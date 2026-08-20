"""Matched-recovery FROC analysis for ocular-code result tables.

This module never reads physiological recordings.  It operates on the result
tables written by ``run_ocular_code_benchmark.py`` and treats synthetic
recovery strictly as an engineering outcome, not human sensitivity.

Existing background event tables are left-censored at each code's frozen
operating threshold.  A derived FROC point is therefore valid only when its
threshold is at or above that storage floor.  The coverage check is explicit
and fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from src.benchmark import clopper_pearson, exact_poisson_rate


SYNTHETIC_COLUMNS = frozenset(
    {
        "subject_id",
        "code_id",
        "anchor_index",
        "anchor_seconds",
        "amplitude_mad",
        "interval_jitter_fraction",
        "maximum_matched_score",
        "engineering_check_only",
    }
)
BACKGROUND_EVENT_COLUMNS = frozenset({"subject_id", "scope", "code_id", "score"})
BACKGROUND_RECORD_COLUMNS = frozenset(
    {
        "subject_id",
        "scope",
        "code_id",
        "threshold",
        "events",
        "exposure_hours",
    }
)


class BackgroundCoverageError(ValueError):
    """Raised when stored events do not cover a requested lower threshold."""


class UnattainableRecoveryError(ValueError):
    """Raised when score ties prevent an exact requested recovery count."""


@dataclass(frozen=True)
class ResultTables:
    """The three result tables needed for an offline FROC analysis."""

    label: str
    directory: Path
    synthetic: pd.DataFrame
    background_events: pd.DataFrame
    background_by_recording: pd.DataFrame


@dataclass(frozen=True)
class RecoveryThreshold:
    """Largest inclusive score threshold yielding an exact recovery count."""

    requested_fraction: float
    recoveries: int
    trials: int
    achieved_fraction: float
    threshold: float


@dataclass(frozen=True)
class BootstrapRateDifference:
    """Participant-clustered interval for a paired rate difference."""

    estimate: float
    lower: float
    upper: float
    replicates: int
    participants: int


@dataclass(frozen=True)
class MatchedFrocBootstrap:
    """Interval that reselects both matched thresholds in every replicate."""

    estimate: float
    lower: float
    upper: float
    candidate_threshold: float
    control_threshold: float
    candidate_rate: float
    control_rate: float
    candidate_events: int
    control_events: int
    candidate_recovery: float
    control_recovery: float
    replicates: int
    participants: int


def load_result_tables(
    directory: str | Path, *, label: str | None = None
) -> ResultTables:
    """Read only result CSVs from a completed benchmark split directory."""

    root = Path(directory).resolve()
    paths = {
        "synthetic": root / "synthetic_recovery.csv",
        "background_events": root / "background_events.csv",
        "background_by_recording": root / "background_by_recording.csv",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing FROC input tables: " + ", ".join(missing))

    synthetic = _read_csv(paths["synthetic"], SYNTHETIC_COLUMNS)
    events = _read_csv(paths["background_events"], BACKGROUND_EVENT_COLUMNS)
    by_recording = _read_csv(
        paths["background_by_recording"], BACKGROUND_RECORD_COLUMNS
    )
    for frame in (synthetic, events, by_recording):
        frame["subject_id"] = frame["subject_id"].astype(str)
        frame["code_id"] = frame["code_id"].astype(str)
    events["scope"] = events["scope"].astype(str)
    by_recording["scope"] = by_recording["scope"].astype(str)

    _validate_numeric(synthetic, ["maximum_matched_score", "amplitude_mad"])
    _validate_numeric(synthetic, ["interval_jitter_fraction", "anchor_seconds"])
    _validate_numeric(events, ["score"])
    _validate_numeric(by_recording, ["threshold", "events", "exposure_hours"])
    scores = synthetic["maximum_matched_score"].to_numpy(dtype=float)
    if np.any((scores < 0) | (scores > 1)):
        raise ValueError("synthetic matched scores must lie in [0, 1]")
    event_scores = events["score"].to_numpy(dtype=float)
    if np.any((event_scores < 0) | (event_scores > 1)):
        raise ValueError("background event scores must lie in [0, 1]")
    exposure_values = by_recording["exposure_hours"].to_numpy(dtype=float)
    if np.any(exposure_values < 0):
        raise ValueError("background exposures must be nonnegative")
    if np.any(by_recording["events"].to_numpy(dtype=float) < 0):
        raise ValueError("background event counts cannot be negative")
    if bool(
        (
            (by_recording["exposure_hours"].to_numpy(dtype=float) == 0)
            & (by_recording["events"].to_numpy(dtype=float) != 0)
        ).any()
    ):
        raise ValueError("zero background exposure cannot contain events")

    engineering = synthetic["engineering_check_only"]
    engineering_true = engineering.astype(str).str.lower().isin({"true", "1"})
    if not bool(engineering_true.all()):
        raise ValueError("synthetic rows must be marked engineering_check_only")

    return ResultTables(
        label=label or root.name,
        directory=root,
        synthetic=synthetic,
        background_events=events,
        background_by_recording=by_recording,
    )


def select_synthetic_condition(
    synthetic: pd.DataFrame,
    code_ids: Sequence[str],
    *,
    amplitude_mad: float,
    interval_jitter_fraction: float,
) -> pd.DataFrame:
    """Select and validate one paired synthetic engineering condition."""

    if len(code_ids) != 2 or code_ids[0] == code_ids[1]:
        raise ValueError("exactly two distinct code_ids are required")
    amplitude = synthetic["amplitude_mad"].to_numpy(dtype=float)
    jitter = synthetic["interval_jitter_fraction"].to_numpy(dtype=float)
    selected = synthetic[
        synthetic["code_id"].isin(code_ids)
        & np.isclose(amplitude, amplitude_mad, rtol=0.0, atol=1e-12)
        & np.isclose(jitter, interval_jitter_fraction, rtol=0.0, atol=1e-12)
    ].copy()
    if selected.empty:
        raise ValueError("no rows match the requested synthetic condition")

    key_columns = ["subject_id"]
    if "record_id" in selected.columns:
        key_columns.append("record_id")
    key_columns.extend(["anchor_index", "anchor_seconds"])
    keys_by_code: dict[str, pd.MultiIndex] = {}
    for code_id in code_ids:
        group = selected[selected["code_id"] == code_id]
        if group.empty:
            raise ValueError(f"synthetic condition has no rows for {code_id}")
        if group.duplicated(key_columns).any():
            raise ValueError(f"synthetic condition has duplicate anchors for {code_id}")
        keys_by_code[code_id] = pd.MultiIndex.from_frame(group[key_columns])
    left, right = (set(keys_by_code[code_id].tolist()) for code_id in code_ids)
    if left != right:
        raise ValueError("the two codes do not share identical synthetic anchors")
    return selected


def select_exact_recovery_threshold(
    scores: Sequence[float], requested_fraction: float
) -> RecoveryThreshold:
    """Select the largest inclusive threshold giving an exact recovery count.

    The requested fraction is converted to the nearest integer count.  If a
    score tie straddles that rank, exact matching is impossible and the function
    raises rather than silently comparing unequal recoveries.
    """

    values = np.asarray(scores, dtype=float)
    if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)):
        raise ValueError("scores must be a nonempty finite vector")
    if np.any((values < 0) | (values > 1)):
        raise ValueError("scores must lie in [0, 1]")
    if not np.isfinite(requested_fraction) or not 0 < requested_fraction <= 1:
        raise ValueError("requested_fraction must lie in (0, 1]")

    trials = int(values.size)
    recoveries = int(np.floor(requested_fraction * trials + 0.5))
    if recoveries < 1:
        raise ValueError(
            "requested recovery is smaller than one trial at this sample size"
        )
    recoveries = min(recoveries, trials)
    ordered = np.sort(values)[::-1]
    threshold = float(ordered[recoveries - 1])
    achieved = int(np.count_nonzero(values >= threshold))
    if achieved != recoveries:
        raise UnattainableRecoveryError(
            f"score ties yield {achieved} recoveries, not requested count {recoveries}"
        )
    return RecoveryThreshold(
        requested_fraction=float(requested_fraction),
        recoveries=recoveries,
        trials=trials,
        achieved_fraction=recoveries / trials,
        threshold=threshold,
    )


def select_at_least_recovery_threshold(
    scores: Sequence[float], requested_fraction: float
) -> RecoveryThreshold:
    """Select the largest threshold recovering at least the target fraction.

    The minimum recovery count is the ceiling of the requested fraction times
    the trial count. Ties at the boundary are retained and may therefore yield
    a slightly higher achieved fraction. This behavior is deterministic and
    is reported rather than broken using background information.
    """

    values = np.asarray(scores, dtype=float)
    if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)):
        raise ValueError("scores must be a nonempty finite vector")
    if np.any((values < 0) | (values > 1)):
        raise ValueError("scores must lie in [0, 1]")
    if not np.isfinite(requested_fraction) or not 0 < requested_fraction <= 1:
        raise ValueError("requested_fraction must lie in (0, 1]")
    trials = int(values.size)
    minimum = max(1, int(np.ceil(requested_fraction * trials - 1e-12)))
    ordered = np.sort(values)[::-1]
    threshold = float(ordered[minimum - 1])
    recoveries = int(np.count_nonzero(values >= threshold))
    return RecoveryThreshold(
        requested_fraction=float(requested_fraction),
        recoveries=recoveries,
        trials=trials,
        achieved_fraction=recoveries / trials,
        threshold=threshold,
    )


def background_storage_floor(
    tables: ResultTables, code_id: str, *, scope: str
) -> float:
    """Return the lowest score for which the stored event table is complete."""

    rows = tables.background_by_recording[
        (tables.background_by_recording["code_id"] == code_id)
        & (tables.background_by_recording["scope"] == scope)
    ]
    if rows.empty:
        raise ValueError(f"no background rows for code={code_id}, scope={scope}")
    floors = rows["threshold"].to_numpy(dtype=float)
    if not np.allclose(floors, floors[0], rtol=0.0, atol=1e-12):
        raise ValueError(f"inconsistent background storage floors for {code_id}")
    floor = float(floors[0])
    stored = tables.background_events[
        (tables.background_events["code_id"] == code_id)
        & (tables.background_events["scope"] == scope)
    ]
    if not stored.empty and bool((stored["score"] < floor - 1e-12).any()):
        raise ValueError(f"stored background event below declared floor for {code_id}")
    return floor


def build_matched_thresholds(
    calibration: ResultTables,
    *,
    candidate: str,
    control: str,
    amplitude_mad: float,
    interval_jitter_fraction: float,
    recovery_levels: Iterable[float],
    scope: str = "rem",
) -> pd.DataFrame:
    """Choose code-specific thresholds with exactly matched calibration recovery."""

    code_ids = (candidate, control)
    selected = select_synthetic_condition(
        calibration.synthetic,
        code_ids,
        amplitude_mad=amplitude_mad,
        interval_jitter_fraction=interval_jitter_fraction,
    )
    levels = np.asarray(tuple(recovery_levels), dtype=float)
    if levels.ndim != 1 or levels.size == 0 or np.any(~np.isfinite(levels)):
        raise ValueError("recovery_levels must be a nonempty finite vector")
    if np.any(np.diff(levels) <= 0):
        raise ValueError("recovery_levels must be strictly increasing")
    if np.any((levels <= 0) | (levels > 1)):
        raise ValueError("recovery_levels must lie in (0, 1]")

    scores = {
        code_id: selected.loc[
            selected["code_id"] == code_id, "maximum_matched_score"
        ].to_numpy(dtype=float)
        for code_id in code_ids
    }
    if len(scores[candidate]) != len(scores[control]):
        raise ValueError("matched threshold selection requires equal trial counts")
    floors = {
        code_id: background_storage_floor(calibration, code_id, scope=scope)
        for code_id in code_ids
    }

    rows: list[dict[str, object]] = []
    for requested in levels:
        chosen = {
            code_id: select_at_least_recovery_threshold(
                scores[code_id], float(requested)
            )
            for code_id in code_ids
        }
        candidate_point = chosen[candidate]
        control_point = chosen[control]
        for code_id in code_ids:
            if chosen[code_id].threshold < floors[code_id] - 1e-12:
                raise BackgroundCoverageError(
                    f"{code_id} threshold {chosen[code_id].threshold:.12g} at "
                    f"requested recovery {requested:.6g} is below stored-event "
                    f"floor {floors[code_id]:.12g}"
                )
        rows.append(
            {
                "requested_recovery_fraction": float(requested),
                "matched_recoveries": min(
                    candidate_point.recoveries, control_point.recoveries
                ),
                "matched_trials": candidate_point.trials,
                "matched_recovery_fraction": min(
                    candidate_point.achieved_fraction,
                    control_point.achieved_fraction,
                ),
                "candidate_code_id": candidate,
                "candidate_threshold": candidate_point.threshold,
                "candidate_calibration_recoveries": candidate_point.recoveries,
                "candidate_calibration_recovery_fraction": candidate_point.achieved_fraction,
                "candidate_storage_floor": floors[candidate],
                "control_code_id": control,
                "control_threshold": control_point.threshold,
                "control_calibration_recoveries": control_point.recoveries,
                "control_calibration_recovery_fraction": control_point.achieved_fraction,
                "control_storage_floor": floors[control],
                "amplitude_mad": float(amplitude_mad),
                "interval_jitter_fraction": float(interval_jitter_fraction),
                "scope": scope,
            }
        )
    return pd.DataFrame(rows)


def evaluate_matched_thresholds(
    tables: ResultTables,
    matched_thresholds: pd.DataFrame,
    *,
    dataset_role: str,
) -> pd.DataFrame:
    """Evaluate frozen paired thresholds on one result bundle."""

    if matched_thresholds.empty:
        raise ValueError("matched_thresholds cannot be empty")
    first = matched_thresholds.iloc[0]
    candidate = str(first["candidate_code_id"])
    control = str(first["control_code_id"])
    amplitude_mad = float(first["amplitude_mad"])
    jitter = float(first["interval_jitter_fraction"])
    selected = select_synthetic_condition(
        tables.synthetic,
        (candidate, control),
        amplitude_mad=amplitude_mad,
        interval_jitter_fraction=jitter,
    )

    rows: list[dict[str, object]] = []
    for operating_index, operating in matched_thresholds.reset_index(
        drop=True
    ).iterrows():
        scope = str(operating["scope"])
        for code_role, code_id in (("candidate", candidate), ("control", control)):
            threshold = float(operating[f"{code_role}_threshold"])
            floor = background_storage_floor(tables, code_id, scope=scope)
            if threshold < floor - 1e-12:
                raise BackgroundCoverageError(
                    f"evaluation table {tables.label!r} stores {code_id} only at "
                    f"scores >= {floor:.12g}, above requested threshold "
                    f"{threshold:.12g}"
                )
            code_scores = selected.loc[
                selected["code_id"] == code_id, "maximum_matched_score"
            ].to_numpy(dtype=float)
            recoveries = int(np.count_nonzero(code_scores >= threshold))
            synthetic_interval = clopper_pearson(recoveries, len(code_scores))
            background = _subject_background_counts(
                tables, code_id=code_id, scope=scope, threshold=threshold
            )
            events = int(background["events"].sum())
            exposure_hours = float(background["exposure_hours"].sum())
            rate_interval = exact_poisson_rate(events, exposure_hours)
            rows.append(
                {
                    "dataset_role": dataset_role,
                    "dataset_label": tables.label,
                    "operating_point": int(operating_index),
                    "requested_recovery_fraction": float(
                        operating["requested_recovery_fraction"]
                    ),
                    "matched_calibration_recoveries": int(
                        operating["matched_recoveries"]
                    ),
                    "matched_calibration_trials": int(operating["matched_trials"]),
                    "matched_calibration_recovery_fraction": float(
                        operating["matched_recovery_fraction"]
                    ),
                    "code_role": code_role,
                    "code_id": code_id,
                    "threshold": threshold,
                    "background_storage_floor": floor,
                    "synthetic_recoveries": recoveries,
                    "synthetic_trials": len(code_scores),
                    "synthetic_recovery_fraction": synthetic_interval.estimate,
                    "synthetic_exact_lower": synthetic_interval.lower,
                    "synthetic_exact_upper": synthetic_interval.upper,
                    "background_scope": scope,
                    "background_events": events,
                    "exposure_hours": exposure_hours,
                    "false_events_per_hour": rate_interval.rate_per_hour,
                    "poisson_lower_per_hour": rate_interval.lower_per_hour,
                    "poisson_upper_per_hour": rate_interval.upper_per_hour,
                    "engineering_check_only": True,
                }
            )
    return pd.DataFrame(rows)


def paired_cluster_bootstrap_rate_difference(
    candidate_events: Sequence[int],
    control_events: Sequence[int],
    exposure_hours: Sequence[float],
    *,
    replicates: int,
    seed: int,
) -> BootstrapRateDifference:
    """Bootstrap participants for candidate-minus-control event-rate difference."""

    candidate = np.asarray(candidate_events, dtype=float)
    control = np.asarray(control_events, dtype=float)
    hours = np.asarray(exposure_hours, dtype=float)
    if candidate.ndim != 1 or control.ndim != 1 or hours.ndim != 1:
        raise ValueError("event counts and exposure must be vectors")
    if not (len(candidate) == len(control) == len(hours)) or len(hours) == 0:
        raise ValueError("paired vectors must have the same nonzero length")
    if np.any(candidate < 0) or np.any(control < 0) or np.any(hours <= 0):
        raise ValueError("event counts must be nonnegative and exposures positive")
    if replicates <= 0 or int(replicates) != replicates:
        raise ValueError("replicates must be a positive integer")

    estimate = float((candidate.sum() - control.sum()) / hours.sum())
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(hours), size=(int(replicates), len(hours)))
    sampled_hours = hours[selected].sum(axis=1)
    draws = (
        candidate[selected].sum(axis=1) - control[selected].sum(axis=1)
    ) / sampled_hours
    return BootstrapRateDifference(
        estimate=estimate,
        lower=float(np.quantile(draws, 0.025)),
        upper=float(np.quantile(draws, 0.975)),
        replicates=int(replicates),
        participants=len(hours),
    )


def build_paired_contrasts(
    tables: ResultTables,
    matched_thresholds: pd.DataFrame,
    points: pd.DataFrame,
    *,
    dataset_role: str,
    bootstrap_replicates: int,
    random_seed: int,
) -> pd.DataFrame:
    """Compare candidate and control rates at each matched operating point."""

    rows: list[dict[str, object]] = []
    for operating_index, operating in matched_thresholds.reset_index(
        drop=True
    ).iterrows():
        scope = str(operating["scope"])
        candidate = str(operating["candidate_code_id"])
        control = str(operating["control_code_id"])
        candidate_counts = _subject_background_counts(
            tables,
            code_id=candidate,
            scope=scope,
            threshold=float(operating["candidate_threshold"]),
        ).rename(columns={"events": "candidate_events"})
        control_counts = _subject_background_counts(
            tables,
            code_id=control,
            scope=scope,
            threshold=float(operating["control_threshold"]),
        ).rename(columns={"events": "control_events"})
        paired = candidate_counts.merge(
            control_counts,
            on="subject_id",
            how="inner",
            suffixes=("_candidate", "_control"),
            validate="one_to_one",
        )
        if len(paired) != len(candidate_counts) or len(paired) != len(control_counts):
            raise ValueError("candidate and control do not have identical participants")
        candidate_hours = paired["exposure_hours_candidate"].to_numpy(dtype=float)
        control_hours = paired["exposure_hours_control"].to_numpy(dtype=float)
        if not np.allclose(candidate_hours, control_hours, rtol=0.0, atol=1e-12):
            raise ValueError(
                "candidate and control exposures differ within participant"
            )
        seed = _labeled_seed(random_seed, tables.label, operating_index)
        interval = paired_cluster_bootstrap_rate_difference(
            paired["candidate_events"].to_numpy(dtype=int),
            paired["control_events"].to_numpy(dtype=int),
            candidate_hours,
            replicates=bootstrap_replicates,
            seed=seed,
        )
        point = points[
            (points["dataset_role"] == dataset_role)
            & (points["operating_point"] == operating_index)
        ]
        candidate_point = point[point["code_role"] == "candidate"].iloc[0]
        control_point = point[point["code_role"] == "control"].iloc[0]
        rows.append(
            {
                "dataset_role": dataset_role,
                "dataset_label": tables.label,
                "operating_point": int(operating_index),
                "requested_recovery_fraction": float(
                    operating["requested_recovery_fraction"]
                ),
                "matched_calibration_recoveries": int(operating["matched_recoveries"]),
                "matched_calibration_trials": int(operating["matched_trials"]),
                "matched_calibration_recovery_fraction": float(
                    operating["matched_recovery_fraction"]
                ),
                "candidate_code_id": candidate,
                "candidate_threshold": float(operating["candidate_threshold"]),
                "candidate_synthetic_recovery_fraction": float(
                    candidate_point["synthetic_recovery_fraction"]
                ),
                "candidate_background_events": int(paired["candidate_events"].sum()),
                "candidate_false_events_per_hour": float(
                    candidate_point["false_events_per_hour"]
                ),
                "control_code_id": control,
                "control_threshold": float(operating["control_threshold"]),
                "control_synthetic_recovery_fraction": float(
                    control_point["synthetic_recovery_fraction"]
                ),
                "control_background_events": int(paired["control_events"].sum()),
                "control_false_events_per_hour": float(
                    control_point["false_events_per_hour"]
                ),
                "candidate_minus_control_rate_per_hour": interval.estimate,
                "cluster_bootstrap_lower": interval.lower,
                "cluster_bootstrap_upper": interval.upper,
                "bootstrap_replicates": interval.replicates,
                "participants": interval.participants,
                "cluster_unit": "subject",
                "engineering_check_only": True,
            }
        )
    return pd.DataFrame(rows)


def bootstrap_matched_froc_rate_difference(
    tables: ResultTables,
    *,
    candidate: str,
    control: str,
    amplitude_mad: float,
    interval_jitter_fraction: float,
    recovery_target: float,
    scope: str = "rem",
    replicates: int,
    seed: int,
) -> MatchedFrocBootstrap:
    """Bootstrap participants and reselect both FROC thresholds each time.

    This is the confirmatory interval. Synthetic scores, candidate events and
    exposure from every selected participant are carried together. Thresholds
    are recomputed from injection scores within each replicate, so calibration
    uncertainty is not treated as fixed.
    """

    if replicates <= 0 or int(replicates) != replicates:
        raise ValueError("replicates must be a positive integer")
    selected = select_synthetic_condition(
        tables.synthetic,
        (candidate, control),
        amplitude_mad=amplitude_mad,
        interval_jitter_fraction=interval_jitter_fraction,
    )
    candidate_floor = background_storage_floor(tables, candidate, scope=scope)
    control_floor = background_storage_floor(tables, control, scope=scope)
    candidate_exposure = _subject_background_counts(
        tables, code_id=candidate, scope=scope, threshold=candidate_floor
    )[["subject_id", "exposure_hours"]]
    control_exposure = _subject_background_counts(
        tables, code_id=control, scope=scope, threshold=control_floor
    )[["subject_id", "exposure_hours"]]
    exposure = candidate_exposure.merge(
        control_exposure,
        on="subject_id",
        how="inner",
        suffixes=("_candidate", "_control"),
        validate="one_to_one",
    )
    if len(exposure) != len(candidate_exposure) or len(exposure) != len(control_exposure):
        raise ValueError("candidate and control do not have identical participants")
    if not np.allclose(
        exposure["exposure_hours_candidate"],
        exposure["exposure_hours_control"],
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("candidate and control exposure differs within participant")

    synthetic_subjects = {
        code_id: set(selected.loc[selected["code_id"] == code_id, "subject_id"])
        for code_id in (candidate, control)
    }
    participants = [
        subject
        for subject in exposure["subject_id"].astype(str)
        if subject in synthetic_subjects[candidate]
        and subject in synthetic_subjects[control]
    ]
    if not participants:
        raise ValueError("no participants have both exposure and paired injections")
    exposure = exposure.set_index("subject_id").loc[participants]
    hours = exposure["exposure_hours_candidate"].to_numpy(dtype=float)
    if np.any(hours <= 0):
        raise ValueError("confirmatory participants must have positive exposure")
    subject_index = {subject: index for index, subject in enumerate(participants)}

    injection_arrays = {
        code_id: _sorted_scores_with_owner(
            selected[selected["code_id"] == code_id],
            score_column="maximum_matched_score",
            subject_index=subject_index,
        )
        for code_id in (candidate, control)
    }
    event_arrays = {
        code_id: _sorted_scores_with_owner(
            tables.background_events[
                (tables.background_events["code_id"] == code_id)
                & (tables.background_events["scope"] == scope)
            ],
            score_column="score",
            subject_index=subject_index,
            allow_empty=True,
        )
        for code_id in (candidate, control)
    }

    unit_weights = np.ones(len(participants), dtype=np.int64)
    observed = _weighted_matched_froc_difference(
        unit_weights,
        hours,
        injection_arrays[candidate],
        injection_arrays[control],
        event_arrays[candidate],
        event_arrays[control],
        recovery_target,
    )
    if observed[0] < candidate_floor - 1e-12:
        raise BackgroundCoverageError("candidate matched threshold is below storage floor")
    if observed[1] < control_floor - 1e-12:
        raise BackgroundCoverageError("control matched threshold is below storage floor")

    rng = np.random.default_rng(seed)
    draws = np.empty(int(replicates), dtype=float)
    for replicate in range(int(replicates)):
        sampled = rng.integers(0, len(participants), len(participants))
        weights = np.bincount(sampled, minlength=len(participants))
        result = _weighted_matched_froc_difference(
            weights,
            hours,
            injection_arrays[candidate],
            injection_arrays[control],
            event_arrays[candidate],
            event_arrays[control],
            recovery_target,
        )
        if result[0] < candidate_floor - 1e-12 or result[1] < control_floor - 1e-12:
            raise BackgroundCoverageError(
                "a bootstrap matched threshold fell below the stored-event floor"
            )
        draws[replicate] = result[8]

    return MatchedFrocBootstrap(
        estimate=observed[8],
        lower=float(np.quantile(draws, 0.025)),
        upper=float(np.quantile(draws, 0.975)),
        candidate_threshold=observed[0],
        control_threshold=observed[1],
        candidate_rate=observed[6],
        control_rate=observed[7],
        candidate_events=int(observed[4]),
        control_events=int(observed[5]),
        candidate_recovery=observed[2],
        control_recovery=observed[3],
        replicates=int(replicates),
        participants=len(participants),
    )


def _sorted_scores_with_owner(
    frame: pd.DataFrame,
    *,
    score_column: str,
    subject_index: dict[str, int],
    allow_empty: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    selected = frame[frame["subject_id"].astype(str).isin(subject_index)].copy()
    if selected.empty:
        if allow_empty:
            return np.array([], dtype=float), np.array([], dtype=np.int64)
        raise ValueError(f"no {score_column} rows for confirmatory participants")
    scores = selected[score_column].to_numpy(dtype=float)
    owners = selected["subject_id"].astype(str).map(subject_index).to_numpy(dtype=np.int64)
    order = np.argsort(-scores, kind="stable")
    return scores[order], owners[order]


def _weighted_threshold(
    scores_descending: np.ndarray,
    owners: np.ndarray,
    participant_weights: np.ndarray,
    recovery_target: float,
) -> tuple[float, float]:
    weights = participant_weights[owners]
    trials = int(weights.sum())
    if trials <= 0:
        raise ValueError("bootstrap replicate contains no synthetic trials")
    minimum = max(1, int(np.ceil(recovery_target * trials - 1e-12)))
    cumulative = np.cumsum(weights)
    boundary = int(np.searchsorted(cumulative, minimum, side="left"))
    threshold = float(scores_descending[boundary])
    stop = int(np.searchsorted(-scores_descending, -threshold, side="right"))
    recoveries = int(weights[:stop].sum())
    return threshold, recoveries / trials


def _weighted_event_count(
    scores_descending: np.ndarray,
    owners: np.ndarray,
    participant_weights: np.ndarray,
    threshold: float,
) -> int:
    if not len(scores_descending):
        return 0
    stop = int(np.searchsorted(-scores_descending, -threshold, side="right"))
    return int(participant_weights[owners[:stop]].sum())


def _weighted_matched_froc_difference(
    participant_weights: np.ndarray,
    exposure_hours: np.ndarray,
    candidate_injections: tuple[np.ndarray, np.ndarray],
    control_injections: tuple[np.ndarray, np.ndarray],
    candidate_events: tuple[np.ndarray, np.ndarray],
    control_events: tuple[np.ndarray, np.ndarray],
    recovery_target: float,
) -> tuple[float, float, float, float, int, int, float, float, float]:
    candidate_threshold, candidate_recovery = _weighted_threshold(
        *candidate_injections, participant_weights, recovery_target
    )
    control_threshold, control_recovery = _weighted_threshold(
        *control_injections, participant_weights, recovery_target
    )
    candidate_count = _weighted_event_count(
        *candidate_events, participant_weights, candidate_threshold
    )
    control_count = _weighted_event_count(
        *control_events, participant_weights, control_threshold
    )
    hours = float(np.dot(participant_weights, exposure_hours))
    if hours <= 0:
        raise ValueError("bootstrap replicate has no positive exposure")
    candidate_rate = candidate_count / hours
    control_rate = control_count / hours
    return (
        candidate_threshold,
        control_threshold,
        candidate_recovery,
        control_recovery,
        candidate_count,
        control_count,
        candidate_rate,
        control_rate,
        candidate_rate - control_rate,
    )


def _subject_background_counts(
    tables: ResultTables, *, code_id: str, scope: str, threshold: float
) -> pd.DataFrame:
    floor = background_storage_floor(tables, code_id, scope=scope)
    if threshold < floor - 1e-12:
        raise BackgroundCoverageError(
            f"threshold {threshold:.12g} is below {code_id} storage floor {floor:.12g}"
        )
    exposure_rows = tables.background_by_recording[
        (tables.background_by_recording["code_id"] == code_id)
        & (tables.background_by_recording["scope"] == scope)
    ][["subject_id", "exposure_hours"]].copy()
    exposure = (
        exposure_rows.groupby("subject_id", as_index=False, sort=True)["exposure_hours"]
        .sum()
    )
    events = tables.background_events[
        (tables.background_events["code_id"] == code_id)
        & (tables.background_events["scope"] == scope)
        & (tables.background_events["score"] >= threshold)
    ]
    counts = events.groupby("subject_id").size().rename("events")
    output = exposure.join(counts, on="subject_id")
    output["events"] = output["events"].fillna(0).astype(int)
    return output.sort_values("subject_id").reset_index(drop=True)


def _read_csv(path: Path, required_columns: frozenset[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = required_columns - set(frame.columns)
    if missing:
        raise ValueError(f"{path} lacks required columns: {sorted(missing)}")
    return frame


def _validate_numeric(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    for column in columns:
        numeric = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        if np.any(~np.isfinite(numeric)):
            raise ValueError(f"column {column!r} contains nonfinite values")
        frame[column] = numeric


def _labeled_seed(base_seed: int, *labels: object) -> int:
    material = "|".join((str(base_seed), *(str(label) for label in labels)))
    return int.from_bytes(sha256(material.encode("utf-8")).digest()[:8], "little")
