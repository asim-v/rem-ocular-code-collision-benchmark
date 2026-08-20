from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from src.cap_sleep import (
    load_cap_sleep,
    parse_remlogic_stages,
    resample_to_target,
)


STAGE_TEXT = """RemLogic Event Export
Patient:\tSynthetic

Sleep Stage\tPosition\tTime [hh:mm:ss]\tEvent\tDuration[s]\tLocation
W\tUnknown\t23:59:30\tSLEEP-S0\t30\tROC-LOC
R\tUnknown\t00:00:00\tSLEEP-REM\t30\tROC-LOC
R\tUnknown\t00:00:30\tSLEEP-REM\t30\tROC-LOC
"""


class FakeRaw:
    def __init__(self, data, channels, sample_rate_hz, meas_date):
        self._data = np.asarray(data, dtype=float)
        self.ch_names = list(channels)
        self.info = {"sfreq": sample_rate_hz, "meas_date": meas_date}
        self.closed = False

    def get_data(self, picks):
        assert picks == self.ch_names
        return self._data

    def close(self):
        self.closed = True


def test_remlogic_clock_alignment_handles_midnight():
    onsets, durations, events = parse_remlogic_stages(
        STAGE_TEXT,
        recording_start_clock_seconds=23 * 3600 + 59 * 60 + 30,
        recording_duration_seconds=90.0,
    )
    np.testing.assert_array_equal(onsets, [0.0, 30.0, 60.0])
    np.testing.assert_array_equal(durations, [30.0, 30.0, 30.0])
    assert events.tolist() == ["SLEEP-S0", "SLEEP-REM", "SLEEP-REM"]


def test_remlogic_rejects_stage_shifted_outside_recording():
    text = STAGE_TEXT.replace("00:00:30", "12:00:30")
    with pytest.raises(ValueError, match="outside the recording"):
        parse_remlogic_stages(
            text,
            recording_start_clock_seconds=23 * 3600 + 59 * 60 + 30,
            recording_duration_seconds=90.0,
        )


def test_polyphase_resampling_has_expected_length_and_is_deterministic():
    values = np.sin(2 * np.pi * np.arange(1280) / 128)
    first = resample_to_target(values, 128.0, 100.0)
    second = resample_to_target(values, 128.0, 100.0)
    assert len(first) == 1000
    np.testing.assert_array_equal(first, second)


def test_cap_loader_subtracts_channels_resamples_and_aligns_rem(tmp_path: Path):
    source_rate = 128.0
    seconds = 90
    samples = int(source_rate * seconds)
    time = np.arange(samples) / source_rate
    left_volts = 2e-6 * np.sin(2 * np.pi * time)
    right_volts = -left_volts
    raw = FakeRaw(
        np.vstack([right_volts, left_volts]),
        ["ROC-A2", "LOC-A1"],
        source_rate,
        datetime(2026, 1, 1, 23, 59, 30, tzinfo=timezone.utc),
    )
    stage_path = tmp_path / "stages.txt"
    stage_path.write_text(STAGE_TEXT, encoding="utf-8")
    with patch("src.cap_sleep.mne.io.read_raw_edf", return_value=raw):
        recording = load_cap_sleep(
            tmp_path / "signal.edf",
            stage_path,
            channel_a="ROC-A2",
            channel_b="LOC-A1",
            operation="subtract_a_minus_b",
            expected_source_rate_hz=128.0,
            target_rate_hz=100.0,
            boundary_margin_seconds=2.0,
        )
    assert raw.closed
    assert len(recording.eog_uv) == 9000
    assert recording.sample_rate_hz == 100.0
    assert recording.exposure.rem_seconds == 60.0
    assert recording.exposure.boundary_eroded_rem_seconds == 56.0
    assert recording.exposure.eligible_rem_seconds == 56.0
    assert np.max(np.abs(recording.eog_uv)) > 3.5
