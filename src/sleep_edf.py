"""Read Sleep-EDF EOG and construct auditable REM eligibility masks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

import mne
import numpy as np
from numpy.typing import NDArray


BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ExposureReport:
    """Sample counts behind every reported REM exposure quantity."""

    sample_rate_hz: float
    recording_samples: int
    rem_samples: int
    boundary_eroded_rem_samples: int
    nonfinite_samples: int
    flatline_samples: int
    nonfinite_boundary_eroded_rem_samples: int
    flatline_boundary_eroded_rem_samples: int
    invalid_boundary_eroded_rem_samples: int
    eligible_rem_samples: int

    @property
    def recording_seconds(self) -> float:
        return self.recording_samples / self.sample_rate_hz

    @property
    def rem_seconds(self) -> float:
        return self.rem_samples / self.sample_rate_hz

    @property
    def boundary_eroded_rem_seconds(self) -> float:
        return self.boundary_eroded_rem_samples / self.sample_rate_hz

    @property
    def eligible_rem_seconds(self) -> float:
        return self.eligible_rem_samples / self.sample_rate_hz

    @property
    def eligible_rem_hours(self) -> float:
        return self.eligible_rem_seconds / 3600.0

    def to_dict(self) -> dict[str, float | int]:
        result: dict[str, float | int] = asdict(self)
        result.update(
            {
                "recording_seconds": self.recording_seconds,
                "rem_seconds": self.rem_seconds,
                "boundary_eroded_rem_seconds": self.boundary_eroded_rem_seconds,
                "eligible_rem_seconds": self.eligible_rem_seconds,
                "eligible_rem_hours": self.eligible_rem_hours,
            }
        )
        return result


@dataclass(frozen=True)
class SleepEdfRecording:
    """Horizontal EOG plus masks aligned sample for sample."""

    psg_path: Path
    hypnogram_path: Path
    eog_uv: FloatArray
    sample_rate_hz: float
    rem_mask: BoolArray
    boundary_eroded_rem_mask: BoolArray
    nonfinite_mask: BoolArray
    flatline_mask: BoolArray
    invalid_mask: BoolArray
    eligible_rem_mask: BoolArray
    exposure: ExposureReport


def _one_dimensional(values: Sequence[object] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return array


def _seconds_to_left_sample(seconds: float, sample_rate_hz: float) -> int:
    # The first included sample is the first timestamp at or after the boundary.
    return int(np.ceil(seconds * sample_rate_hz - 1e-10))


def align_annotation_onsets(
    onsets_seconds: Sequence[float] | np.ndarray,
    *,
    annotation_orig_time: datetime | None,
    recording_meas_date: datetime | None,
    recording_first_time_seconds: float = 0.0,
) -> FloatArray:
    """Express MNE annotation onsets relative to the first PSG sample.

    An annotation file with ``orig_time=None`` is already relative to the
    recording and is returned unchanged. For absolute annotation times, this
    applies the same origin correction used by ``Raw.set_annotations``, while
    retaining intervals outside the recording so rasterization can clip them
    transparently.
    """

    onsets = _one_dimensional(onsets_seconds, "onsets_seconds").astype(float)
    if not np.isfinite(recording_first_time_seconds):
        raise ValueError("recording_first_time_seconds must be finite")
    if annotation_orig_time is None:
        return onsets.copy()
    if recording_meas_date is None:
        raise ValueError(
            "hypnogram has an absolute orig_time but the PSG has no meas_date"
        )
    try:
        origin_delta_seconds = (
            annotation_orig_time - recording_meas_date
        ).total_seconds()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "hypnogram orig_time and PSG meas_date cannot be aligned"
        ) from exc
    if not np.isfinite(origin_delta_seconds):
        raise ValueError("annotation clock offset must be finite")
    return onsets + origin_delta_seconds - recording_first_time_seconds


def annotations_to_mask(
    onsets_seconds: Sequence[float] | np.ndarray,
    durations_seconds: Sequence[float] | np.ndarray,
    descriptions: Sequence[str] | np.ndarray,
    *,
    n_samples: int,
    sample_rate_hz: float,
    target_description: str = "Sleep stage R",
) -> BoolArray:
    """Rasterize and merge matching half-open annotation intervals.

    Intervals are clipped to the recording bounds. Overlap and adjacency are
    merged naturally by the Boolean mask, whose length is always exactly
    ``n_samples``.
    """

    if n_samples < 0:
        raise ValueError("n_samples must be nonnegative")
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive and finite")
    onsets = _one_dimensional(onsets_seconds, "onsets_seconds").astype(float)
    durations = _one_dimensional(durations_seconds, "durations_seconds").astype(float)
    labels = _one_dimensional(descriptions, "descriptions").astype(str)
    if not (len(onsets) == len(durations) == len(labels)):
        raise ValueError("annotation arrays must have equal length")

    mask = np.zeros(n_samples, dtype=bool)
    for onset, duration, description in zip(onsets, durations, labels):
        if description != target_description:
            continue
        if not np.isfinite(onset) or not np.isfinite(duration) or duration < 0:
            raise ValueError("matching annotations require finite, nonnegative timing")
        interval_start = max(0, _seconds_to_left_sample(onset, sample_rate_hz))
        interval_stop = min(
            n_samples,
            _seconds_to_left_sample(onset + duration, sample_rate_hz),
        )
        if interval_stop > interval_start:
            mask[interval_start:interval_stop] = True
    return mask


def erode_true_runs(mask: Sequence[bool] | np.ndarray, margin_samples: int) -> BoolArray:
    """Remove ``margin_samples`` from both ends of every True run."""

    values = _one_dimensional(mask, "mask").astype(bool, copy=False)
    if margin_samples < 0:
        raise ValueError("margin_samples must be nonnegative")
    if margin_samples == 0 or not values.any():
        return values.copy()
    edges = np.diff(np.pad(values.astype(np.int8), (1, 1)))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    eroded = np.zeros_like(values)
    for start, stop in zip(starts, stops):
        kept_start = int(start + margin_samples)
        kept_stop = int(stop - margin_samples)
        if kept_stop > kept_start:
            eroded[kept_start:kept_stop] = True
    return eroded


def nonfinite_sample_mask(signal: Sequence[float] | np.ndarray) -> BoolArray:
    """Mark NaN and infinite samples without imputing them."""

    values = _one_dimensional(signal, "signal").astype(float, copy=False)
    return ~np.isfinite(values)


def flatline_sample_mask(
    signal_uv: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    minimum_duration_seconds: float = 5.0,
    tolerance_uv: float = 0.0,
) -> BoolArray:
    """Mark sustained finite plateaus using a prespecified absolute tolerance.

    A plateau is a contiguous run in which every adjacent change is no larger
    than ``tolerance_uv``. The default therefore marks only exactly repeated
    finite samples lasting at least five seconds. No variance or
    physiology-dependent rejection criterion is used.
    """

    values = _one_dimensional(signal_uv, "signal_uv").astype(float, copy=False)
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive and finite")
    if not np.isfinite(minimum_duration_seconds) or minimum_duration_seconds <= 0:
        raise ValueError("minimum_duration_seconds must be positive and finite")
    if not np.isfinite(tolerance_uv) or tolerance_uv < 0:
        raise ValueError("tolerance_uv must be finite and nonnegative")
    minimum_samples = max(2, int(np.ceil(minimum_duration_seconds * sample_rate_hz)))
    result = np.zeros(len(values), dtype=bool)
    if len(values) < minimum_samples:
        return result

    finite = np.isfinite(values)
    flat_steps = (
        finite[:-1]
        & finite[1:]
        & (np.abs(np.diff(values)) <= tolerance_uv)
    )
    if not flat_steps.any():
        return result
    edges = np.diff(np.pad(flat_steps.astype(np.int8), (1, 1)))
    step_starts = np.flatnonzero(edges == 1)
    step_stops = np.flatnonzero(edges == -1)
    for step_start, step_stop in zip(step_starts, step_stops):
        sample_stop = int(step_stop + 1)
        if sample_stop - step_start >= minimum_samples:
            result[int(step_start):sample_stop] = True
    return result


def objective_invalid_mask(
    signal_uv: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    flatline_minimum_seconds: float = 5.0,
    flatline_tolerance_uv: float = 0.0,
) -> tuple[BoolArray, BoolArray, BoolArray]:
    """Return combined, nonfinite, and sustained-flatline masks."""

    nonfinite = nonfinite_sample_mask(signal_uv)
    flatline = flatline_sample_mask(
        signal_uv,
        sample_rate_hz,
        minimum_duration_seconds=flatline_minimum_seconds,
        tolerance_uv=flatline_tolerance_uv,
    )
    return nonfinite | flatline, nonfinite, flatline


def summarize_exposure(
    rem_mask: Sequence[bool] | np.ndarray,
    boundary_eroded_rem_mask: Sequence[bool] | np.ndarray,
    nonfinite_mask: Sequence[bool] | np.ndarray,
    flatline_mask: Sequence[bool] | np.ndarray,
    *,
    sample_rate_hz: float,
) -> ExposureReport:
    """Count total, REM, excluded, and eligible samples explicitly."""

    arrays = [
        _one_dimensional(values, name).astype(bool, copy=False)
        for values, name in (
            (rem_mask, "rem_mask"),
            (boundary_eroded_rem_mask, "boundary_eroded_rem_mask"),
            (nonfinite_mask, "nonfinite_mask"),
            (flatline_mask, "flatline_mask"),
        )
    ]
    lengths = {len(array) for array in arrays}
    if len(lengths) != 1:
        raise ValueError("all exposure masks must have identical length")
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive and finite")
    rem, boundary_rem, nonfinite, flatline = arrays
    if np.any(boundary_rem & ~rem):
        raise ValueError("boundary-eroded REM must be a subset of REM")
    invalid = nonfinite | flatline
    invalid_rem = invalid & boundary_rem
    eligible = boundary_rem & ~invalid
    return ExposureReport(
        sample_rate_hz=float(sample_rate_hz),
        recording_samples=len(rem),
        rem_samples=int(rem.sum()),
        boundary_eroded_rem_samples=int(boundary_rem.sum()),
        nonfinite_samples=int(nonfinite.sum()),
        flatline_samples=int(flatline.sum()),
        nonfinite_boundary_eroded_rem_samples=int((nonfinite & boundary_rem).sum()),
        flatline_boundary_eroded_rem_samples=int((flatline & boundary_rem).sum()),
        invalid_boundary_eroded_rem_samples=int(invalid_rem.sum()),
        eligible_rem_samples=int(eligible.sum()),
    )


def load_sleep_edf(
    psg_path: str | Path,
    hypnogram_path: str | Path,
    *,
    channel: str = "EOG horizontal",
    required_sample_rate_hz: float = 100.0,
    rem_description: str = "Sleep stage R",
    boundary_margin_seconds: float = 2.0,
    flatline_minimum_seconds: float = 5.0,
    flatline_tolerance_uv: float = 0.0,
) -> SleepEdfRecording:
    """Load one pilot night and create sample-aligned REM eligibility masks."""

    psg = Path(psg_path).resolve()
    hypnogram = Path(hypnogram_path).resolve()
    if boundary_margin_seconds < 0 or not np.isfinite(boundary_margin_seconds):
        raise ValueError("boundary_margin_seconds must be finite and nonnegative")

    raw = mne.io.read_raw_edf(
        psg,
        include=[channel],
        preload=True,
        verbose="ERROR",
    )
    try:
        if raw.ch_names != [channel]:
            raise ValueError(
                f"expected only channel {channel!r}, found {raw.ch_names!r}"
            )
        sample_rate_hz = float(raw.info["sfreq"])
        if not np.isclose(
            sample_rate_hz,
            required_sample_rate_hz,
            rtol=0.0,
            atol=1e-9,
        ):
            raise ValueError(
                f"expected {required_sample_rate_hz:g} Hz, found "
                f"{sample_rate_hz:g} Hz in {psg.name}"
            )
        n_samples = int(raw.n_times)
        recording_meas_date = raw.info.get("meas_date")
        recording_first_time = float(raw.first_time)
        # MNE returns EDF physiological channels in SI volts.
        eog_uv = np.asarray(raw.get_data(picks=[channel])[0], dtype=float) * 1e6
    finally:
        raw.close()
    if len(eog_uv) != n_samples:
        raise RuntimeError("MNE returned a signal length inconsistent with raw.n_times")

    annotations = mne.read_annotations(hypnogram)
    aligned_onsets = align_annotation_onsets(
        annotations.onset,
        annotation_orig_time=annotations.orig_time,
        recording_meas_date=recording_meas_date,
        recording_first_time_seconds=recording_first_time,
    )
    rem_mask = annotations_to_mask(
        aligned_onsets,
        annotations.duration,
        annotations.description,
        n_samples=n_samples,
        sample_rate_hz=sample_rate_hz,
        target_description=rem_description,
    )
    margin_samples = int(np.ceil(boundary_margin_seconds * sample_rate_hz))
    boundary_rem = erode_true_runs(rem_mask, margin_samples)
    invalid, nonfinite, flatline = objective_invalid_mask(
        eog_uv,
        sample_rate_hz,
        flatline_minimum_seconds=flatline_minimum_seconds,
        flatline_tolerance_uv=flatline_tolerance_uv,
    )
    eligible_rem = boundary_rem & ~invalid
    exposure = summarize_exposure(
        rem_mask,
        boundary_rem,
        nonfinite,
        flatline,
        sample_rate_hz=sample_rate_hz,
    )
    if not all(
        len(mask) == n_samples
        for mask in (
            rem_mask,
            boundary_rem,
            nonfinite,
            flatline,
            invalid,
            eligible_rem,
        )
    ):
        raise RuntimeError("one or more masks are not aligned to the EOG")

    return SleepEdfRecording(
        psg_path=psg,
        hypnogram_path=hypnogram,
        eog_uv=eog_uv,
        sample_rate_hz=sample_rate_hz,
        rem_mask=rem_mask,
        boundary_eroded_rem_mask=boundary_rem,
        nonfinite_mask=nonfinite,
        flatline_mask=flatline,
        invalid_mask=invalid,
        eligible_rem_mask=eligible_rem,
        exposure=exposure,
    )
