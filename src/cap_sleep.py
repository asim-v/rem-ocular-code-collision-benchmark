"""Load CAP Sleep Database EOG and RemLogic stage annotations."""

from __future__ import annotations

import csv
from datetime import datetime
from fractions import Fraction
from io import StringIO
from pathlib import Path
import re
from typing import Sequence

import mne
import numpy as np
from scipy.signal import resample_poly

from src.sleep_edf import (
    SleepEdfRecording,
    annotations_to_mask,
    erode_true_runs,
    flatline_sample_mask,
    summarize_exposure,
)


CLOCK_RE = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d):(?P<second>[0-5]\d)$")
STAGE_EVENTS = {
    "SLEEP-S0",
    "SLEEP-S1",
    "SLEEP-S2",
    "SLEEP-S3",
    "SLEEP-S4",
    "SLEEP-REM",
    "SLEEP-UNSCORED",
}


def clock_seconds(value: str) -> int:
    """Convert a strict 24-hour clock string to seconds after midnight."""

    match = CLOCK_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid RemLogic clock time: {value!r}")
    return (
        int(match.group("hour")) * 3600
        + int(match.group("minute")) * 60
        + int(match.group("second"))
    )


def parse_remlogic_stages(
    text: str,
    *,
    recording_start_clock_seconds: int,
    recording_duration_seconds: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse stage rows and align their clocks to an EDF recording start.

    Clock offsets use modulo one day, which handles a recording that starts
    before midnight and continues after midnight. Stage rows outside the
    recording are rejected rather than shifted heuristically.
    """

    if not 0 <= recording_start_clock_seconds < 86400:
        raise ValueError("recording_start_clock_seconds must lie within one day")
    if not np.isfinite(recording_duration_seconds) or recording_duration_seconds <= 0:
        raise ValueError("recording_duration_seconds must be positive and finite")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Sleep Stage\t")),
        None,
    )
    if header_index is None:
        raise ValueError("RemLogic export lacks the sleep-stage table header")
    reader = csv.DictReader(StringIO("\n".join(lines[header_index:])), delimiter="\t")
    required = {"Time [hh:mm:ss]", "Event", "Duration[s]"}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError("RemLogic stage table lacks required columns")

    rows: list[tuple[float, float, str]] = []
    for row_number, row in enumerate(reader, start=header_index + 2):
        event = (row.get("Event") or "").strip()
        if event not in STAGE_EVENTS:
            continue
        onset_clock = clock_seconds(row.get("Time [hh:mm:ss]") or "")
        onset = float((onset_clock - recording_start_clock_seconds) % 86400)
        try:
            duration = float((row.get("Duration[s]") or "").strip())
        except ValueError as exc:
            raise ValueError(f"invalid stage duration on RemLogic row {row_number}") from exc
        if not np.isfinite(duration) or duration <= 0:
            raise ValueError(f"nonpositive stage duration on RemLogic row {row_number}")
        if onset >= recording_duration_seconds + 1e-6:
            raise ValueError(
                f"stage row {row_number} lies outside the recording after clock alignment"
            )
        if onset + duration > recording_duration_seconds + 30.0 + 1e-6:
            raise ValueError(f"stage row {row_number} extends implausibly beyond the recording")
        rows.append((onset, duration, event))
    if not rows:
        raise ValueError("RemLogic export contains no recognized sleep-stage rows")
    rows.sort(key=lambda item: item[0])
    onsets = np.asarray([row[0] for row in rows], dtype=float)
    durations = np.asarray([row[1] for row in rows], dtype=float)
    events = np.asarray([row[2] for row in rows], dtype=str)
    return onsets, durations, events


def resample_to_target(
    values: Sequence[float] | np.ndarray,
    source_rate_hz: float,
    target_rate_hz: float,
) -> np.ndarray:
    """Polyphase-resample a finite vector with an exact rational rate ratio."""

    signal = np.asarray(values, dtype=float)
    if signal.ndim != 1 or signal.size == 0 or np.any(~np.isfinite(signal)):
        raise ValueError("resampling requires a nonempty finite vector")
    if not np.isfinite(source_rate_hz) or not np.isfinite(target_rate_hz):
        raise ValueError("sample rates must be finite")
    if source_rate_hz <= 0 or target_rate_hz <= 0:
        raise ValueError("sample rates must be positive")
    if np.isclose(source_rate_hz, target_rate_hz, rtol=0.0, atol=1e-12):
        return signal.copy()
    ratio = Fraction(str(target_rate_hz)) / Fraction(str(source_rate_hz))
    output = resample_poly(signal, ratio.numerator, ratio.denominator, padtype="line")
    return np.asarray(output, dtype=float)


def _fill_nonfinite(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nonfinite = ~np.isfinite(values)
    if not nonfinite.any():
        return values.copy(), nonfinite
    finite = ~nonfinite
    if not finite.any():
        raise ValueError("EOG contains no finite samples")
    indices = np.arange(len(values))
    filled = values.copy()
    filled[nonfinite] = np.interp(indices[nonfinite], indices[finite], values[finite])
    return filled, nonfinite


def _project_invalid_mask(
    source_mask: np.ndarray,
    source_rate_hz: float,
    target_samples: int,
    target_rate_hz: float,
) -> np.ndarray:
    if not source_mask.any():
        return np.zeros(target_samples, dtype=bool)
    target_times = np.arange(target_samples, dtype=float) / target_rate_hz
    source_indices = np.minimum(
        len(source_mask) - 1,
        np.floor(target_times * source_rate_hz).astype(int),
    )
    return source_mask[source_indices]


def load_cap_sleep(
    psg_path: str | Path,
    stage_path: str | Path,
    *,
    channel_a: str,
    channel_b: str = "",
    operation: str = "identity",
    expected_source_rate_hz: float,
    target_rate_hz: float = 100.0,
    boundary_margin_seconds: float = 2.0,
    flatline_minimum_seconds: float = 5.0,
    flatline_tolerance_uv: float = 0.0,
) -> SleepEdfRecording:
    """Load one CAP record and create target-rate REM eligibility masks."""

    psg = Path(psg_path).resolve()
    stages = Path(stage_path).resolve()
    if operation not in {"identity", "subtract_a_minus_b"}:
        raise ValueError(f"unsupported EOG operation: {operation}")
    if operation == "identity" and channel_b:
        raise ValueError("identity EOG operation cannot include channel_b")
    if operation == "subtract_a_minus_b" and not channel_b:
        raise ValueError("subtraction EOG operation requires channel_b")
    if boundary_margin_seconds < 0 or not np.isfinite(boundary_margin_seconds):
        raise ValueError("boundary margin must be finite and nonnegative")

    channels = [channel_a] if operation == "identity" else [channel_a, channel_b]
    raw = mne.io.read_raw_edf(psg, include=channels, preload=True, verbose="ERROR")
    try:
        if raw.ch_names != channels:
            raise ValueError(f"expected EOG channels {channels!r}, found {raw.ch_names!r}")
        source_rate = float(raw.info["sfreq"])
        if not np.isclose(source_rate, expected_source_rate_hz, rtol=0.0, atol=1e-9):
            raise ValueError(
                f"expected {expected_source_rate_hz:g} Hz, found {source_rate:g} Hz in {psg.name}"
            )
        meas_date = raw.info.get("meas_date")
        if not isinstance(meas_date, datetime):
            raise ValueError("CAP EDF has no usable recording start date and clock")
        data = np.asarray(raw.get_data(picks=channels), dtype=float) * 1e6
    finally:
        raw.close()
    if data.shape[0] != len(channels) or data.shape[1] == 0:
        raise RuntimeError("MNE returned an unexpected EOG array shape")
    source_eog = data[0] if operation == "identity" else data[0] - data[1]
    filled_source, source_nonfinite = _fill_nonfinite(source_eog)
    eog_uv = resample_to_target(filled_source, source_rate, target_rate_hz)
    nonfinite = _project_invalid_mask(
        source_nonfinite, source_rate, len(eog_uv), target_rate_hz
    )

    recording_seconds = len(eog_uv) / target_rate_hz
    start_clock = meas_date.hour * 3600 + meas_date.minute * 60 + meas_date.second
    stage_text = stages.read_text(encoding="utf-8-sig")
    onsets, durations, events = parse_remlogic_stages(
        stage_text,
        recording_start_clock_seconds=start_clock,
        recording_duration_seconds=recording_seconds,
    )
    rem = annotations_to_mask(
        onsets,
        durations,
        events,
        n_samples=len(eog_uv),
        sample_rate_hz=target_rate_hz,
        target_description="SLEEP-REM",
    )
    margin_samples = int(np.ceil(boundary_margin_seconds * target_rate_hz))
    boundary_rem = erode_true_runs(rem, margin_samples)
    flatline = flatline_sample_mask(
        eog_uv,
        target_rate_hz,
        minimum_duration_seconds=flatline_minimum_seconds,
        tolerance_uv=flatline_tolerance_uv,
    )
    invalid = nonfinite | flatline
    eligible = boundary_rem & ~invalid
    exposure = summarize_exposure(
        rem,
        boundary_rem,
        nonfinite,
        flatline,
        sample_rate_hz=target_rate_hz,
    )
    return SleepEdfRecording(
        psg_path=psg,
        hypnogram_path=stages,
        eog_uv=eog_uv,
        sample_rate_hz=float(target_rate_hz),
        rem_mask=rem,
        boundary_eroded_rem_mask=boundary_rem,
        nonfinite_mask=nonfinite,
        flatline_mask=flatline,
        invalid_mask=invalid,
        eligible_rem_mask=eligible,
        exposure=exposure,
    )
