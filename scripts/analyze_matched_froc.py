#!/usr/bin/env python3
"""Create a matched-synthetic-recovery FROC analysis from saved result CSVs.

No EDF or hypnogram is opened.  Code-specific thresholds are chosen on the
calibration result bundle so the candidate and control recover exactly the same
number of primary-condition synthetic injections.  Those thresholds are then
applied unchanged to the evaluation result bundle.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.benchmark import file_sha256, write_json  # noqa: E402
from src.froc import (  # noqa: E402
    ResultTables,
    build_matched_thresholds,
    build_paired_contrasts,
    evaluate_matched_thresholds,
    load_result_tables,
)


DEFAULT_RESULT_ROOT = REPOSITORY_ROOT / "outputs" / "ocular-code-pilot"
DEFAULT_CALIBRATION = DEFAULT_RESULT_ROOT / "development"
DEFAULT_EVALUATION = DEFAULT_RESULT_ROOT / "test"
DEFAULT_OUTPUT = DEFAULT_RESULT_ROOT / "matched-froc"
DEFAULT_RECOVERY_LEVELS = tuple(float(value) for value in np.arange(0.1, 1.0, 0.1))
INPUT_FILENAMES = (
    "synthetic_recovery.csv",
    "background_events.csv",
    "background_by_recording.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-dir", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--evaluation-dir", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--candidate", default="sync8_c0")
    parser.add_argument("--control", default="iso8_matched")
    parser.add_argument("--scope", default="rem")
    parser.add_argument("--amplitude-mad", type=float, default=4.0)
    parser.add_argument("--interval-jitter-fraction", type=float, default=0.15)
    parser.add_argument(
        "--recovery-levels",
        type=float,
        nargs="+",
        default=DEFAULT_RECOVERY_LEVELS,
        metavar="FRACTION",
    )
    parser.add_argument("--bootstrap-replicates", type=int, default=10_000)
    parser.add_argument("--random-seed", type=int, default=20260819)
    return parser.parse_args()


def require_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(
            f"refusing to overwrite nonempty FROC output directory: {output_dir}"
        )


def input_hashes(tables: ResultTables) -> dict[str, str]:
    return {
        filename: file_sha256(tables.directory / filename)
        for filename in INPUT_FILENAMES
    }


def source_hashes() -> dict[str, str]:
    paths = ("scripts/analyze_matched_froc.py", "src/froc.py", "src/benchmark.py")
    return {path: file_sha256(REPOSITORY_ROOT / path) for path in paths}


def make_froc_figure(
    points: pd.DataFrame,
    *,
    candidate: str,
    control: str,
    output_dir: Path,
) -> None:
    roles = list(dict.fromkeys(points["dataset_role"].tolist()))
    figure, axes = plt.subplots(
        1, len(roles), figsize=(5.2 * len(roles), 4.4), squeeze=False
    )
    colors = {candidate: "#2166ac", control: "#b2182b"}
    markers = {candidate: "o", control: "s"}
    for axis, role in zip(axes[0], roles):
        subset = points[points["dataset_role"] == role]
        for code_id in (candidate, control):
            group = subset[subset["code_id"] == code_id].sort_values(
                "matched_calibration_recovery_fraction"
            )
            x = group["false_events_per_hour"].to_numpy(dtype=float)
            y = group["synthetic_recovery_fraction"].to_numpy(dtype=float)
            lower = group["poisson_lower_per_hour"].to_numpy(dtype=float)
            upper = group["poisson_upper_per_hour"].to_numpy(dtype=float)
            axis.errorbar(
                x,
                y,
                xerr=np.vstack((x - lower, upper - x)),
                color=colors[code_id],
                marker=markers[code_id],
                linewidth=1.5,
                markersize=4.5,
                capsize=2,
                label=code_id,
            )
        axis.set_title(role.capitalize())
        axis.set_xlabel("Background events per eligible REM hour")
        axis.grid(alpha=0.25, linewidth=0.6)
        axis.set_ylim(0.0, 1.0)
    axes[0, 0].set_ylabel("Synthetic recovery (engineering check)")
    axes[0, -1].legend(frameon=False)
    figure.suptitle("FROC at development-matched synthetic recovery")
    figure.tight_layout()
    figure.savefig(
        output_dir / "matched_froc.png",
        dpi=200,
        metadata={"Software": "matplotlib"},
    )
    figure.savefig(
        output_dir / "matched_froc.pdf",
        metadata={"Creator": "matched FROC analysis", "CreationDate": None},
    )
    plt.close(figure)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    require_empty_output(output_dir)

    calibration = load_result_tables(
        args.calibration_dir.resolve(), label="calibration"
    )
    evaluation = load_result_tables(args.evaluation_dir.resolve(), label="evaluation")
    matched = build_matched_thresholds(
        calibration,
        candidate=args.candidate,
        control=args.control,
        amplitude_mad=args.amplitude_mad,
        interval_jitter_fraction=args.interval_jitter_fraction,
        recovery_levels=args.recovery_levels,
        scope=args.scope,
    )

    point_frames: list[pd.DataFrame] = []
    contrast_frames: list[pd.DataFrame] = []
    for role, tables in (("calibration", calibration), ("evaluation", evaluation)):
        role_points = evaluate_matched_thresholds(tables, matched, dataset_role=role)
        point_frames.append(role_points)
        contrast_frames.append(
            build_paired_contrasts(
                tables,
                matched,
                role_points,
                dataset_role=role,
                bootstrap_replicates=args.bootstrap_replicates,
                random_seed=args.random_seed,
            )
        )
    points = pd.concat(point_frames, ignore_index=True)
    contrasts = pd.concat(contrast_frames, ignore_index=True)

    output_dir.mkdir(parents=True, exist_ok=False)
    matched.to_csv(
        output_dir / "matched_thresholds.csv", index=False, lineterminator="\n"
    )
    points.to_csv(output_dir / "froc_points.csv", index=False, lineterminator="\n")
    contrasts.to_csv(
        output_dir / "paired_rate_contrasts.csv", index=False, lineterminator="\n"
    )
    make_froc_figure(
        points,
        candidate=args.candidate,
        control=args.control,
        output_dir=output_dir,
    )

    summary = {
        "schema_version": 1,
        "analysis": "matched-synthetic-recovery FROC",
        "interpretation": (
            "background collision rates at thresholds matched on synthetic "
            "engineering recovery; not human sensitivity"
        ),
        "physiological_recordings_read": False,
        "calibration_result_directory": calibration.directory.as_posix(),
        "evaluation_result_directory": evaluation.directory.as_posix(),
        "candidate": args.candidate,
        "control": args.control,
        "scope": args.scope,
        "synthetic_condition": {
            "amplitude_mad": args.amplitude_mad,
            "interval_jitter_fraction": args.interval_jitter_fraction,
        },
        "requested_recovery_levels": [float(value) for value in args.recovery_levels],
        "bootstrap_replicates": args.bootstrap_replicates,
        "random_seed": args.random_seed,
        "background_coverage_rule": (
            "every derived score threshold must be at or above the code-specific "
            "storage floor"
        ),
        "input_sha256": {
            "calibration": input_hashes(calibration),
            "evaluation": input_hashes(evaluation),
        },
        "source_sha256": source_hashes(),
        "outputs": {
            filename: file_sha256(output_dir / filename)
            for filename in (
                "matched_thresholds.csv",
                "froc_points.csv",
                "paired_rate_contrasts.csv",
                "matched_froc.png",
                "matched_froc.pdf",
            )
        },
    }
    write_json(output_dir / "analysis.json", summary)
    digest = sha256(json.dumps(summary, sort_keys=True).encode("utf-8")).hexdigest()
    print(
        json.dumps(
            {
                "output_directory": output_dir.as_posix(),
                "analysis_digest": digest,
                "operating_points": len(matched),
                "physiological_recordings_read": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
