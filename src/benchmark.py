"""Statistical and split-control utilities for the ocular-code benchmark.

The functions in this module deliberately keep synthetic recoverability and
background collision rates separate. Synthetic injections are an engineering
check. They are not observations of intentional human signals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import exp, log
from pathlib import Path
import subprocess
from typing import Iterable, Sequence

import numpy as np
from scipy.signal import butter, sosfiltfilt
from scipy.stats import beta, chi2


@dataclass(frozen=True)
class BinomialInterval:
    successes: int
    trials: int
    estimate: float
    lower: float
    upper: float
    confidence_level: float


@dataclass(frozen=True)
class PoissonRateInterval:
    events: int
    exposure_hours: float
    rate_per_hour: float
    lower_per_hour: float
    upper_per_hour: float
    upper_one_sided_per_hour: float
    confidence_level: float


@dataclass(frozen=True)
class ThresholdSelection:
    threshold: float | None
    successes: int
    trials: int
    synthetic_sensitivity: float
    target_synthetic_sensitivity: float
    calibrated: bool


def file_sha256(path: str | Path) -> str:
    """Return the lowercase SHA-256 digest of *path*."""

    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def robust_mad(values: Sequence[float]) -> float:
    """Gaussian-consistent median absolute deviation of finite samples."""

    data = np.asarray(values, dtype=float)
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        raise ValueError("cannot estimate MAD without finite samples")
    center = np.median(finite)
    scale = float(1.4826 * np.median(np.abs(finite - center)))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        raise ValueError("robust scale is zero or nonfinite")
    return scale


def interpolate_nonfinite(values: Sequence[float]) -> np.ndarray:
    """Linearly fill nonfinite samples for filtering while preserving length."""

    data = np.asarray(values, dtype=float)
    if data.ndim != 1 or data.size == 0:
        raise ValueError("values must be a nonempty vector")
    finite = np.isfinite(data)
    if finite.all():
        return data.copy()
    if not finite.any():
        raise ValueError("cannot interpolate a signal with no finite samples")
    indices = np.arange(data.size)
    output = data.copy()
    output[~finite] = np.interp(indices[~finite], indices[finite], data[finite])
    return output


def butterworth_bandpass_sos(
    sample_rate_hz: float, highpass_hz: float, lowpass_hz: float, order: int
) -> np.ndarray:
    """Create the frozen Butterworth bandpass in second-order sections."""

    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if not 0 < highpass_hz < lowpass_hz < sample_rate_hz / 2:
        raise ValueError("require 0 < highpass < lowpass < Nyquist")
    if order <= 0 or int(order) != order:
        raise ValueError("order must be a positive integer")
    return butter(
        int(order), [highpass_hz, lowpass_hz], btype="bandpass", fs=sample_rate_hz, output="sos"
    )


def zero_phase_filter(values: Sequence[float], sos: np.ndarray) -> np.ndarray:
    """Interpolate nonfinite samples and apply the frozen offline filter."""

    data = interpolate_nonfinite(values)
    if data.size < 32:
        raise ValueError("signal is too short for stable zero-phase filtering")
    return np.asarray(sosfiltfilt(sos, data), dtype=float)


def prespecified_threshold_grid(start: float, stop: float, step: float) -> np.ndarray:
    """Build an endpoint-inclusive decimal grid without floating drift."""

    if not 0 <= start <= stop <= 1 or step <= 0:
        raise ValueError("invalid threshold-grid bounds")
    count = int(np.floor((stop - start) / step + 1e-12))
    values = start + step * np.arange(count + 1)
    if values[-1] < stop - 1e-12:
        raise ValueError("step does not land on stop")
    values[-1] = stop
    return values


def clopper_pearson(
    successes: int, trials: int, confidence_level: float = 0.95
) -> BinomialInterval:
    """Two-sided exact binomial interval."""

    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("Require 0 <= successes <= trials and trials > 0")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must lie strictly between 0 and 1")
    alpha = 1.0 - confidence_level
    lower = 0.0 if successes == 0 else float(beta.ppf(alpha / 2, successes, trials - successes + 1))
    upper = 1.0 if successes == trials else float(beta.ppf(1 - alpha / 2, successes + 1, trials - successes))
    return BinomialInterval(
        successes=successes,
        trials=trials,
        estimate=successes / trials,
        lower=lower,
        upper=upper,
        confidence_level=confidence_level,
    )


def exact_poisson_rate(
    events: int, exposure_hours: float, confidence_level: float = 0.95
) -> PoissonRateInterval:
    """Exact Poisson interval and one-sided upper limit for an event rate."""

    if events < 0:
        raise ValueError("events must be nonnegative")
    if not np.isfinite(exposure_hours) or exposure_hours <= 0:
        raise ValueError("exposure_hours must be positive and finite")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must lie strictly between 0 and 1")
    alpha = 1.0 - confidence_level
    lower_count = 0.0 if events == 0 else 0.5 * float(chi2.ppf(alpha / 2, 2 * events))
    upper_count = 0.5 * float(chi2.ppf(1 - alpha / 2, 2 * (events + 1)))
    one_sided_upper_count = 0.5 * float(chi2.ppf(confidence_level, 2 * (events + 1)))
    return PoissonRateInterval(
        events=events,
        exposure_hours=exposure_hours,
        rate_per_hour=events / exposure_hours,
        lower_per_hour=lower_count / exposure_hours,
        upper_per_hour=upper_count / exposure_hours,
        upper_one_sided_per_hour=one_sided_upper_count / exposure_hours,
        confidence_level=confidence_level,
    )


def query_window_false_probability(rate_per_hour: float, window_seconds: float) -> float:
    """Poisson probability of one or more background events in a query window."""

    if rate_per_hour < 0 or window_seconds < 0:
        raise ValueError("rate and duration must be nonnegative")
    return 1.0 - exp(-rate_per_hour * window_seconds / 3600.0)


def select_synthetic_threshold(
    matched_scores: Sequence[float],
    thresholds: Sequence[float],
    target_sensitivity: float,
) -> ThresholdSelection:
    """Select the largest threshold reaching a synthetic recovery target.

    Only scores at prespecified injection anchors enter this rule. Background
    event counts must not be supplied and therefore cannot influence selection.
    """

    scores = np.asarray(matched_scores, dtype=float)
    grid = np.asarray(thresholds, dtype=float)
    if scores.ndim != 1 or grid.ndim != 1 or len(scores) == 0 or len(grid) == 0:
        raise ValueError("matched_scores and thresholds must be nonempty vectors")
    if np.any(~np.isfinite(scores)) or np.any(~np.isfinite(grid)):
        raise ValueError("scores and thresholds must be finite")
    if np.any(np.diff(grid) <= 0):
        raise ValueError("thresholds must be strictly increasing")
    if not 0.0 < target_sensitivity <= 1.0:
        raise ValueError("target_sensitivity must be in (0, 1]")

    valid: list[tuple[float, int]] = []
    for threshold in grid:
        successes = int(np.count_nonzero(scores >= threshold))
        if successes / len(scores) >= target_sensitivity:
            valid.append((float(threshold), successes))
    if not valid:
        return ThresholdSelection(
            threshold=None,
            successes=0,
            trials=len(scores),
            synthetic_sensitivity=0.0,
            target_synthetic_sensitivity=target_sensitivity,
            calibrated=False,
        )
    threshold, successes = valid[-1]
    return ThresholdSelection(
        threshold=threshold,
        successes=successes,
        trials=len(scores),
        synthetic_sensitivity=successes / len(scores),
        target_synthetic_sensitivity=target_sensitivity,
        calibrated=True,
    )


def choose_shared_anchors(
    eligible_mask: Sequence[bool],
    signal_length_samples: int,
    minimum_separation_samples: int,
    maximum_anchors: int,
    rng: np.random.Generator,
    candidate_stride_samples: int = 1,
) -> np.ndarray:
    """Choose fully eligible, separated injection starts without replacement."""

    mask = np.asarray(eligible_mask, dtype=bool)
    if mask.ndim != 1:
        raise ValueError("eligible_mask must be one-dimensional")
    if signal_length_samples <= 0 or signal_length_samples > len(mask):
        raise ValueError("invalid signal_length_samples")
    if minimum_separation_samples < 0 or maximum_anchors < 0 or candidate_stride_samples <= 0:
        raise ValueError("separation and count must be nonnegative; stride must be positive")
    if maximum_anchors == 0:
        return np.array([], dtype=int)

    bad = (~mask).astype(np.int64)
    cumulative = np.concatenate(([0], np.cumsum(bad)))
    starts = np.arange(0, len(mask) - signal_length_samples + 1, candidate_stride_samples)
    fully_eligible = (cumulative[starts + signal_length_samples] - cumulative[starts]) == 0
    candidates = starts[fully_eligible]
    if len(candidates) == 0:
        return np.array([], dtype=int)

    selected: list[int] = []
    for candidate in rng.permutation(candidates):
        value = int(candidate)
        if all(abs(value - existing) >= minimum_separation_samples for existing in selected):
            selected.append(value)
            if len(selected) == maximum_anchors:
                break
    return np.asarray(sorted(selected), dtype=int)


def match_events(
    truth_seconds: Iterable[float], detected_seconds: Iterable[float], tolerance_seconds: float
) -> tuple[int, list[tuple[float, float]]]:
    """One-to-one temporal matching for separated event sequences."""

    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be nonnegative")
    truth = sorted(float(x) for x in truth_seconds)
    detected = sorted(float(x) for x in detected_seconds)
    pairs: list[tuple[float, float]] = []
    i = j = 0
    while i < len(truth) and j < len(detected):
        delta = detected[j] - truth[i]
        if abs(delta) <= tolerance_seconds:
            pairs.append((truth[i], detected[j]))
            i += 1
            j += 1
        elif detected[j] < truth[i] - tolerance_seconds:
            j += 1
        else:
            i += 1
    return len(pairs), pairs


def git_commit_and_clean(repo_root: str | Path) -> tuple[str, bool]:
    """Return the current commit and whether tracked/untracked state is clean."""

    root = Path(repo_root)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    return commit, not bool(status.strip())


def frozen_run_metadata(repo_root: str | Path, config_paths: Sequence[str | Path]) -> dict:
    """Record the exact code revision and configuration digests for a run."""

    root = Path(repo_root)
    commit, clean = git_commit_and_clean(root)
    return {
        "git_commit": commit,
        "git_worktree_clean": clean,
        "config_sha256": {
            str(Path(path).as_posix()): file_sha256(root / path) for path in config_paths
        },
    }


def write_json(path: str | Path, value: object) -> None:
    """Write stable, human-readable JSON with dataclasses expanded."""

    def default(item: object) -> object:
        if hasattr(item, "__dataclass_fields__"):
            return asdict(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"Cannot serialize {type(item).__name__}")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True, default=default) + "\n", encoding="utf-8")
