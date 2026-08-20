#!/usr/bin/env python3
"""Run the prespecified Sleep-EDF ocular-code collision pilot.

Development selects one threshold per code using synthetic engineering
recoverability only. The test split is sealed: it requires committed thresholds,
an unchanged implementation, and a clean Git worktree before any EDF is read.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.benchmark import (  # noqa: E402
    butterworth_bandpass_sos,
    choose_shared_anchors,
    clopper_pearson,
    exact_poisson_rate,
    file_sha256,
    frozen_run_metadata,
    prespecified_threshold_grid,
    query_window_false_probability,
    robust_mad,
    select_synthetic_threshold,
    write_json,
    zero_phase_filter,
)
from src.ocular_codes import (  # noqa: E402
    Detection,
    OcularCode,
    OcularTemplate,
    PerturbationSpec,
    WaveformSpec,
    build_template_bank,
    detect_code,
    non_maximum_suppression,
    synthesize_perturbed_code,
)
from src.sleep_edf import load_sleep_edf  # noqa: E402


DEFAULT_BENCHMARK = REPOSITORY_ROOT / "config" / "benchmark.json"
DEFAULT_CODEBOOK = REPOSITORY_ROOT / "config" / "codebook.json"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "config" / "sleep_edf_pilot_manifest.csv"
DEFAULT_DATA_ROOT = REPOSITORY_ROOT / "data" / "sleep-edf" / "sleep-cassette"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "ocular-code-pilot"
DEFAULT_THRESHOLDS = DEFAULT_OUTPUT_ROOT / "development" / "thresholds.json"
IMPLEMENTATION_PATHS = (
    "scripts/run_ocular_code_benchmark.py",
    "src/benchmark.py",
    "src/code_design.py",
    "src/ocular_codes.py",
    "src/sleep_edf.py",
)
CONFIG_PATHS = (
    "config/benchmark.json",
    "config/codebook.json",
    "config/sleep_edf_pilot_manifest.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "test"), required=True)
    parser.add_argument("--benchmark-config", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--codebook", type=Path, default=DEFAULT_CODEBOOK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def load_manifest(path: Path, split: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["split"] == split]
    if not rows:
        raise ValueError(f"manifest contains no rows for split={split}")
    subjects = [row["subject_id"] for row in rows]
    if len(subjects) != len(set(subjects)):
        raise ValueError(f"split={split} contains repeated participants")
    return rows


def implementation_hashes() -> dict[str, str]:
    return {path: file_sha256(REPOSITORY_ROOT / path) for path in IMPLEMENTATION_PATHS}


def verify_input_files(rows: Iterable[dict[str, str]], data_root: Path) -> None:
    problems: list[str] = []
    for row in rows:
        for role in ("psg", "hypnogram"):
            path = data_root / row[f"{role}_file"]
            if not path.is_file():
                problems.append(f"missing {path}")
                continue
            observed = file_sha256(path)
            expected = row[f"{role}_sha256"].lower()
            if observed != expected:
                problems.append(
                    f"SHA256 mismatch for {path.name}: expected {expected}, observed {observed}"
                )
    if problems:
        raise RuntimeError("\n".join(problems))


def require_empty_output(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(
            f"refusing to overwrite nonempty split output: {output_dir}. "
            "Move it aside explicitly before a new run."
        )


def require_test_seal(thresholds_path: Path) -> dict:
    if not thresholds_path.is_file():
        raise RuntimeError(f"sealed test requires development thresholds: {thresholds_path}")
    commit, clean = _git_state()
    if not clean:
        raise RuntimeError("sealed test requires a clean Git worktree")
    relative = thresholds_path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    if tracked.returncode:
        raise RuntimeError("sealed test requires thresholds committed to Git")
    thresholds = load_json(thresholds_path)
    expected_impl = thresholds.get("implementation_sha256")
    observed_impl = implementation_hashes()
    if expected_impl != observed_impl:
        raise RuntimeError("implementation differs from the development-threshold run")
    expected_configs = thresholds.get("config_sha256")
    observed_configs = {
        path: file_sha256(REPOSITORY_ROOT / path) for path in CONFIG_PATHS
    }
    if expected_configs != observed_configs:
        raise RuntimeError("configuration differs from the development-threshold run")
    thresholds["test_git_commit"] = commit
    return thresholds


def _git_state() -> tuple[str, bool]:
    metadata = frozen_run_metadata(REPOSITORY_ROOT, CONFIG_PATHS)
    return str(metadata["git_commit"]), bool(metadata["git_worktree_clean"])


def condition_seed(base_seed: int, *labels: object) -> int:
    text = "|".join([str(base_seed), *(str(label) for label in labels)])
    return int.from_bytes(sha256(text.encode("utf-8")).digest()[:8], "little")


def filtered_template_bank(
    code: OcularCode,
    waveform: WaveformSpec,
    time_scales: list[float],
    sos: np.ndarray,
) -> tuple[OcularTemplate, ...]:
    """Filter canonical templates inside long zero context and crop them back."""

    output: list[OcularTemplate] = []
    padding = int(round(30 * waveform.sample_rate_hz))
    for template in build_template_bank(code, waveform, time_scales):
        embedded = np.pad(template.values, (padding, padding))
        filtered = zero_phase_filter(embedded, sos)[padding:-padding]
        output.append(replace(template, values=filtered))
    return tuple(output)


def longest_injection_samples(
    codes: list[OcularCode], waveform: WaveformSpec, synthetic: dict
) -> int:
    maximum_jitter = max(float(value) for value in synthetic["interval_jitter_fraction"])
    maximum_transition = float(synthetic["transition_seconds_range"][1])
    maximum_seconds = 0.0
    for code in codes:
        dwell = sum(waveform.duration_seconds(symbol) for symbol in code.rhythm)
        transitions = sum(symbol != "P" for symbol in code.rhythm) + 1
        transitions += 2 * code.rhythm.count("P")
        duration = (
            waveform.pre_baseline_seconds
            + waveform.post_baseline_seconds
            + dwell * (1 + maximum_jitter)
            + transitions * maximum_transition
        )
        maximum_seconds = max(maximum_seconds, duration)
    return int(np.ceil(maximum_seconds * waveform.sample_rate_hz)) + 2


def trailing_scale(
    filtered_eog: np.ndarray,
    invalid: np.ndarray,
    sample: int,
    sfreq: float,
    window_seconds: float,
    minimum_seconds: float,
) -> float:
    """Robust causal scale from samples strictly preceding a candidate."""

    stop = min(len(filtered_eog), int(sample))
    start = max(0, stop - int(round(window_seconds * sfreq)))
    valid = ~invalid[start:stop]
    if int(valid.sum()) < int(round(minimum_seconds * sfreq)):
        raise ValueError("insufficient valid trailing calibration exposure")
    return robust_mad(filtered_eog[start:stop][valid])


def detect_with_trailing_amplitude_gate(
    *,
    signal: np.ndarray,
    templates: tuple[OcularTemplate, ...],
    eligible_mask: np.ndarray,
    invalid_mask: np.ndarray,
    detector: dict,
    preprocessing: dict,
    sfreq: float,
) -> tuple[Detection, ...]:
    """Apply the amplitude gate using a causal, stepwise trailing MAD."""

    raw_candidates = detect_code(
        signal,
        templates,
        calibration_mad=1.0,
        score_threshold=float(detector["minimum_candidate_score"]),
        minimum_amplitude_mad=0.0,
        eligible_mask=eligible_mask,
        scan_step_seconds=float(detector["scan_step_seconds"]),
        nms_seconds=0.0,
    )
    update_samples = int(round(float(preprocessing["calibration_update_seconds"]) * sfreq))
    scale_cache: dict[int, float | None] = {}
    qualified: list[Detection] = []
    for candidate in raw_candidates:
        scale_bin = candidate.start_sample // update_samples
        if scale_bin not in scale_cache:
            calibration_stop = scale_bin * update_samples
            try:
                scale_cache[scale_bin] = trailing_scale(
                    signal,
                    invalid_mask,
                    calibration_stop,
                    sfreq,
                    float(preprocessing["calibration_seconds"]),
                    float(preprocessing["minimum_calibration_seconds"]),
                )
            except ValueError:
                scale_cache[scale_bin] = None
        scale = scale_cache[scale_bin]
        if scale is None:
            continue
        amplitude_mad = abs(candidate.fitted_amplitude) / scale
        if amplitude_mad >= float(detector["minimum_regression_amplitude_mad"]):
            qualified.append(replace(candidate, amplitude_mad=amplitude_mad))
    return non_maximum_suppression(
        qualified, nms_samples=float(detector["nms_seconds"]) * sfreq
    )


def detection_rows(
    detections: Iterable[Detection], subject_id: str, scope: str, sfreq: float
) -> list[dict]:
    return [
        {
            "subject_id": subject_id,
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


def matched_injection_score(
    filtered_signal: np.ndarray,
    eligible_mask: np.ndarray,
    anchor: int,
    maximum_signal_samples: int,
    templates: tuple[OcularTemplate, ...],
    local_calibration_mad: float,
    detector: dict,
    sfreq: float,
) -> tuple[float, float | None, float | None]:
    context = int(round(1.5 * sfreq))
    start = max(0, anchor - context)
    stop = min(len(filtered_signal), anchor + maximum_signal_samples + context)
    segment = filtered_signal[start:stop]
    segment_mask = eligible_mask[start:stop]
    detections = detect_code(
        segment,
        templates,
        calibration_mad=local_calibration_mad,
        score_threshold=float(detector["minimum_candidate_score"]),
        minimum_amplitude_mad=float(detector["minimum_regression_amplitude_mad"]),
        eligible_mask=segment_mask,
        scan_step_seconds=float(detector["scan_step_seconds"]),
        nms_seconds=float(detector["nms_seconds"]),
    )
    tolerance = float(detector["match_tolerance_seconds"]) * sfreq
    matches = [
        item for item in detections if abs((item.start_sample + start) - anchor) <= tolerance
    ]
    if not matches:
        return 0.0, None, None
    best = max(matches, key=lambda item: item.score)
    return best.score, (best.start_sample + start) / sfreq, best.time_scale


def run_synthetic_conditions(
    *,
    raw_eog: np.ndarray,
    filtered_eog: np.ndarray,
    invalid_mask: np.ndarray,
    eligible_rem_mask: np.ndarray,
    subject_id: str,
    codes: list[OcularCode],
    templates: dict[str, tuple[OcularTemplate, ...]],
    waveform: WaveformSpec,
    benchmark: dict,
    sos: np.ndarray,
    maximum_signal_samples: int,
) -> list[dict]:
    synthetic = benchmark["synthetic_injection"]
    detector = benchmark["detector"]
    sfreq = waveform.sample_rate_hz
    anchors = choose_shared_anchors(
        eligible_rem_mask,
        maximum_signal_samples,
        int(round(float(synthetic["minimum_anchor_separation_seconds"]) * sfreq)),
        int(synthetic["anchors_per_recording"]),
        np.random.default_rng(condition_seed(int(benchmark["random_seed"]), subject_id, "anchors")),
        candidate_stride_samples=int(round(sfreq)),
    )
    if not len(anchors):
        raise RuntimeError(f"no eligible injection anchors for subject {subject_id}")

    rows: list[dict] = []
    for code in codes:
        for jitter in synthetic["interval_jitter_fraction"]:
            perturbation = PerturbationSpec.from_mapping(
                synthetic, interval_jitter_fraction=float(jitter)
            )
            for amplitude_mad in synthetic["amplitude_mad"]:
                rng = np.random.default_rng(
                    condition_seed(
                        int(benchmark["random_seed"]),
                        subject_id,
                        code.code_id,
                        amplitude_mad,
                        jitter,
                    )
                )
                injected = raw_eog.copy()
                truths: list[tuple[int, float, int, int]] = []
                for anchor_index, anchor in enumerate(anchors):
                    scale = trailing_scale(
                        filtered_eog,
                        invalid_mask,
                        int(anchor),
                        sfreq,
                        float(benchmark["preprocessing"]["calibration_seconds"]),
                        float(benchmark["preprocessing"]["minimum_calibration_seconds"]),
                    )
                    signal = synthesize_perturbed_code(
                        code,
                        waveform,
                        amplitude=float(amplitude_mad) * scale,
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
                            "subject_id": subject_id,
                            "code_id": code.code_id,
                            "anchor_index": anchor_index,
                            "anchor_seconds": anchor / sfreq,
                            "amplitude_mad": float(amplitude_mad),
                            "interval_jitter_fraction": float(jitter),
                            "local_mad_uv": scale,
                            "injection_samples": signal_samples,
                            "maximum_matched_score": score,
                            "detected_start_seconds": detected_start,
                            "detected_time_scale": detected_scale,
                            "engineering_check_only": True,
                        }
                    )
    return rows


def threshold_map_from_development(
    synthetic_frame: pd.DataFrame, benchmark: dict, code_ids: list[str]
) -> dict[str, dict]:
    synthetic = benchmark["synthetic_injection"]
    selection = benchmark["threshold_selection"]
    grid = prespecified_threshold_grid(
        float(selection["score_grid_start"]),
        float(selection["score_grid_stop"]),
        float(selection["score_grid_step"]),
    )
    output: dict[str, dict] = {}
    primary = synthetic_frame[
        (synthetic_frame["amplitude_mad"] == float(synthetic["primary_amplitude_mad"]))
        & (
            synthetic_frame["interval_jitter_fraction"]
            == float(synthetic["primary_interval_jitter_fraction"])
        )
    ]
    for code_id in code_ids:
        scores = primary.loc[primary["code_id"] == code_id, "maximum_matched_score"].to_numpy()
        selected = select_synthetic_threshold(
            scores, grid, float(selection["target_development_sensitivity"])
        )
        output[code_id] = asdict(selected)
    return output


def threshold_value_map(threshold_document: dict) -> dict[str, float]:
    result: dict[str, float] = {}
    for code_id, value in threshold_document["codes"].items():
        if value["calibrated"]:
            result[code_id] = float(value["threshold"])
    if not result:
        raise RuntimeError("no code passed synthetic engineering calibration")
    return result


def bootstrap_primary_rate_difference(
    background_by_recording: pd.DataFrame,
    candidate: str,
    control: str,
    replicates: int,
    seed: int,
) -> dict:
    rem = background_by_recording[background_by_recording["scope"] == "rem"]
    pivot = rem.pivot(index="subject_id", columns="code_id", values="events")
    exposure = rem.groupby("subject_id", sort=True)["exposure_hours"].first()
    subjects = sorted(set(pivot.index) & set(exposure.index))
    if candidate not in pivot or control not in pivot or not subjects:
        return {"available": False}
    candidate_counts = pivot.loc[subjects, candidate].to_numpy(dtype=float)
    control_counts = pivot.loc[subjects, control].to_numpy(dtype=float)
    hours = exposure.loc[subjects].to_numpy(dtype=float)
    observed = candidate_counts.sum() / hours.sum() - control_counts.sum() / hours.sum()
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=float)
    for index in range(replicates):
        selected = rng.integers(0, len(subjects), len(subjects))
        selected_hours = hours[selected].sum()
        draws[index] = (
            candidate_counts[selected].sum() / selected_hours
            - control_counts[selected].sum() / selected_hours
        )
    return {
        "available": True,
        "candidate": candidate,
        "control": control,
        "rate_difference_per_rem_hour": observed,
        "cluster_bootstrap_lower": float(np.quantile(draws, 0.025)),
        "cluster_bootstrap_upper": float(np.quantile(draws, 0.975)),
        "bootstrap_replicates": replicates,
        "cluster_unit": "subject",
    }


def summarize_outputs(
    *,
    split: str,
    exposure_frame: pd.DataFrame,
    synthetic_frame: pd.DataFrame,
    background_events: pd.DataFrame,
    background_by_recording: pd.DataFrame,
    thresholds: dict[str, float],
    benchmark: dict,
    codebook: dict,
) -> tuple[pd.DataFrame, dict]:
    synthetic_rows: list[dict] = []
    for (code_id, amplitude, jitter), group in synthetic_frame.groupby(
        ["code_id", "amplitude_mad", "interval_jitter_fraction"], sort=True
    ):
        if code_id not in thresholds:
            continue
        successes = int((group["maximum_matched_score"] >= thresholds[code_id]).sum())
        interval = clopper_pearson(successes, len(group))
        synthetic_rows.append(
            {
                "code_id": code_id,
                "amplitude_mad": amplitude,
                "interval_jitter_fraction": jitter,
                "threshold": thresholds[code_id],
                "synthetic_recoveries": successes,
                "synthetic_injections": len(group),
                "synthetic_recovery_fraction": interval.estimate,
                "exact_lower": interval.lower,
                "exact_upper": interval.upper,
                "engineering_check_only": True,
            }
        )
    synthetic_summary = pd.DataFrame(synthetic_rows)

    rate_rows: list[dict] = []
    for (scope, code_id), group in background_by_recording.groupby(["scope", "code_id"]):
        events = int(group["events"].sum())
        hours = float(group["exposure_hours"].sum())
        interval = exact_poisson_rate(events, hours)
        row = asdict(interval)
        row.update(
            {
                "scope": scope,
                "code_id": code_id,
                "query_window_seconds": 10.0,
                "probability_false_event_in_10_seconds": query_window_false_probability(
                    interval.rate_per_hour, 10.0
                ),
            }
        )
        rate_rows.append(row)

    primary = codebook["prespecified_primary_contrast"]
    contrast = bootstrap_primary_rate_difference(
        background_by_recording,
        str(primary["candidate"]),
        str(primary["control"]),
        int(benchmark["inference"]["bootstrap_replicates"]),
        int(benchmark["random_seed"]),
    )
    summary = {
        "split": split,
        "interpretation": "background collision benchmark with synthetic engineering calibration",
        "human_signal_sensitivity_estimated": False,
        "recordings": int(exposure_frame["subject_id"].nunique()),
        "eligible_rem_hours": float(exposure_frame["eligible_rem_hours"].sum()),
        "full_recording_hours": float(exposure_frame["recording_hours"].sum()),
        "calibrated_codes": sorted(thresholds),
        "background_rates": rate_rows,
        "primary_contrast": contrast,
        "background_event_rows": len(background_events),
    }
    return synthetic_summary, summary


def main() -> None:
    args = parse_args()
    benchmark = load_json(args.benchmark_config.resolve())
    codebook = load_json(args.codebook.resolve())
    rows = load_manifest(args.manifest.resolve(), args.split)
    output_dir = args.output_root.resolve() / args.split
    require_empty_output(output_dir)
    run_metadata = frozen_run_metadata(REPOSITORY_ROOT, CONFIG_PATHS)

    if args.split == "test":
        threshold_document = require_test_seal(args.thresholds.resolve())
        threshold_values = threshold_value_map(threshold_document)
    else:
        commit, clean = _git_state()
        if not clean:
            raise RuntimeError("development run requires a clean Git worktree")
        threshold_document = {"development_git_commit": commit}
        threshold_values = {}

    print(f"Verifying {2 * len(rows)} frozen {args.split} files by SHA256...")
    verify_input_files(rows, args.data_root.resolve())
    print("Input verification complete.")

    waveform = WaveformSpec.from_mapping(codebook["waveform"])
    all_codes = [OcularCode.from_mapping(value) for value in codebook["codes"]]
    if args.split == "test":
        codes = [code for code in all_codes if code.code_id in threshold_values]
    else:
        codes = all_codes
    preprocessing = benchmark["preprocessing"]
    detector = benchmark["detector"]
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
    maximum_signal_samples = longest_injection_samples(codes, waveform, benchmark["synthetic_injection"])

    exposure_rows: list[dict] = []
    synthetic_rows: list[dict] = []
    rem_candidates: dict[tuple[str, str], tuple[Detection, ...]] = {}
    night_candidates: dict[tuple[str, str], tuple[Detection, ...]] = {}
    for record_index, row in enumerate(rows, start=1):
        subject_id = row["subject_id"]
        print(f"[{record_index}/{len(rows)}] subject {subject_id}: loading and filtering")
        recording = load_sleep_edf(
            args.data_root.resolve() / row["psg_file"],
            args.data_root.resolve() / row["hypnogram_file"],
            channel=benchmark["data"]["channel"],
            required_sample_rate_hz=float(benchmark["data"]["required_sample_rate_hz"]),
            rem_description=benchmark["data"]["rem_annotation"],
            boundary_margin_seconds=float(benchmark["data"]["rem_boundary_margin_seconds"]),
        )
        filtered = zero_phase_filter(recording.eog_uv, sos)
        first_stop = min(
            len(filtered),
            int(round(float(preprocessing["calibration_seconds"]) * recording.sample_rate_hz)),
        )
        initial_scale = robust_mad(filtered[:first_stop][~recording.invalid_mask[:first_stop]])
        exposure = recording.exposure.to_dict()
        exposure.update(
            {
                "subject_id": subject_id,
                "psg_file": row["psg_file"],
                "recording_hours": recording.exposure.recording_seconds / 3600.0,
                "initial_recording_mad_uv": initial_scale,
            }
        )
        exposure_rows.append(exposure)

        print(f"[{record_index}/{len(rows)}] subject {subject_id}: continuous background scan")
        for code in codes:
            common = dict(
                signal=filtered,
                templates=templates[code.code_id],
                invalid_mask=recording.invalid_mask,
                detector=detector,
                preprocessing=preprocessing,
                sfreq=recording.sample_rate_hz,
            )
            rem_candidates[(subject_id, code.code_id)] = detect_with_trailing_amplitude_gate(
                eligible_mask=recording.eligible_rem_mask, **common
            )
            night_candidates[(subject_id, code.code_id)] = detect_with_trailing_amplitude_gate(
                eligible_mask=~recording.invalid_mask, **common
            )

        print(f"[{record_index}/{len(rows)}] subject {subject_id}: synthetic engineering surface")
        synthetic_rows.extend(
            run_synthetic_conditions(
                raw_eog=recording.eog_uv,
                filtered_eog=filtered,
                invalid_mask=recording.invalid_mask,
                eligible_rem_mask=recording.eligible_rem_mask,
                subject_id=subject_id,
                codes=codes,
                templates=templates,
                waveform=waveform,
                benchmark=benchmark,
                sos=sos,
                maximum_signal_samples=maximum_signal_samples,
            )
        )

    exposure_frame = pd.DataFrame(exposure_rows)
    synthetic_frame = pd.DataFrame(synthetic_rows)
    if args.split == "development":
        code_thresholds = threshold_map_from_development(
            synthetic_frame, benchmark, [code.code_id for code in codes]
        )
        threshold_document = {
            "schema_version": 1,
            "interpretation": "thresholds selected from synthetic engineering recoverability, not human sensitivity",
            "development_git_commit": threshold_document["development_git_commit"],
            "config_sha256": {
                path: file_sha256(REPOSITORY_ROOT / path) for path in CONFIG_PATHS
            },
            "implementation_sha256": implementation_hashes(),
            "codes": code_thresholds,
        }
        threshold_values = threshold_value_map(threshold_document)

    background_event_rows: list[dict] = []
    background_record_rows: list[dict] = []
    exposure_by_subject = exposure_frame.set_index("subject_id")
    for code in codes:
        if code.code_id not in threshold_values:
            continue
        threshold = threshold_values[code.code_id]
        for row in rows:
            subject_id = row["subject_id"]
            for scope, candidate_map, exposure_hours in (
                (
                    "rem",
                    rem_candidates,
                    float(exposure_by_subject.loc[subject_id, "eligible_rem_hours"]),
                ),
                (
                    "full_night_ungated",
                    night_candidates,
                    float(exposure_by_subject.loc[subject_id, "recording_hours"]),
                ),
            ):
                selected = tuple(
                    item
                    for item in candidate_map[(subject_id, code.code_id)]
                    if item.score >= threshold
                )
                background_event_rows.extend(
                    detection_rows(selected, subject_id, scope, waveform.sample_rate_hz)
                )
                background_record_rows.append(
                    {
                        "subject_id": subject_id,
                        "scope": scope,
                        "code_id": code.code_id,
                        "threshold": threshold,
                        "events": len(selected),
                        "exposure_hours": exposure_hours,
                        "events_per_hour": len(selected) / exposure_hours,
                    }
                )

    background_events = pd.DataFrame(
        background_event_rows,
        columns=[
            "subject_id",
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
        ],
    )
    background_by_recording = pd.DataFrame(background_record_rows)
    synthetic_summary, summary = summarize_outputs(
        split=args.split,
        exposure_frame=exposure_frame,
        synthetic_frame=synthetic_frame,
        background_events=background_events,
        background_by_recording=background_by_recording,
        thresholds=threshold_values,
        benchmark=benchmark,
        codebook=codebook,
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    exposure_frame.to_csv(output_dir / "exposure.csv", index=False)
    synthetic_frame.to_csv(output_dir / "synthetic_recovery.csv", index=False)
    synthetic_summary.to_csv(output_dir / "synthetic_summary.csv", index=False)
    background_events.to_csv(output_dir / "background_events.csv", index=False)
    background_by_recording.to_csv(output_dir / "background_by_recording.csv", index=False)
    provenance = run_metadata
    provenance.update(
        {
            "split": args.split,
            "implementation_sha256": implementation_hashes(),
            "thresholds_path": args.thresholds.resolve().as_posix(),
            "thresholds_sha256": (
                file_sha256(args.thresholds.resolve())
                if args.split == "test"
                else None
            ),
        }
    )
    write_json(output_dir / "provenance.json", provenance)
    write_json(output_dir / "summary.json", summary)
    if args.split == "development":
        write_json(output_dir / "thresholds.json", threshold_document)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {output_dir}")


if __name__ == "__main__":
    main()
