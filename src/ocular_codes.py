"""Waveforms and matched-filter detection for prespecified ocular codes.

The detector in this module is deliberately small and auditable.  Canonical
templates use cosine-eased transitions, while synthetic engineering signals
use independently jittered dwell times, variable plateaus, and minimum-jerk
transitions.  Consequently, recovering a synthetic signal does not amount to
correlating a template with an exact copy of itself.

All signal amplitudes are expressed in the caller's units (normally
microvolts).  Template values are dimensionless, so the fitted regression
coefficient returned by :func:`normalized_cross_correlation` has signal units.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.signal import fftconvolve


_GAZE_SYMBOLS = frozenset("SLE")
_VALID_SYMBOLS = _GAZE_SYMBOLS | {"P"}


@dataclass(frozen=True)
class WaveformSpec:
    """Timing rules shared by canonical and perturbed ocular waveforms."""

    sample_rate_hz: float = 100.0
    pre_baseline_seconds: float = 0.4
    post_baseline_seconds: float = 0.4
    transition_seconds: float = 0.15
    short_seconds: float = 0.35
    long_seconds: float = 0.75
    equal_seconds: float = 0.55
    pause_seconds: float = 1.0
    starting_polarity: int = 1
    return_to_baseline: bool = True

    def __post_init__(self) -> None:
        positive = {
            "sample_rate_hz": self.sample_rate_hz,
            "transition_seconds": self.transition_seconds,
            "short_seconds": self.short_seconds,
            "long_seconds": self.long_seconds,
            "equal_seconds": self.equal_seconds,
            "pause_seconds": self.pause_seconds,
        }
        for name, value in positive.items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in (
            ("pre_baseline_seconds", self.pre_baseline_seconds),
            ("post_baseline_seconds", self.post_baseline_seconds),
        ):
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.starting_polarity not in (-1, 1):
            raise ValueError("starting_polarity must be -1 or 1")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "WaveformSpec":
        """Construct a spec from the ``waveform`` object in ``codebook.json``."""

        fields = cls.__dataclass_fields__
        unknown = set(values) - set(fields)
        if unknown:
            raise ValueError(f"unknown waveform fields: {sorted(unknown)}")
        return cls(**values)  # type: ignore[arg-type]

    def duration_seconds(self, symbol: str) -> float:
        durations = {
            "S": self.short_seconds,
            "L": self.long_seconds,
            "E": self.equal_seconds,
            "P": self.pause_seconds,
        }
        try:
            return durations[symbol]
        except KeyError as exc:
            raise ValueError(f"unknown rhythm symbol {symbol!r}") from exc


@dataclass(frozen=True)
class OcularCode:
    """A named sequence of target dwells and optional center pauses."""

    code_id: str
    rhythm: str

    def __post_init__(self) -> None:
        if not self.code_id:
            raise ValueError("code_id cannot be empty")
        validate_rhythm(self.rhythm)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "OcularCode":
        return cls(code_id=str(values["id"]), rhythm=str(values["rhythm"]))


@dataclass(frozen=True)
class OcularTemplate:
    """A canonical, dimensionless matched-filter template."""

    code_id: str
    rhythm: str
    time_scale: float
    sample_rate_hz: float
    values: NDArray[np.float64]

    @property
    def n_samples(self) -> int:
        return int(self.values.size)

    @property
    def duration_seconds(self) -> float:
        return self.n_samples / self.sample_rate_hz


@dataclass(frozen=True)
class PerturbationSpec:
    """Prespecified departures of injections from their detector templates."""

    interval_jitter_fraction: float = 0.15
    transition_seconds_range: tuple[float, float] = (0.08, 0.25)
    relative_plateau_amplitude_sd: float = 0.10
    overshoot_fraction_range: tuple[float, float] = (0.0, 0.15)
    random_polarity: bool = True
    time_scale: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.interval_jitter_fraction < 1:
            raise ValueError("interval_jitter_fraction must be in [0, 1)")
        if self.relative_plateau_amplitude_sd < 0:
            raise ValueError("relative_plateau_amplitude_sd cannot be negative")
        _validate_range("transition_seconds_range", self.transition_seconds_range, 0.0)
        _validate_range("overshoot_fraction_range", self.overshoot_fraction_range, 0.0)
        if not np.isfinite(self.time_scale) or self.time_scale <= 0:
            raise ValueError("time_scale must be finite and positive")

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        interval_jitter_fraction: float,
    ) -> "PerturbationSpec":
        """Construct from ``synthetic_injection`` configuration values."""

        return cls(
            interval_jitter_fraction=interval_jitter_fraction,
            transition_seconds_range=tuple(values["transition_seconds_range"]),  # type: ignore[arg-type]
            relative_plateau_amplitude_sd=float(
                values["relative_plateau_amplitude_sd"]
            ),
            overshoot_fraction_range=tuple(values["overshoot_fraction_range"]),  # type: ignore[arg-type]
            random_polarity=bool(values["random_polarity"]),
        )


@dataclass(frozen=True)
class MatchTrace:
    """Normalized matched-filter values at regularly scanned window starts."""

    start_samples: NDArray[np.int64]
    signed_scores: NDArray[np.float64]
    fitted_amplitudes: NDArray[np.float64]
    eligible: NDArray[np.bool_]
    template_samples: int

    @property
    def scores(self) -> NDArray[np.float64]:
        """Polarity-invariant scores."""

        return np.abs(self.signed_scores)


@dataclass(frozen=True)
class Detection:
    """One event surviving thresholding and cross-scale NMS."""

    code_id: str
    start_sample: int
    end_sample: int
    center_sample: float
    time_scale: float
    score: float
    signed_score: float
    fitted_amplitude: float
    amplitude_mad: float
    polarity: int


@dataclass(frozen=True)
class SuffixPrefixOverlap:
    """A proper suffix of ``source_id`` matching a prefix of ``target_id``."""

    source_id: str
    target_id: str
    length: int
    sequence: str


def validate_rhythm(rhythm: str) -> None:
    """Raise when a rhythm is empty, malformed, or contains no gaze target."""

    if not rhythm:
        raise ValueError("rhythm cannot be empty")
    unknown = set(rhythm) - _VALID_SYMBOLS
    if unknown:
        raise ValueError(f"unknown rhythm symbols: {sorted(unknown)}")
    if not any(symbol in _GAZE_SYMBOLS for symbol in rhythm):
        raise ValueError("rhythm must contain at least one gaze-target symbol")


def find_suffix_prefix_overlaps(
    codes: Mapping[str, str] | Iterable[OcularCode],
) -> tuple[SuffixPrefixOverlap, ...]:
    """Find all proper suffix-prefix matches, including self-overlaps.

    A match must be shorter than both participating strings.  Thus, comparing
    a code with itself does not report the trivial whole-string identity.
    """

    if isinstance(codes, Mapping):
        items = tuple((str(code_id), str(rhythm)) for code_id, rhythm in codes.items())
    else:
        items = tuple((code.code_id, code.rhythm) for code in codes)
    for _, rhythm in items:
        validate_rhythm(rhythm)

    overlaps: list[SuffixPrefixOverlap] = []
    for source_id, source in items:
        for target_id, target in items:
            for length in range(1, min(len(source), len(target))):
                if source[-length:] == target[:length]:
                    overlaps.append(
                        SuffixPrefixOverlap(
                            source_id=source_id,
                            target_id=target_id,
                            length=length,
                            sequence=source[-length:],
                        )
                    )
    return tuple(overlaps)


def validate_no_suffix_prefix(
    codes: Mapping[str, str] | Iterable[OcularCode],
) -> None:
    """Raise if any code has a proper suffix matching a code prefix."""

    overlaps = find_suffix_prefix_overlaps(codes)
    if overlaps:
        detail = ", ".join(
            f"{item.source_id}->{item.target_id}:{item.sequence!r}"
            for item in overlaps
        )
        raise ValueError(f"suffix-prefix overlaps found: {detail}")


def generate_template(
    code: OcularCode,
    waveform: WaveformSpec,
    *,
    time_scale: float = 1.0,
) -> OcularTemplate:
    """Generate a canonical template with cosine-eased transitions.

    ``time_scale`` stretches the movement transitions and rhythm intervals;
    the prespecified pre/post context remains fixed.  ``P`` returns to center,
    dwells there, and resets the following target to ``starting_polarity``.
    """

    if not np.isfinite(time_scale) or time_scale <= 0:
        raise ValueError("time_scale must be finite and positive")

    values = _render_waveform(
        code.rhythm,
        waveform,
        time_scale=time_scale,
        dwell_scales=np.ones(len(code.rhythm), dtype=float),
        target_amplitudes=None,
        transition_seconds=waveform.transition_seconds * time_scale,
        transition_kind="cosine",
        overshoot_fraction=0.0,
    )
    return OcularTemplate(
        code_id=code.code_id,
        rhythm=code.rhythm,
        time_scale=float(time_scale),
        sample_rate_hz=float(waveform.sample_rate_hz),
        values=values,
    )


def build_template_bank(
    code: OcularCode,
    waveform: WaveformSpec,
    time_scales: Sequence[float],
) -> tuple[OcularTemplate, ...]:
    """Build one canonical template per unique time scale."""

    if not time_scales:
        raise ValueError("time_scales cannot be empty")
    scales = tuple(float(scale) for scale in time_scales)
    if len(set(scales)) != len(scales):
        raise ValueError("time_scales must be unique")
    return tuple(generate_template(code, waveform, time_scale=scale) for scale in scales)


def synthesize_perturbed_code(
    code: OcularCode,
    waveform: WaveformSpec,
    *,
    amplitude: float,
    rng: np.random.Generator,
    perturbation: PerturbationSpec | None = None,
    polarity: int | None = None,
) -> NDArray[np.float64]:
    """Create a non-identical synthetic signal for engineering checks.

    Dwell durations are independently jittered; non-center plateau magnitudes
    vary independently; a single transition duration and overshoot are drawn
    for the event; and minimum-jerk rather than cosine easing is used.  Passing
    a seeded :class:`numpy.random.Generator` makes every draw reproducible.
    """

    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    if not np.isfinite(amplitude) or amplitude <= 0:
        raise ValueError("amplitude must be finite and positive")
    perturbation = perturbation or PerturbationSpec()

    if polarity is None:
        polarity = (
            int(rng.choice(np.array([-1, 1], dtype=int)))
            if perturbation.random_polarity
            else waveform.starting_polarity
        )
    if polarity not in (-1, 1):
        raise ValueError("polarity must be -1 or 1")

    jitter = perturbation.interval_jitter_fraction
    dwell_scales = rng.uniform(1.0 - jitter, 1.0 + jitter, len(code.rhythm))
    plateau_count = sum(symbol in _GAZE_SYMBOLS for symbol in code.rhythm)
    relative_amplitudes = rng.normal(
        1.0, perturbation.relative_plateau_amplitude_sd, plateau_count
    )
    # Avoid implausible polarity reversals from an unusually large Gaussian draw.
    relative_amplitudes = np.clip(relative_amplitudes, 0.25, 1.75)
    target_amplitudes = amplitude * relative_amplitudes
    transition_seconds = rng.uniform(*perturbation.transition_seconds_range)
    overshoot_fraction = rng.uniform(*perturbation.overshoot_fraction_range)

    injection_waveform = WaveformSpec(
        sample_rate_hz=waveform.sample_rate_hz,
        pre_baseline_seconds=waveform.pre_baseline_seconds,
        post_baseline_seconds=waveform.post_baseline_seconds,
        transition_seconds=waveform.transition_seconds,
        short_seconds=waveform.short_seconds,
        long_seconds=waveform.long_seconds,
        equal_seconds=waveform.equal_seconds,
        pause_seconds=waveform.pause_seconds,
        starting_polarity=polarity,
        return_to_baseline=waveform.return_to_baseline,
    )
    return _render_waveform(
        code.rhythm,
        injection_waveform,
        time_scale=perturbation.time_scale,
        dwell_scales=dwell_scales,
        target_amplitudes=target_amplitudes,
        transition_seconds=transition_seconds * perturbation.time_scale,
        transition_kind="minimum_jerk",
        overshoot_fraction=float(overshoot_fraction),
    )


def normalized_cross_correlation(
    signal: ArrayLike,
    template: ArrayLike,
    *,
    eligible_mask: ArrayLike | None = None,
    scan_step_samples: int = 1,
) -> MatchTrace:
    """Evaluate a normalized matched filter using FFT and rolling moments.

    A returned window is eligible only when every signal sample covered by the
    template is finite and ``True`` in ``eligible_mask``.  Scores at ineligible
    positions are retained for diagnostics but must not be thresholded; callers
    should use the returned ``eligible`` array.
    """

    x = _as_1d_float("signal", signal)
    raw_template = _as_1d_float("template", template)
    if scan_step_samples < 1 or int(scan_step_samples) != scan_step_samples:
        raise ValueError("scan_step_samples must be a positive integer")
    scan_step_samples = int(scan_step_samples)
    if raw_template.size < 2:
        raise ValueError("template must contain at least two samples")
    if raw_template.size > x.size:
        raise ValueError("template cannot be longer than signal")
    if not np.all(np.isfinite(raw_template)):
        raise ValueError("template must contain only finite values")

    centered_template = raw_template - raw_template.mean()
    template_energy = float(np.dot(centered_template, centered_template))
    if template_energy <= np.finfo(float).eps:
        raise ValueError("template must have non-zero variance")

    finite = np.isfinite(x)
    if eligible_mask is None:
        sample_eligible = finite
    else:
        requested = np.asarray(eligible_mask, dtype=bool)
        if requested.ndim != 1 or requested.size != x.size:
            raise ValueError("eligible_mask must be one-dimensional and match signal")
        sample_eligible = requested & finite

    safe_x = np.where(finite, x, 0.0)
    window = raw_template.size
    numerator = fftconvolve(safe_x, centered_template[::-1], mode="valid")

    cumulative = np.concatenate(([0.0], np.cumsum(safe_x, dtype=np.float64)))
    cumulative_sq = np.concatenate(
        ([0.0], np.cumsum(safe_x * safe_x, dtype=np.float64))
    )
    local_sum = cumulative[window:] - cumulative[:-window]
    local_sum_sq = cumulative_sq[window:] - cumulative_sq[:-window]
    local_energy = local_sum_sq - (local_sum * local_sum) / window
    local_energy = np.maximum(local_energy, 0.0)

    eligible_cumulative = np.concatenate(
        ([0], np.cumsum(sample_eligible, dtype=np.int64))
    )
    valid_count = eligible_cumulative[window:] - eligible_cumulative[:-window]
    full_window_eligible = valid_count == window

    denominator = np.sqrt(local_energy * template_energy)
    signed_scores = np.zeros_like(numerator, dtype=np.float64)
    nonflat = denominator > np.finfo(float).eps
    signed_scores[nonflat] = numerator[nonflat] / denominator[nonflat]
    signed_scores = np.clip(signed_scores, -1.0, 1.0)
    fitted_amplitudes = numerator / template_energy

    selected = np.arange(0, numerator.size, scan_step_samples, dtype=np.int64)
    return MatchTrace(
        start_samples=selected,
        signed_scores=signed_scores[selected],
        fitted_amplitudes=fitted_amplitudes[selected],
        eligible=full_window_eligible[selected],
        template_samples=window,
    )


def detect_code(
    signal: ArrayLike,
    templates: Sequence[OcularTemplate],
    *,
    calibration_mad: float,
    score_threshold: float,
    minimum_amplitude_mad: float,
    eligible_mask: ArrayLike | None = None,
    scan_step_seconds: float = 0.05,
    nms_seconds: float = 1.0,
) -> tuple[Detection, ...]:
    """Detect a code across time scales and merge candidates by greedy NMS."""

    if not templates:
        raise ValueError("templates cannot be empty")
    if not np.isfinite(calibration_mad) or calibration_mad <= 0:
        raise ValueError("calibration_mad must be finite and positive")
    if not 0 <= score_threshold <= 1:
        raise ValueError("score_threshold must be in [0, 1]")
    if not np.isfinite(minimum_amplitude_mad) or minimum_amplitude_mad < 0:
        raise ValueError("minimum_amplitude_mad must be finite and non-negative")
    if not np.isfinite(scan_step_seconds) or scan_step_seconds <= 0:
        raise ValueError("scan_step_seconds must be finite and positive")
    if not np.isfinite(nms_seconds) or nms_seconds < 0:
        raise ValueError("nms_seconds must be finite and non-negative")

    code_ids = {template.code_id for template in templates}
    sample_rates = {template.sample_rate_hz for template in templates}
    if len(code_ids) != 1:
        raise ValueError("all templates must represent the same code")
    if len(sample_rates) != 1:
        raise ValueError("all templates must have the same sample rate")
    sample_rate_hz = next(iter(sample_rates))
    scan_step_samples = max(1, int(round(scan_step_seconds * sample_rate_hz)))

    candidates: list[Detection] = []
    for template in templates:
        trace = normalized_cross_correlation(
            signal,
            template.values,
            eligible_mask=eligible_mask,
            scan_step_samples=scan_step_samples,
        )
        amplitude_mad = np.abs(trace.fitted_amplitudes) / calibration_mad
        qualified = (
            trace.eligible
            & (trace.scores >= score_threshold)
            & (amplitude_mad >= minimum_amplitude_mad)
        )
        for index in _qualified_local_maxima(trace.scores, qualified):
            start = int(trace.start_samples[index])
            end = start + template.n_samples
            signed_score = float(trace.signed_scores[index])
            fitted_amplitude = float(trace.fitted_amplitudes[index])
            candidates.append(
                Detection(
                    code_id=template.code_id,
                    start_sample=start,
                    end_sample=end,
                    center_sample=(start + end) / 2.0,
                    time_scale=template.time_scale,
                    score=abs(signed_score),
                    signed_score=signed_score,
                    fitted_amplitude=fitted_amplitude,
                    amplitude_mad=abs(fitted_amplitude) / calibration_mad,
                    polarity=1 if fitted_amplitude >= 0 else -1,
                )
            )

    return non_maximum_suppression(
        candidates, nms_samples=float(nms_seconds * sample_rate_hz)
    )


def non_maximum_suppression(
    detections: Sequence[Detection], *, nms_samples: float
) -> tuple[Detection, ...]:
    """Greedily retain the highest-scoring event within each time neighborhood.

    Time buckets make neighborhood lookup linear on average while preserving
    the exact score ordering and strict-distance rule of a naive pairwise
    implementation. At most one retained center can occupy a bucket whose
    width is the suppression radius.
    """

    if not np.isfinite(nms_samples) or nms_samples < 0:
        raise ValueError("nms_samples must be finite and non-negative")
    ranked = sorted(
        detections,
        key=lambda item: (item.score, item.amplitude_mad, -abs(item.time_scale - 1.0)),
        reverse=True,
    )
    kept: list[Detection] = []
    if nms_samples == 0:
        occupied_centers: set[float] = set()
        for candidate in ranked:
            if candidate.center_sample not in occupied_centers:
                kept.append(candidate)
                occupied_centers.add(candidate.center_sample)
        return tuple(sorted(kept, key=lambda item: item.center_sample))

    occupied_buckets: dict[int, float] = {}
    for candidate in ranked:
        bucket = int(np.floor(candidate.center_sample / nms_samples))
        neighborhood = (
            occupied_buckets.get(bucket - 1),
            occupied_buckets.get(bucket),
            occupied_buckets.get(bucket + 1),
        )
        if all(
            center is None
            or abs(candidate.center_sample - center) > nms_samples
            for center in neighborhood
        ):
            kept.append(candidate)
            occupied_buckets[bucket] = candidate.center_sample
    return tuple(sorted(kept, key=lambda item: item.center_sample))


def _render_waveform(
    rhythm: str,
    waveform: WaveformSpec,
    *,
    time_scale: float,
    dwell_scales: NDArray[np.float64],
    target_amplitudes: NDArray[np.float64] | None,
    transition_seconds: float,
    transition_kind: str,
    overshoot_fraction: float,
) -> NDArray[np.float64]:
    validate_rhythm(rhythm)
    if dwell_scales.shape != (len(rhythm),):
        raise ValueError("dwell_scales must have one value per rhythm symbol")
    if np.any(~np.isfinite(dwell_scales)) or np.any(dwell_scales <= 0):
        raise ValueError("dwell scales must be finite and positive")

    plateau_count = sum(symbol in _GAZE_SYMBOLS for symbol in rhythm)
    if target_amplitudes is None:
        target_amplitudes = np.ones(plateau_count, dtype=float)
    else:
        target_amplitudes = np.asarray(target_amplitudes, dtype=float)
        if target_amplitudes.shape != (plateau_count,):
            raise ValueError("target_amplitudes must have one value per gaze dwell")

    sample_rate_hz = waveform.sample_rate_hz
    chunks: list[NDArray[np.float64]] = [
        np.zeros(
            _sample_count(
                waveform.pre_baseline_seconds, sample_rate_hz, allow_zero=True
            )
        )
    ]
    current_level = 0.0
    current_sign = waveform.starting_polarity
    plateau_index = 0

    for symbol_index, symbol in enumerate(rhythm):
        if symbol == "P":
            if current_level != 0.0:
                chunks.append(
                    _transition(
                        current_level,
                        0.0,
                        transition_seconds,
                        sample_rate_hz,
                        kind=transition_kind,
                        overshoot_fraction=overshoot_fraction,
                    )
                )
                current_level = 0.0
            pause_seconds = (
                waveform.duration_seconds(symbol)
                * time_scale
                * float(dwell_scales[symbol_index])
            )
            chunks.append(np.zeros(_sample_count(pause_seconds, sample_rate_hz)))
            current_sign = waveform.starting_polarity
            continue

        magnitude = float(target_amplitudes[plateau_index])
        target_level = current_sign * magnitude
        plateau_index += 1
        chunks.append(
            _transition(
                current_level,
                target_level,
                transition_seconds,
                sample_rate_hz,
                kind=transition_kind,
                overshoot_fraction=overshoot_fraction,
            )
        )
        dwell_seconds = (
            waveform.duration_seconds(symbol)
            * time_scale
            * float(dwell_scales[symbol_index])
        )
        chunks.append(
            np.full(_sample_count(dwell_seconds, sample_rate_hz), target_level)
        )
        current_level = target_level
        current_sign *= -1

    if waveform.return_to_baseline and current_level != 0.0:
        chunks.append(
            _transition(
                current_level,
                0.0,
                transition_seconds,
                sample_rate_hz,
                kind=transition_kind,
                overshoot_fraction=overshoot_fraction,
            )
        )
    chunks.append(
        np.zeros(
            _sample_count(
                waveform.post_baseline_seconds, sample_rate_hz, allow_zero=True
            )
        )
    )
    return np.concatenate(chunks).astype(np.float64, copy=False)


def _transition(
    start: float,
    stop: float,
    duration_seconds: float,
    sample_rate_hz: float,
    *,
    kind: str,
    overshoot_fraction: float,
) -> NDArray[np.float64]:
    count = _sample_count(duration_seconds, sample_rate_hz)
    u = np.arange(1, count + 1, dtype=float) / count
    if kind == "cosine":
        progress = 0.5 - 0.5 * np.cos(np.pi * u)
    elif kind == "minimum_jerk":
        progress = 10.0 * u**3 - 15.0 * u**4 + 6.0 * u**5
    else:
        raise ValueError(f"unknown transition kind {kind!r}")
    transition = start + (stop - start) * progress
    if overshoot_fraction:
        # A smooth, endpoint-zero deformation.  It changes the transition shape
        # without introducing a discontinuity at either plateau.
        bump = np.sin(np.pi * u) ** 4
        transition += overshoot_fraction * (stop - start) * bump
    return transition


def _sample_count(
    seconds: float, sample_rate_hz: float, *, allow_zero: bool = False
) -> int:
    return max(0 if allow_zero else 1, int(round(seconds * sample_rate_hz)))


def _qualified_local_maxima(
    scores: NDArray[np.float64], qualified: NDArray[np.bool_]
) -> NDArray[np.int64]:
    """Return one deterministic local maximum from every qualified plateau."""

    if scores.shape != qualified.shape:
        raise ValueError("scores and qualified must have matching shapes")
    indices = np.flatnonzero(qualified)
    if indices.size == 0:
        return indices.astype(np.int64)
    selected: list[int] = []
    for index in indices:
        left_better = index > 0 and qualified[index - 1] and scores[index - 1] > scores[index]
        right_not_worse = (
            index + 1 < scores.size
            and qualified[index + 1]
            and scores[index + 1] >= scores[index]
        )
        if not left_better and not right_not_worse:
            selected.append(int(index))
    return np.asarray(selected, dtype=np.int64)


def _as_1d_float(name: str, values: ArrayLike) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if array.size == 0:
        raise ValueError(f"{name} cannot be empty")
    return array


def _validate_range(name: str, values: tuple[float, float], minimum: float) -> None:
    if len(values) != 2:
        raise ValueError(f"{name} must contain exactly two values")
    low, high = values
    if not np.isfinite(low) or not np.isfinite(high):
        raise ValueError(f"{name} values must be finite")
    if low < minimum or high < low:
        raise ValueError(f"invalid {name}: {values}")
