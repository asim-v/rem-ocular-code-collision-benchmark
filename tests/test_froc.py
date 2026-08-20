import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from src.froc import (
    BackgroundCoverageError,
    ResultTables,
    UnattainableRecoveryError,
    bootstrap_matched_froc_rate_difference,
    build_matched_thresholds,
    build_paired_contrasts,
    evaluate_matched_thresholds,
    load_result_tables,
    paired_cluster_bootstrap_rate_difference,
    select_at_least_recovery_threshold,
    select_exact_recovery_threshold,
)


ROOT = Path(__file__).resolve().parents[1]


def _frames():
    subjects = ["a"] * 5 + ["b"] * 5
    anchors = list(range(5)) * 2
    anchor_seconds = [100.0 + value for value in anchors] + [
        200.0 + value for value in anchors
    ]
    candidate_scores = [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]
    control_scores = [0.98, 0.88, 0.84, 0.82, 0.77, 0.68, 0.64, 0.62, 0.57, 0.52]
    synthetic_rows = []
    for code_id, scores in (("c0", candidate_scores), ("iso", control_scores)):
        for subject, anchor, seconds, score in zip(
            subjects, anchors, anchor_seconds, scores
        ):
            synthetic_rows.append(
                {
                    "subject_id": subject,
                    "code_id": code_id,
                    "anchor_index": anchor,
                    "anchor_seconds": seconds,
                    "amplitude_mad": 4.0,
                    "interval_jitter_fraction": 0.15,
                    "maximum_matched_score": score,
                    "engineering_check_only": True,
                }
            )
    synthetic = pd.DataFrame(synthetic_rows)

    event_scores = {
        ("a", "c0"): [0.90, 0.70, 0.55],
        ("b", "c0"): [0.80, 0.61],
        ("a", "iso"): [0.92, 0.76, 0.63],
        ("b", "iso"): [0.81, 0.65, 0.51],
    }
    event_rows = []
    for (subject, code_id), scores in event_scores.items():
        for score in scores:
            event_rows.append(
                {
                    "subject_id": subject,
                    "scope": "rem",
                    "code_id": code_id,
                    "score": score,
                }
            )
    events = pd.DataFrame(event_rows)
    background_rows = []
    for code_id in ("c0", "iso"):
        for subject, hours in (("a", 1.0), ("b", 2.0)):
            background_rows.append(
                {
                    "subject_id": subject,
                    "scope": "rem",
                    "code_id": code_id,
                    "threshold": 0.5,
                    "events": len(event_scores[(subject, code_id)]),
                    "exposure_hours": hours,
                }
            )
    return synthetic, events, pd.DataFrame(background_rows)


def _tables(tmp_path: Path, label: str = "fixture") -> ResultTables:
    synthetic, events, by_recording = _frames()
    return ResultTables(label, tmp_path, synthetic, events, by_recording)


def _write_bundle(path: Path) -> None:
    synthetic, events, by_recording = _frames()
    path.mkdir(parents=True)
    synthetic.to_csv(path / "synthetic_recovery.csv", index=False)
    events.to_csv(path / "background_events.csv", index=False)
    by_recording.to_csv(path / "background_by_recording.csv", index=False)


def test_exact_threshold_uses_largest_score_with_requested_count():
    result = select_exact_recovery_threshold([0.9, 0.8, 0.7, 0.6], 0.5)

    assert result.recoveries == 2
    assert result.trials == 4
    assert result.achieved_fraction == 0.5
    assert result.threshold == 0.8


def test_exact_threshold_rejects_boundary_ties():
    with pytest.raises(UnattainableRecoveryError, match="ties"):
        select_exact_recovery_threshold([0.9, 0.8, 0.8, 0.7], 0.5)


def test_at_least_threshold_retains_boundary_ties_and_reports_recovery():
    result = select_at_least_recovery_threshold([0.9, 0.8, 0.8, 0.7], 0.5)

    assert result.threshold == 0.8
    assert result.recoveries == 3
    assert result.achieved_fraction == 0.75


def test_matched_thresholds_have_equal_calibration_recovery(tmp_path):
    matched = build_matched_thresholds(
        _tables(tmp_path),
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_levels=[0.5, 0.8],
    )

    assert matched["matched_recoveries"].tolist() == [5, 8]
    assert matched["candidate_threshold"].tolist() == [0.75, 0.60]
    assert matched["control_threshold"].tolist() == [0.77, 0.62]


def test_matched_thresholds_fail_below_stored_event_floor(tmp_path):
    tables = _tables(tmp_path)
    tables.background_by_recording.loc[:, "threshold"] = 0.65
    tables.background_events.drop(
        tables.background_events[tables.background_events["score"] < 0.65].index,
        inplace=True,
    )

    with pytest.raises(BackgroundCoverageError, match="below stored-event floor"):
        build_matched_thresholds(
            tables,
            candidate="c0",
            control="iso",
            amplitude_mad=4.0,
            interval_jitter_fraction=0.15,
            recovery_levels=[0.8],
        )


def test_evaluation_counts_false_events_at_code_specific_matched_thresholds(tmp_path):
    tables = _tables(tmp_path)
    matched = build_matched_thresholds(
        tables,
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_levels=[0.5, 0.8],
    )
    points = evaluate_matched_thresholds(tables, matched, dataset_role="calibration")

    high_recovery = points[points["requested_recovery_fraction"] == 0.8]
    candidate = high_recovery[high_recovery["code_role"] == "candidate"].iloc[0]
    control = high_recovery[high_recovery["code_role"] == "control"].iloc[0]
    assert candidate["synthetic_recoveries"] == control["synthetic_recoveries"] == 8
    assert candidate["background_events"] == 4
    assert control["background_events"] == 5
    assert candidate["false_events_per_hour"] == pytest.approx(4 / 3)
    assert control["false_events_per_hour"] == pytest.approx(5 / 3)


def test_paired_contrast_uses_subject_cluster_and_is_reproducible(tmp_path):
    tables = _tables(tmp_path)
    matched = build_matched_thresholds(
        tables,
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_levels=[0.8],
    )
    points = evaluate_matched_thresholds(tables, matched, dataset_role="evaluation")
    first = build_paired_contrasts(
        tables,
        matched,
        points,
        dataset_role="evaluation",
        bootstrap_replicates=500,
        random_seed=17,
    )
    second = build_paired_contrasts(
        tables,
        matched,
        points,
        dataset_role="evaluation",
        bootstrap_replicates=500,
        random_seed=17,
    )

    pd.testing.assert_frame_equal(first, second)
    assert first.loc[0, "candidate_minus_control_rate_per_hour"] == pytest.approx(
        -1 / 3
    )
    assert first.loc[0, "participants"] == 2


def test_paired_contrast_aggregates_repeated_nights_by_subject(tmp_path):
    tables = _tables(tmp_path)
    split_rows = []
    for row in tables.background_by_recording.to_dict("records"):
        first = dict(row)
        second = dict(row)
        first["exposure_hours"] = row["exposure_hours"] / 2
        second["exposure_hours"] = row["exposure_hours"] / 2
        split_rows.extend([first, second])
    repeated = ResultTables(
        tables.label,
        tables.directory,
        tables.synthetic,
        tables.background_events,
        pd.DataFrame(split_rows),
    )
    matched = build_matched_thresholds(
        repeated,
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_levels=[0.8],
    )
    points = evaluate_matched_thresholds(
        repeated, matched, dataset_role="evaluation"
    )
    contrast = build_paired_contrasts(
        repeated,
        matched,
        points,
        dataset_role="evaluation",
        bootstrap_replicates=100,
        random_seed=9,
    )
    assert contrast.loc[0, "participants"] == 2
    assert contrast.loc[0, "candidate_minus_control_rate_per_hour"] == pytest.approx(
        -1 / 3
    )


def test_cluster_bootstrap_validates_paired_vectors():
    with pytest.raises(ValueError, match="same nonzero length"):
        paired_cluster_bootstrap_rate_difference(
            [1, 2], [1], [1.0, 1.0], replicates=10, seed=1
        )


def test_matched_froc_bootstrap_reselects_thresholds_reproducibly(tmp_path):
    tables = _tables(tmp_path)
    first = bootstrap_matched_froc_rate_difference(
        tables,
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_target=0.8,
        replicates=200,
        seed=41,
    )
    second = bootstrap_matched_froc_rate_difference(
        tables,
        candidate="c0",
        control="iso",
        amplitude_mad=4.0,
        interval_jitter_fraction=0.15,
        recovery_target=0.8,
        replicates=200,
        seed=41,
    )

    assert first == second
    assert first.candidate_threshold == 0.6
    assert first.control_threshold == 0.62
    assert first.candidate_recovery == first.control_recovery == 0.8
    assert first.estimate == pytest.approx(-1 / 3)


def test_loader_and_cli_use_only_saved_result_tables(tmp_path):
    calibration = tmp_path / "development"
    evaluation = tmp_path / "test"
    output = tmp_path / "froc"
    _write_bundle(calibration)
    _write_bundle(evaluation)

    loaded = load_result_tables(calibration, label="development")
    assert loaded.label == "development"
    assert len(loaded.synthetic) == 20

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analyze_matched_froc.py"),
            "--calibration-dir",
            str(calibration),
            "--evaluation-dir",
            str(evaluation),
            "--output-dir",
            str(output),
            "--candidate",
            "c0",
            "--control",
            "iso",
            "--recovery-levels",
            "0.5",
            "0.8",
            "--bootstrap-replicates",
            "100",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    expected = {
        "matched_thresholds.csv",
        "froc_points.csv",
        "paired_rate_contrasts.csv",
        "matched_froc.png",
        "matched_froc.pdf",
        "analysis.json",
    }
    assert expected == {path.name for path in output.iterdir()}
    analysis = json.loads((output / "analysis.json").read_text())
    assert analysis["physiological_recordings_read"] is False
    assert set(analysis["input_sha256"]) == {"calibration", "evaluation"}
