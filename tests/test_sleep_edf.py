from __future__ import annotations

import csv
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.sleep_edf import (  # noqa: E402
    align_annotation_onsets,
    annotations_to_mask,
    erode_true_runs,
    flatline_sample_mask,
    load_sleep_edf,
    objective_invalid_mask,
    summarize_exposure,
)


def load_fetch_module():
    path = REPOSITORY_ROOT / "scripts" / "fetch_sleep_edf.py"
    spec = importlib.util.spec_from_file_location("fetch_sleep_edf", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fetch_sleep_edf = load_fetch_module()


class FakeResponse:
    def __init__(self, payload: bytes, status: int):
        self.payload = payload
        self.status = status
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int) -> bytes:
        block = self.payload[self.offset:self.offset + size]
        self.offset += len(block)
        return block


class FakeRaw:
    def __init__(
        self,
        volts: np.ndarray,
        sample_rate_hz: float = 100.0,
        meas_date: datetime | None = None,
        first_time: float = 0.0,
    ):
        self._volts = np.asarray(volts, dtype=float)
        self.info = {"sfreq": sample_rate_hz, "meas_date": meas_date}
        self.n_times = len(self._volts)
        self.ch_names = ["EOG horizontal"]
        self.first_time = first_time
        self.closed = False

    def get_data(self, picks):
        if picks != ["EOG horizontal"]:
            raise AssertionError(picks)
        return self._volts[np.newaxis, :]

    def close(self):
        self.closed = True


class FakeAnnotations:
    def __init__(self, onset, duration, description, orig_time=None):
        self.onset = np.asarray(onset, dtype=float)
        self.duration = np.asarray(duration, dtype=float)
        self.description = np.asarray(description, dtype=str)
        self.orig_time = orig_time


class MaskTests(unittest.TestCase):
    def test_absolute_annotation_origin_is_aligned_to_first_psg_sample(self):
        recording_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        aligned = align_annotation_onsets(
            [0.0, 30.0],
            annotation_orig_time=recording_start + timedelta(seconds=12),
            recording_meas_date=recording_start,
            recording_first_time_seconds=2.0,
        )
        np.testing.assert_array_equal(aligned, [10.0, 40.0])

    def test_absolute_annotations_require_psg_measurement_date(self):
        with self.assertRaisesRegex(ValueError, "PSG has no meas_date"):
            align_annotation_onsets(
                [0.0],
                annotation_orig_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                recording_meas_date=None,
            )

    def test_annotations_clip_merge_and_preserve_exact_length(self):
        mask = annotations_to_mask(
            [-0.5, 1.0, 1.5, 3.0],
            [1.0, 1.0, 1.0, 1.0],
            ["Sleep stage R", "Sleep stage R", "Sleep stage R", "Sleep stage W"],
            n_samples=30,
            sample_rate_hz=10.0,
        )
        expected = np.zeros(30, dtype=bool)
        expected[0:5] = True
        expected[10:25] = True
        np.testing.assert_array_equal(mask, expected)

    def test_subsample_annotation_uses_half_open_sample_timestamps(self):
        mask = annotations_to_mask(
            [0.005],
            [0.020],
            ["Sleep stage R"],
            n_samples=5,
            sample_rate_hz=100.0,
        )
        np.testing.assert_array_equal(mask, [False, True, True, False, False])

    def test_each_rem_run_is_eroded_independently(self):
        mask = np.array(
            [False, True, True, True, True, True, False, True, True, False]
        )
        np.testing.assert_array_equal(
            erode_true_runs(mask, 1),
            [False, False, True, True, True, False, False, False, False, False],
        )

    def test_nonfinite_and_sustained_flatline_are_objective_masks(self):
        signal = np.array([0.0, 0.0, 0.0, 1.0, np.nan, 2.0, 2.0, 2.0])
        invalid, nonfinite, flatline = objective_invalid_mask(
            signal,
            1.0,
            flatline_minimum_seconds=3.0,
        )
        np.testing.assert_array_equal(
            flatline,
            [True, True, True, False, False, True, True, True],
        )
        np.testing.assert_array_equal(
            nonfinite,
            [False, False, False, False, True, False, False, False],
        )
        np.testing.assert_array_equal(invalid, flatline | nonfinite)

    def test_flatline_tolerance_is_explicit(self):
        signal = np.array([1.0, 1.01, 1.02])
        self.assertFalse(
            flatline_sample_mask(
                signal, 1.0, minimum_duration_seconds=3.0, tolerance_uv=0.0
            ).any()
        )
        self.assertTrue(
            flatline_sample_mask(
                signal, 1.0, minimum_duration_seconds=3.0, tolerance_uv=0.011
            ).all()
        )

    def test_exposure_report_counts_overlap_only_once(self):
        rem = np.array([False, True, True, True, True, False])
        boundary = np.array([False, False, True, True, False, False])
        nonfinite = np.array([False, False, True, False, False, False])
        flatline = np.array([False, False, True, True, False, False])
        report = summarize_exposure(
            rem,
            boundary,
            nonfinite,
            flatline,
            sample_rate_hz=2.0,
        )
        self.assertEqual(report.invalid_boundary_eroded_rem_samples, 2)
        self.assertEqual(report.nonfinite_boundary_eroded_rem_samples, 1)
        self.assertEqual(report.flatline_boundary_eroded_rem_samples, 2)
        self.assertEqual(report.eligible_rem_samples, 0)
        self.assertEqual(report.rem_seconds, 2.0)


class LoaderTests(unittest.TestCase):
    def test_loader_converts_volts_and_aligns_all_masks(self):
        volts = np.linspace(-2e-6, 2e-6, 1000)
        raw = FakeRaw(volts)
        annotations = FakeAnnotations(
            [1.0, 5.0],
            [3.0, 2.0],
            ["Sleep stage R", "Sleep stage R"],
        )
        with (
            patch("src.sleep_edf.mne.io.read_raw_edf", return_value=raw),
            patch("src.sleep_edf.mne.read_annotations", return_value=annotations),
        ):
            recording = load_sleep_edf(
                "synthetic-PSG.edf",
                "synthetic-Hypnogram.edf",
                boundary_margin_seconds=1.0,
            )
        self.assertTrue(raw.closed)
        np.testing.assert_allclose(recording.eog_uv, volts * 1e6)
        self.assertEqual(len(recording.rem_mask), len(volts))
        self.assertEqual(recording.exposure.rem_samples, 500)
        self.assertEqual(recording.exposure.boundary_eroded_rem_samples, 100)
        self.assertEqual(recording.exposure.eligible_rem_samples, 100)
        self.assertEqual(recording.exposure.eligible_rem_seconds, 1.0)

    def test_loader_rejects_wrong_sample_rate_and_closes_raw(self):
        raw = FakeRaw(np.arange(10), sample_rate_hz=128.0)
        with patch("src.sleep_edf.mne.io.read_raw_edf", return_value=raw):
            with self.assertRaisesRegex(ValueError, "expected 100 Hz"):
                load_sleep_edf("x.edf", "y.edf")
        self.assertTrue(raw.closed)

    def test_loader_applies_absolute_hypnogram_clock_offset(self):
        recording_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        raw = FakeRaw(
            np.linspace(0.0, 1e-6, 1000),
            meas_date=recording_start,
        )
        annotations = FakeAnnotations(
            [0.0],
            [1.0],
            ["Sleep stage R"],
            orig_time=recording_start + timedelta(seconds=2),
        )
        with (
            patch("src.sleep_edf.mne.io.read_raw_edf", return_value=raw),
            patch("src.sleep_edf.mne.read_annotations", return_value=annotations),
        ):
            recording = load_sleep_edf(
                "synthetic-PSG.edf",
                "synthetic-Hypnogram.edf",
                boundary_margin_seconds=0.0,
            )
        expected = np.zeros(1000, dtype=bool)
        expected[200:300] = True
        np.testing.assert_array_equal(recording.rem_mask, expected)


class FetchTests(unittest.TestCase):
    def _write_manifest(self, path: Path, payload: bytes):
        digest = hashlib.sha256(payload).hexdigest()
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "subject_id",
                    "split",
                    "psg_file",
                    "psg_sha256",
                    "hypnogram_file",
                    "hypnogram_sha256",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "subject_id": "00",
                    "split": "development",
                    "psg_file": "night-PSG.edf",
                    "psg_sha256": digest,
                    "hypnogram_file": "night-Hypnogram.edf",
                    "hypnogram_sha256": digest,
                }
            )
        return digest

    def test_manifest_split_yields_two_validated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.csv"
            self._write_manifest(path, b"content")
            specs = fetch_sleep_edf.load_manifest(path, "development")
        self.assertEqual([spec.role for spec in specs], ["psg", "hypnogram"])
        self.assertEqual({spec.subject_id for spec in specs}, {"00"})

    def test_download_resumes_part_and_atomically_publishes(self):
        payload = b"abcdefghij"
        digest = hashlib.sha256(payload).hexdigest()
        spec = fetch_sleep_edf.DownloadSpec(
            "00", "development", "psg", "night.edf", digest
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            part = root / "night.edf.part"
            part.write_bytes(payload[:4])

            def fake_urlopen(request, timeout):
                self.assertEqual(request.get_header("Range"), "bytes=4-")
                return FakeResponse(payload[4:], 206)

            with patch.object(fetch_sleep_edf, "urlopen", side_effect=fake_urlopen):
                result = fetch_sleep_edf.download_one(
                    spec, root, "https://example.invalid", retries=0
                )
            self.assertEqual(result.status, "downloaded")
            self.assertEqual((root / "night.edf").read_bytes(), payload)
            self.assertFalse(part.exists())

    def test_corrupt_destination_is_redownloaded(self):
        payload = b"verified bytes"
        digest = hashlib.sha256(payload).hexdigest()
        spec = fetch_sleep_edf.DownloadSpec(
            "00", "development", "psg", "night.edf", digest
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "night.edf"
            destination.write_bytes(b"corrupt")
            with patch.object(
                fetch_sleep_edf,
                "urlopen",
                return_value=FakeResponse(payload, 200),
            ):
                fetch_sleep_edf.download_one(
                    spec, root, "https://example.invalid", retries=0
                )
            self.assertEqual(destination.read_bytes(), payload)

    def test_checksum_failure_restarts_partial_file(self):
        payload = b"correct payload"
        digest = hashlib.sha256(payload).hexdigest()
        spec = fetch_sleep_edf.DownloadSpec(
            "00", "development", "psg", "night.edf", digest
        )
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "night.edf.part").write_bytes(b"bad-prefix")

            def fake_urlopen(request, timeout):
                range_header = request.get_header("Range")
                calls.append(range_header)
                if range_header:
                    return FakeResponse(payload[len(b"bad-prefix"):], 206)
                return FakeResponse(payload, 200)

            with patch.object(fetch_sleep_edf, "urlopen", side_effect=fake_urlopen):
                fetch_sleep_edf.download_one(
                    spec, root, "https://example.invalid", retries=1
                )
            self.assertEqual(calls, ["bytes=10-", None])
            self.assertEqual((root / "night.edf").read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
