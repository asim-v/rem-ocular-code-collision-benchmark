#!/usr/bin/env python3
"""Analyze frozen score-floor tables at matched synthetic recovery."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import json
from pathlib import Path
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchmark import file_sha256, write_json  # noqa: E402
from src.froc import (  # noqa: E402
    bootstrap_matched_froc_rate_difference,
    build_matched_thresholds,
    evaluate_matched_thresholds,
    load_result_tables,
    select_synthetic_condition,
)


DEFAULT_CONFIG = ROOT / "config" / "confirmatory_benchmark.json"
DEFAULT_INPUT = ROOT / "outputs" / "ocular-code-confirmatory" / "sc"
DEFAULT_OUTPUT = ROOT / "outputs" / "ocular-code-confirmatory" / "sc-analysis"
SOURCE_PATHS = (
    "scripts/analyze_confirmatory_froc.py",
    "src/froc.py",
    "src/benchmark.py",
    "config/confirmatory_benchmark.json",
)
INPUT_FILES = (
    "synthetic_recovery.csv",
    "background_events.csv",
    "background_by_recording.csv",
    "summary.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def require_empty(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise RuntimeError(f"refusing to overwrite nonempty analysis output: {path}")


def frozen_source_hashes() -> tuple[str, dict[str, str]]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise RuntimeError("confirmatory analysis requires no tracked worktree changes")
    hashes: dict[str, str] = {}
    for relative in SOURCE_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=ROOT,
            capture_output=True,
        )
        if tracked.returncode:
            raise RuntimeError(f"analysis source is not tracked: {relative}")
        hashes[relative] = file_sha256(ROOT / relative)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, hashes


def descriptive_score_grid(tables, config: dict, candidate: str, control: str) -> pd.DataFrame:
    synthetic_cfg = config["synthetic_injection"]
    froc_cfg = config["froc"]
    selected = select_synthetic_condition(
        tables.synthetic,
        (candidate, control),
        amplitude_mad=float(synthetic_cfg["primary_amplitude_mad"]),
        interval_jitter_fraction=float(
            synthetic_cfg["primary_interval_jitter_fraction"]
        ),
    )
    thresholds = np.arange(
        float(froc_cfg["descriptive_score_grid_start"]),
        float(froc_cfg["descriptive_score_grid_stop"]) + 1e-12,
        float(froc_cfg["descriptive_score_grid_step"]),
    )
    rows: list[dict] = []
    for code_id in (candidate, control):
        injection_scores = selected.loc[
            selected["code_id"] == code_id, "maximum_matched_score"
        ].to_numpy(dtype=float)
        background_scores = tables.background_events.loc[
            (tables.background_events["code_id"] == code_id)
            & (tables.background_events["scope"] == "rem"),
            "score",
        ].to_numpy(dtype=float)
        exposure = float(
            tables.background_by_recording.loc[
                (tables.background_by_recording["code_id"] == code_id)
                & (tables.background_by_recording["scope"] == "rem"),
                "exposure_hours",
            ].sum()
        )
        if exposure <= 0:
            raise ValueError(f"no positive REM exposure for {code_id}")
        for threshold in thresholds:
            recoveries = int(np.count_nonzero(injection_scores >= threshold))
            events = int(np.count_nonzero(background_scores >= threshold))
            rows.append(
                {
                    "code_id": code_id,
                    "threshold": float(threshold),
                    "synthetic_recoveries": recoveries,
                    "synthetic_trials": len(injection_scores),
                    "synthetic_recovery_fraction": recoveries / len(injection_scores),
                    "background_events": events,
                    "exposure_hours": exposure,
                    "false_events_per_hour": events / exposure,
                    "engineering_check_only": True,
                }
            )
    return pd.DataFrame(rows)


def make_figure(grid: pd.DataFrame, points: pd.DataFrame, output: Path) -> None:
    colors = {"sync8_c0": "#2166ac", "iso8_matched": "#b2182b"}
    figure, axis = plt.subplots(figsize=(6.2, 4.6))
    for code_id in ("sync8_c0", "iso8_matched"):
        curve = grid[grid["code_id"] == code_id].sort_values(
            "synthetic_recovery_fraction"
        )
        axis.plot(
            curve["false_events_per_hour"],
            curve["synthetic_recovery_fraction"],
            color=colors[code_id],
            linewidth=1.5,
            label=code_id,
        )
        primary = points[
            (points["code_id"] == code_id)
            & np.isclose(points["requested_recovery_fraction"], 0.9)
        ]
        axis.scatter(
            primary["false_events_per_hour"],
            primary["synthetic_recovery_fraction"],
            color=colors[code_id],
            edgecolor="white",
            linewidth=0.7,
            s=52,
            zorder=3,
        )
    axis.set_xlabel("Background detections per eligible REM hour")
    axis.set_ylabel("Synthetic engineering recovery")
    axis.set_ylim(0.0, 1.01)
    axis.grid(alpha=0.22)
    axis.legend(frameon=False)
    axis.set_title("Confirmatory matched-recovery FROC")
    figure.tight_layout()
    figure.savefig(output / "confirmatory_froc.png", dpi=240, bbox_inches="tight")
    figure.savefig(
        output / "confirmatory_froc.pdf",
        bbox_inches="tight",
        metadata={"Creator": "confirmatory FROC analysis", "CreationDate": None},
    )
    plt.close(figure)


def main() -> None:
    args = parse_args()
    if args.config.resolve() != DEFAULT_CONFIG.resolve():
        raise RuntimeError("confirmatory analysis requires the frozen default config")
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    require_empty(output_dir)
    commit, source_hashes = frozen_source_hashes()
    config = load_json(args.config.resolve())
    tables = load_result_tables(input_dir, label="sleep_edf_sc_confirmatory")
    inference = config["inference"]
    synthetic = config["synthetic_injection"]
    froc = config["froc"]
    candidate = str(inference["primary_candidate"])
    control = str(inference["primary_control"])
    levels = sorted(
        {
            float(froc["primary_recovery_target"]),
            *(float(value) for value in froc["secondary_recovery_targets"]),
        }
    )
    matched = build_matched_thresholds(
        tables,
        candidate=candidate,
        control=control,
        amplitude_mad=float(synthetic["primary_amplitude_mad"]),
        interval_jitter_fraction=float(synthetic["primary_interval_jitter_fraction"]),
        recovery_levels=levels,
        scope="rem",
    )
    points = evaluate_matched_thresholds(
        tables, matched, dataset_role="primary_confirmation"
    )
    contrast_rows: list[dict] = []
    for level in levels:
        interval = bootstrap_matched_froc_rate_difference(
            tables,
            candidate=candidate,
            control=control,
            amplitude_mad=float(synthetic["primary_amplitude_mad"]),
            interval_jitter_fraction=float(
                synthetic["primary_interval_jitter_fraction"]
            ),
            recovery_target=level,
            scope="rem",
            replicates=int(inference["bootstrap_replicates"]),
            seed=int(inference["bootstrap_seed"]) + int(round(level * 1000)),
        )
        ratio = (
            interval.candidate_rate / interval.control_rate
            if interval.control_rate > 0
            else None
        )
        contrast_rows.append(
            {
                "requested_recovery_fraction": level,
                **asdict(interval),
                "rate_ratio": ratio,
                "statistical_superiority": interval.upper < 0,
                "practical_advance_gate": (
                    ratio is not None
                    and ratio <= float(inference["practical_advance_rate_ratio_maximum"])
                ),
                "engineering_check_only": True,
            }
        )
    contrasts = pd.DataFrame(contrast_rows)
    grid = descriptive_score_grid(tables, config, candidate, control)

    output_dir.mkdir(parents=True, exist_ok=False)
    matched.to_csv(output_dir / "matched_thresholds.csv", index=False, lineterminator="\n")
    points.to_csv(output_dir / "matched_froc_points.csv", index=False, lineterminator="\n")
    contrasts.to_csv(output_dir / "clustered_contrasts.csv", index=False, lineterminator="\n")
    grid.to_csv(output_dir / "score_grid_froc.csv", index=False, lineterminator="\n")
    make_figure(grid, points, output_dir)

    primary_level = float(froc["primary_recovery_target"])
    primary_thresholds = matched[
        np.isclose(matched["requested_recovery_fraction"], primary_level)
    ].iloc[0]
    primary_contrast = contrasts[
        np.isclose(contrasts["requested_recovery_fraction"], primary_level)
    ].iloc[0]
    input_hashes = {
        filename: file_sha256(input_dir / filename) for filename in INPUT_FILES
    }
    locked = {
        "schema_version": 1,
        "source_cohort": "sleep_edf_sc_confirmatory",
        "interpretation": "thresholds selected from synthetic engineering recovery only",
        "human_sensitivity_estimated": False,
        "git_commit": commit,
        "candidate": candidate,
        "control": control,
        "recovery_target": primary_level,
        "candidate_threshold": float(primary_thresholds["candidate_threshold"]),
        "control_threshold": float(primary_thresholds["control_threshold"]),
        "candidate_calibration_recovery_fraction": float(
            primary_thresholds["candidate_calibration_recovery_fraction"]
        ),
        "control_calibration_recovery_fraction": float(
            primary_thresholds["control_calibration_recovery_fraction"]
        ),
        "source_sha256": source_hashes,
        "input_sha256": input_hashes,
    }
    write_json(output_dir / "locked_thresholds.json", locked)
    summary = {
        "schema_version": 1,
        "analysis": "confirmatory matched-recovery FROC",
        "physiological_recordings_read": False,
        "human_sensitivity_estimated": False,
        "git_commit": commit,
        "input_sha256": input_hashes,
        "source_sha256": source_hashes,
        "primary": {
            key: (value.item() if isinstance(value, np.generic) else value)
            for key, value in primary_contrast.to_dict().items()
        },
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"Wrote immutable analysis output: {output_dir}")


if __name__ == "__main__":
    main()
