#!/usr/bin/env python3
"""Run one frozen confirmatory cohort and retain all score-floor candidates."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_ocular_code_benchmark import (  # noqa: E402
    condition_seed,
    detect_with_trailing_amplitude_gate,
    filtered_template_bank,
    longest_injection_samples,
    matched_injection_score,
    trailing_scale,
)
from src.benchmark import (  # noqa: E402
    butterworth_bandpass_sos,
    choose_shared_anchors,
    file_sha256,
    write_json,
    zero_phase_filter,
)
from src.cap_sleep import load_cap_sleep  # noqa: E402
from src.confirmatory_manifest import (  # noqa: E402
    ManifestRecord,
    load_confirmatory_manifest,
    manifest_assets,
)
from src.ocular_codes import (  # noqa: E402
    OcularCode,
    PerturbationSpec,
    WaveformSpec,
    synthesize_perturbed_code,
)
from src.sleep_edf import load_sleep_edf  # noqa: E402


DEFAULT_CONFIG = ROOT / "config" / "confirmatory_benchmark.json"
DEFAULT_CODEBOOK = ROOT / "config" / "codebook.json"
DEFAULT_DATA_ROOT = ROOT / "data" / "confirmatory"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "ocular-code-confirmatory"
SLEEP_MANIFEST = ROOT / "config" / "sleep_edf_confirmatory_manifest.csv"
CAP_MANIFEST = ROOT / "config" / "cap_normal_manifest.csv"
COHORTS = {
    "sc": (SLEEP_MANIFEST, "sleep_edf_sc_confirmatory"),
    "st-placebo": (SLEEP_MANIFEST, "sleep_edf_st_placebo"),
    "st-temazepam": (SLEEP_MANIFEST, "sleep_edf_st_temazepam"),
    "cap-normal": (CAP_MANIFEST, "cap_normal_external"),
}
TRANSPORT_GATE = DEFAULT_OUTPUT_ROOT / "sc-analysis" / "locked_thresholds.json"
CAP_GATE = ROOT / "config" / "cap_analysis_gate.json"
IMPLEMENTATION_PATHS = (
    "scripts/run_confirmatory_benchmark.py",
    "scripts/analyze_confirmatory_froc.py",
    "scripts/run_ocular_code_benchmark.py",
    "src/benchmark.py",
    "src/cap_sleep.py",
    "src/confirmatory_manifest.py",
    "src/froc.py",
    "src/ocular_codes.py",
    "src/sleep_edf.py",
)
CONFIG_PATHS = (
    "config/codebook.json",
    "config/confirmatory_benchmark.json",
    "config/sleep_edf_confirmatory_manifest.csv",
    "config/cap_normal_manifest.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=tuple(COHORTS), required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--codebook", type=Path, default=DEFAULT_CODEBOOK)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_frozen_revision(paths: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    tracked_changes = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if tracked_changes.strip():
        raise RuntimeError("confirmatory run requires no tracked worktree changes")
    hashes: dict[str, str] = {}
    for relative in paths:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if tracked.returncode:
            raise RuntimeError(f"confirmatory input is not tracked: {relative}")
        differs = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative],
            cwd=ROOT,
        )
        if differs.returncode == 1:
            raise RuntimeError(f"confirmatory input differs from HEAD: {relative}")
        if differs.returncode:
            raise subprocess.CalledProcessError(differs.returncode, differs.args)
        head_bytes = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        from hashlib import sha256

        hashes[relative] = sha256(head_bytes).hexdigest()
    return git_commit(), hashes


def require_stage_gate(cohort: str) -> None:
    gate = None
    if cohort in {"st-placebo", "st-temazepam"}:
        gate = TRANSPORT_GATE
    elif cohort == "cap-normal":
        gate = CAP_GATE
    if gate is None:
        return
    if not gate.is_file():
        raise RuntimeError(f"cohort {cohort} remains sealed until tracked gate exists: {gate}")
    relative = gate.resolve().relative_to(ROOT).as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if tracked.returncode:
        raise RuntimeError(f"stage gate is not tracked: {relative}")


def record_directory(data_root: Path, record: ManifestRecord) -> Path:
    return data_root.joinpath(*record.local_subdirectory.parts)


def verify_assets(records: tuple[ManifestRecord, ...], data_root: Path) -> None:
    problems: list[str] = []
    for asset in manifest_assets(records):
        path = data_root.joinpath(*asset.local_subdirectory.parts) / asset.filename
        if not path.is_file():
            problems.append(f"missing {path}")
            continue
        observed = file_sha256(path)
        if observed != asset.sha256:
            problems.append(
                f"SHA256 mismatch for {path.name}: expected {asset.sha256}, observed {observed}"
            )
    if problems:
        raise RuntimeError("\n".join(problems))


def load_recording(record: ManifestRecord, data_root: Path, config: dict):
    directory = record_directory(data_root, record)
    signal = directory / record.signal_file
    annotation = directory / record.annotation_file
    exposure = config["exposure"]
    if record.dataset == "sleep-edf":
        return load_sleep_edf(
            signal,
            annotation,
            channel=record.eog_channel_a,
            required_sample_rate_hz=record.source_sample_rate_hz,
            rem_description="Sleep stage R",
            boundary_margin_seconds=float(exposure["rem_boundary_margin_seconds"]),
            flatline_minimum_seconds=float(exposure["flatline_minimum_seconds"]),
            flatline_tolerance_uv=float(exposure["flatline_tolerance_uv"]),
        )
    return load_cap_sleep(
        signal,
        annotation,
        channel_a=record.eog_channel_a,
        channel_b=record.eog_channel_b,
        operation=record.eog_operation,
        expected_source_rate_hz=record.source_sample_rate_hz,
        target_rate_hz=record.target_sample_rate_hz,
        boundary_margin_seconds=float(exposure["rem_boundary_margin_seconds"]),
        flatline_minimum_seconds=float(exposure["flatline_minimum_seconds"]),
        flatline_tolerance_uv=float(exposure["flatline_tolerance_uv"]),
    )


def detection_rows(detections, record: ManifestRecord, scope: str, sfreq: float):
    return [
        {
            "subject_id": record.participant_id,
            "record_id": record.record_id,
            "scope": scope,
            "code_id": item.code_id,
            "start_seconds": item.start_sample / sfreq,
            "end_seconds": item.end_sample / sfreq,
            "center_seconds": item.center_sample / sfreq,
            "time_scale": item.time_scale,
            "score": item.score,
            "signed_score": item.signed_score,
            "fitted_amplitude_uv": item.fitted_amplitude,
            "amplitude_mad": item.amplitude_mad,
            "polarity": item.polarity,
        }
        for item in detections
    ]


def primary_synthetic_rows(
    *,
    raw_eog: np.ndarray,
    filtered_eog: np.ndarray,
    invalid_mask: np.ndarray,
    eligible_rem_mask: np.ndarray,
    record: ManifestRecord,
    codes: list[OcularCode],
    templates: dict,
    waveform: WaveformSpec,
    config: dict,
    sos: np.ndarray,
    maximum_signal_samples: int,
) -> list[dict]:
    synthetic = config["synthetic_injection"]
    detector = config["detector"]
    preprocessing = config["preprocessing"]
    sfreq = waveform.sample_rate_hz
    anchors = choose_shared_anchors(
        eligible_rem_mask,
        maximum_signal_samples,
        int(round(float(synthetic["minimum_anchor_separation_seconds"]) * sfreq)),
        int(synthetic["anchors_per_recording"]),
        np.random.default_rng(
            condition_seed(int(config["random_seed"]), record.record_id, "anchors")
        ),
        candidate_stride_samples=int(round(sfreq)),
    )
    if not len(anchors):
        return []
    amplitude_mad = float(synthetic["primary_amplitude_mad"])
    jitter = float(synthetic["primary_interval_jitter_fraction"])
    perturbation = PerturbationSpec.from_mapping(
        synthetic, interval_jitter_fraction=jitter
    )
    shared_seed = condition_seed(
        int(config["random_seed"]), record.record_id, amplitude_mad, jitter, "paired-shape"
    )
    rows: list[dict] = []
    for code in codes:
        rng = np.random.default_rng(shared_seed)
        injected = raw_eog.copy()
        truths: list[tuple[int, float, int, int]] = []
        for anchor_index, anchor in enumerate(anchors):
            scale = trailing_scale(
                filtered_eog,
                invalid_mask,
                int(anchor),
                sfreq,
                float(preprocessing["calibration_seconds"]),
                float(preprocessing["minimum_calibration_seconds"]),
            )
            signal = synthesize_perturbed_code(
                code,
                waveform,
                amplitude=amplitude_mad * scale,
                rng=rng,
                perturbation=perturbation,
            )
            stop = int(anchor) + len(signal)
            if stop > len(injected) or len(signal) > maximum_signal_samples:
                raise RuntimeError("prespecified maximum injection length was exceeded")
            injected[int(anchor):stop] += signal
            truths.append((int(anchor), scale, len(signal), anchor_index))
        filtered_injected = zero_phase_filter(injected, sos)
        for anchor, scale, signal_samples, anchor_index in truths:
            score, detected_start, detected_scale = matched_injection_score(
                filtered_injected,
                eligible_rem_mask,
                anchor,
                maximum_signal_samples,
                templates[code.code_id],
                scale,
                detector,
                sfreq,
            )
            rows.append(
                {
                    "subject_id": record.participant_id,
                    "record_id": record.record_id,
                    "code_id": code.code_id,
                    "anchor_index": anchor_index,
                    "anchor_seconds": anchor / sfreq,
                    "amplitude_mad": amplitude_mad,
                    "interval_jitter_fraction": jitter,
                    "local_mad_uv": scale,
                    "injection_samples": signal_samples,
                    "maximum_matched_score": score,
                    "detected_start_seconds": detected_start,
                    "detected_time_scale": detected_scale,
                    "paired_perturbation_seed": shared_seed,
                    "engineering_check_only": True,
                }
            )
    return rows


def write_record_bundle(
    staging: Path,
    record: ManifestRecord,
    exposure_row: dict,
    events: list[dict],
    background_rows: list[dict],
    synthetic_rows: list[dict],
    run_fingerprint: str,
) -> None:
    records_root = staging / "records"
    records_root.mkdir(parents=True, exist_ok=True)
    final = records_root / record.record_id
    if final.exists():
        return
    temp = Path(tempfile.mkdtemp(prefix="record-", dir=staging))
    pd.DataFrame([exposure_row]).to_csv(temp / "exposure.csv", index=False)
    pd.DataFrame(events, columns=EVENT_COLUMNS).to_csv(
        temp / "background_events.csv", index=False
    )
    pd.DataFrame(background_rows).to_csv(
        temp / "background_by_recording.csv", index=False
    )
    pd.DataFrame(synthetic_rows, columns=SYNTHETIC_COLUMNS).to_csv(
        temp / "synthetic_recovery.csv", index=False
    )
    write_json(
        temp / "complete.json",
        {
            "record_id": record.record_id,
            "signal_sha256": record.signal_sha256,
            "annotation_sha256": record.annotation_sha256,
            "run_fingerprint": run_fingerprint,
        },
    )
    os.replace(temp, final)


def combine_csv(record_dirs: list[Path], filename: str, destination: Path) -> None:
    with destination.open("wb") as output:
        wrote_header = False
        for directory in record_dirs:
            lines = (directory / filename).read_bytes().splitlines(keepends=True)
            if not lines:
                continue
            if not wrote_header:
                output.write(lines[0])
                wrote_header = True
            for line in lines[1:]:
                output.write(line)
        if not wrote_header:
            raise RuntimeError(f"no record table was available for {filename}")


EVENT_COLUMNS = [
    "subject_id",
    "record_id",
    "scope",
    "code_id",
    "start_seconds",
    "end_seconds",
    "center_seconds",
    "time_scale",
    "score",
    "signed_score",
    "fitted_amplitude_uv",
    "amplitude_mad",
    "polarity",
]
SYNTHETIC_COLUMNS = [
    "subject_id",
    "record_id",
    "code_id",
    "anchor_index",
    "anchor_seconds",
    "amplitude_mad",
    "interval_jitter_fraction",
    "local_mad_uv",
    "injection_samples",
    "maximum_matched_score",
    "detected_start_seconds",
    "detected_time_scale",
    "paired_perturbation_seed",
    "engineering_check_only",
]


def main() -> None:
    args = parse_args()
    if args.config.resolve() != DEFAULT_CONFIG.resolve():
        raise RuntimeError("confirmatory execution requires the frozen default config")
    if args.codebook.resolve() != DEFAULT_CODEBOOK.resolve():
        raise RuntimeError("confirmatory execution requires the frozen default codebook")
    require_stage_gate(args.cohort)
    manifest_path, cohort_id = COHORTS[args.cohort]
    relevant_paths = tuple(dict.fromkeys((*IMPLEMENTATION_PATHS, *CONFIG_PATHS)))
    commit, hashes = require_frozen_revision(relevant_paths)
    config = load_json(args.config.resolve())
    codebook = load_json(args.codebook.resolve())
    records = load_confirmatory_manifest(manifest_path, cohorts=[cohort_id])
    data_root = args.data_root.resolve()
    print(f"Verifying {2 * len(records)} source assets before signal access...")
    verify_assets(records, data_root)

    output_dir = args.output_root.resolve() / args.cohort
    staging = output_dir.with_name(output_dir.name + ".inprogress")
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite completed output: {output_dir}")
    run_document = {
        "schema_version": 1,
        "cohort": args.cohort,
        "cohort_id": cohort_id,
        "git_commit": commit,
        "frozen_sha256": hashes,
        "physiological_interpretation": "background collision benchmark",
        "human_sensitivity_estimated": False,
    }
    from hashlib import sha256

    run_fingerprint = sha256(
        json.dumps(run_document, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if staging.exists():
        if not args.resume:
            raise RuntimeError(f"incomplete run exists; pass --resume: {staging}")
        prior = load_json(staging / "run.json")
        if prior != run_document:
            raise RuntimeError("incomplete run was created by a different frozen revision")
    else:
        staging.mkdir(parents=True)
        write_json(staging / "run.json", run_document)

    waveform = WaveformSpec.from_mapping(codebook["waveform"])
    primary_ids = set(config["code_sets"]["primary_froc"])
    codes = [
        OcularCode.from_mapping(value)
        for value in codebook["codes"]
        if value["id"] in primary_ids
    ]
    if {code.code_id for code in codes} != primary_ids:
        raise ValueError("one or more primary FROC codes are missing from the codebook")
    preprocessing = config["preprocessing"]
    detector = config["detector"]
    sos = butterworth_bandpass_sos(
        waveform.sample_rate_hz,
        float(preprocessing["highpass_hz"]),
        float(preprocessing["lowpass_hz"]),
        int(preprocessing["filter_order"]),
    )
    templates = {
        code.code_id: filtered_template_bank(
            code, waveform, list(detector["time_scales"]), sos
        )
        for code in codes
    }
    length_config = dict(config["synthetic_injection"])
    length_config["interval_jitter_fraction"] = [
        float(length_config["primary_interval_jitter_fraction"])
    ]
    maximum_signal_samples = longest_injection_samples(codes, waveform, length_config)

    completed = {
        directory.name
        for directory in (staging / "records").glob("*")
        if directory.is_dir() and (directory / "complete.json").is_file()
    } if (staging / "records").exists() else set()
    for index, record in enumerate(records, start=1):
        if record.record_id in completed:
            completion = load_json(staging / "records" / record.record_id / "complete.json")
            if completion.get("run_fingerprint") != run_fingerprint:
                raise RuntimeError(f"record checkpoint has wrong fingerprint: {record.record_id}")
            print(f"[{index}/{len(records)}] {record.record_id}: verified checkpoint")
            continue
        print(f"[{index}/{len(records)}] {record.record_id}: load and filter")
        recording = load_recording(record, data_root, config)
        filtered = zero_phase_filter(recording.eog_uv, sos)
        exposure_row = recording.exposure.to_dict()
        exposure_row.update(
            {
                "subject_id": record.participant_id,
                "record_id": record.record_id,
                "cohort": record.cohort,
                "condition": record.condition,
                "signal_file": record.signal_file,
                "recording_hours": recording.exposure.recording_seconds / 3600.0,
            }
        )
        event_rows: list[dict] = []
        background_rows: list[dict] = []
        print(f"[{index}/{len(records)}] {record.record_id}: score-floor background scan")
        for code in codes:
            detections = detect_with_trailing_amplitude_gate(
                signal=filtered,
                templates=templates[code.code_id],
                eligible_mask=recording.eligible_rem_mask,
                invalid_mask=recording.invalid_mask,
                detector=detector,
                preprocessing=preprocessing,
                sfreq=recording.sample_rate_hz,
            )
            event_rows.extend(detection_rows(detections, record, "rem", recording.sample_rate_hz))
            background_rows.append(
                {
                    "subject_id": record.participant_id,
                    "record_id": record.record_id,
                    "scope": "rem",
                    "code_id": code.code_id,
                    "threshold": float(detector["minimum_candidate_score"]),
                    "events": len(detections),
                    "exposure_hours": recording.exposure.eligible_rem_hours,
                }
            )
        print(f"[{index}/{len(records)}] {record.record_id}: paired synthetic reference")
        synthetic_rows = primary_synthetic_rows(
            raw_eog=recording.eog_uv,
            filtered_eog=filtered,
            invalid_mask=recording.invalid_mask,
            eligible_rem_mask=recording.eligible_rem_mask,
            record=record,
            codes=codes,
            templates=templates,
            waveform=waveform,
            config=config,
            sos=sos,
            maximum_signal_samples=maximum_signal_samples,
        )
        write_record_bundle(
            staging,
            record,
            exposure_row,
            event_rows,
            background_rows,
            synthetic_rows,
            run_fingerprint,
        )

    record_dirs = [staging / "records" / record.record_id for record in records]
    for directory in record_dirs:
        if not (directory / "complete.json").is_file():
            raise RuntimeError(f"missing completed record checkpoint: {directory.name}")
    for filename in (
        "exposure.csv",
        "background_events.csv",
        "background_by_recording.csv",
        "synthetic_recovery.csv",
    ):
        combine_csv(record_dirs, filename, staging / filename)
    exposure = pd.read_csv(staging / "exposure.csv")
    by_recording = pd.read_csv(staging / "background_by_recording.csv")
    synthetic = pd.read_csv(staging / "synthetic_recovery.csv")
    summary = {
        **run_document,
        "records": len(records),
        "participants": int(exposure["subject_id"].nunique()),
        "eligible_rem_hours": float(exposure["eligible_rem_hours"].sum()),
        "primary_synthetic_injections": int(len(synthetic) / len(codes)),
        "score_floor_background_candidates": int(by_recording["events"].sum()),
        "candidate_storage_floor": float(detector["minimum_candidate_score"]),
        "physiological_recordings_read": True,
    }
    write_json(staging / "summary.json", summary)
    os.replace(staging, output_dir)
    print(json.dumps(summary, indent=2))
    print(f"Completed immutable cohort output: {output_dir}")


if __name__ == "__main__":
    main()
