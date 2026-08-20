#!/usr/bin/env python3
"""Analyze the frozen ST-placebo high-recovery external replication."""

from __future__ import annotations

from dataclasses import asdict
import argparse
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_confirmatory_benchmark import require_frozen_revision  # noqa: E402
from src.benchmark import file_sha256, write_json  # noqa: E402
from src.froc import (  # noqa: E402
    bootstrap_matched_froc_rate_difference,
    build_matched_thresholds,
    evaluate_matched_thresholds,
    load_result_tables,
)


DEFAULT_GATE = ROOT / "config" / "external_95_st_gate.json"
DEFAULT_INPUT = ROOT / "outputs" / "ocular-code-external95" / "st-placebo"
DEFAULT_OUTPUT = ROOT / "outputs" / "ocular-code-external95" / "st-analysis"
INPUT_FILES = (
    "synthetic_recovery.csv",
    "background_events.csv",
    "background_by_recording.csv",
    "summary.json",
)
SOURCE_PATHS = (
    "scripts/analyze_external_95_froc.py",
    "scripts/run_confirmatory_benchmark.py",
    "src/froc.py",
    "src/benchmark.py",
    "config/confirmatory_benchmark.json",
    "config/external_95_st_gate.json",
    "outputs/ocular-code-confirmatory/sc-analysis/matched_thresholds.csv",
    "outputs/ocular-code-confirmatory/sc-analysis/clustered_contrasts.csv",
    "outputs/ocular-code-confirmatory/sc-analysis/summary.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def require_empty(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise RuntimeError(f"refusing to overwrite nonempty analysis output: {path}")


def verify_sc_provenance(gate: dict, source_hashes: dict[str, str]) -> None:
    files = gate["generated_from"]["files"]
    for relative, expected in files.items():
        observed = source_hashes.get(relative)
        if observed != expected:
            raise RuntimeError(f"SC source hash mismatch: {relative}")


def fixed_sc_threshold_frame(gate: dict) -> pd.DataFrame:
    frozen = gate["sc_95_descriptive_thresholds"]
    return pd.DataFrame(
        [
            {
                "requested_recovery_fraction": float(gate["recovery_target"]),
                "matched_recoveries": int(frozen["recoveries"]),
                "matched_trials": int(frozen["trials"]),
                "matched_recovery_fraction": float(frozen["recovery_fraction"]),
                "candidate_code_id": str(gate["candidate"]),
                "candidate_threshold": float(frozen["candidate_threshold"]),
                "control_code_id": str(gate["control"]),
                "control_threshold": float(frozen["control_threshold"]),
                "amplitude_mad": float(gate["amplitude_mad"]),
                "interval_jitter_fraction": float(
                    gate["interval_jitter_fraction"]
                ),
                "scope": "rem",
            }
        ]
    )


def main() -> None:
    args = parse_args()
    if args.gate.resolve() != DEFAULT_GATE.resolve():
        raise RuntimeError("external analysis requires the frozen default gate")
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    require_empty(output_dir)
    commit, source_hashes = require_frozen_revision(SOURCE_PATHS)
    gate = load_json(args.gate.resolve())
    if gate["primary_cohort"] != "sleep_edf_st_placebo":
        raise ValueError("external gate does not identify the ST placebo cohort")
    if float(gate["candidate_storage_floor"]) != 0.0:
        raise ValueError("external analysis requires complete zero-floor support")
    verify_sc_provenance(gate, source_hashes)

    tables = load_result_tables(input_dir, label="sleep_edf_st_placebo")
    candidate = str(gate["candidate"])
    control = str(gate["control"])
    recovery_target = float(gate["recovery_target"])
    amplitude = float(gate["amplitude_mad"])
    jitter = float(gate["interval_jitter_fraction"])
    matched = build_matched_thresholds(
        tables,
        candidate=candidate,
        control=control,
        amplitude_mad=amplitude,
        interval_jitter_fraction=jitter,
        recovery_levels=[recovery_target],
        scope="rem",
    )
    points = evaluate_matched_thresholds(
        tables,
        matched,
        dataset_role="external_95_primary",
    )
    interval = bootstrap_matched_froc_rate_difference(
        tables,
        candidate=candidate,
        control=control,
        amplitude_mad=amplitude,
        interval_jitter_fraction=jitter,
        recovery_target=recovery_target,
        scope="rem",
        replicates=int(gate["bootstrap_replicates"]),
        seed=int(gate["bootstrap_seed"]),
    )
    ratio = (
        interval.candidate_rate / interval.control_rate
        if interval.control_rate > 0
        else None
    )
    superiority = interval.upper < 0
    practical = (
        ratio is not None
        and ratio <= float(gate["practical_rate_ratio_maximum"])
    )
    advance_cap = bool(superiority and practical)

    fixed_points = evaluate_matched_thresholds(
        tables,
        fixed_sc_threshold_frame(gate),
        dataset_role="sc_95_threshold_transport_descriptive",
    )
    input_hashes = {
        filename: file_sha256(input_dir / filename) for filename in INPUT_FILES
    }
    contrast = {
        "requested_recovery_fraction": recovery_target,
        **asdict(interval),
        "rate_ratio": ratio,
        "statistical_superiority": superiority,
        "practical_gate": practical,
        "external_replication": advance_cap,
        "engineering_check_only": True,
    }
    locked = matched.iloc[0].to_dict()
    locked.update(
        {
            "schema_version": 1,
            "source_cohort": "sleep_edf_st_placebo",
            "git_commit": commit,
            "input_sha256": input_hashes,
            "source_sha256": source_hashes,
            "human_sensitivity_estimated": False,
        }
    )
    summary = {
        "schema_version": 1,
        "analysis": "external 95% matched-recovery FROC replication",
        "git_commit": commit,
        "input_sha256": input_hashes,
        "source_sha256": source_hashes,
        "primary": contrast,
        "advance_cap": advance_cap,
        "temazepam_opened": False,
        "cap_opened": False,
        "physiological_recordings_read": False,
        "human_sensitivity_estimated": False,
        "psi_claim_permitted": False,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    matched.to_csv(
        output_dir / "matched_thresholds.csv", index=False, lineterminator="\n"
    )
    points.to_csv(
        output_dir / "matched_froc_points.csv", index=False, lineterminator="\n"
    )
    fixed_points.to_csv(
        output_dir / "sc_95_threshold_transport.csv",
        index=False,
        lineterminator="\n",
    )
    pd.DataFrame([contrast]).to_csv(
        output_dir / "clustered_contrast.csv", index=False, lineterminator="\n"
    )
    write_json(output_dir / "locked_thresholds.json", locked)
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"Wrote immutable external analysis output: {output_dir}")


if __name__ == "__main__":
    main()
