import json
from pathlib import Path

import numpy as np
import pytest

from src.ocular_codes import (
    Detection,
    OcularCode,
    PerturbationSpec,
    WaveformSpec,
    build_template_bank,
    detect_code,
    find_suffix_prefix_overlaps,
    generate_template,
    normalized_cross_correlation,
    non_maximum_suppression,
    synthesize_perturbed_code,
    validate_no_suffix_prefix,
)


ROOT = Path(__file__).resolve().parents[1]


def _frozen_specs():
    codebook = json.loads((ROOT / "config" / "codebook.json").read_text())
    benchmark = json.loads((ROOT / "config" / "benchmark.json").read_text())
    waveform = WaveformSpec.from_mapping(codebook["waveform"])
    codes = {
        entry["id"]: OcularCode.from_mapping(entry) for entry in codebook["codes"]
    }
    return waveform, codes, benchmark


def test_primary_pair_has_no_proper_suffix_prefix_collision():
    _, codes, _ = _frozen_specs()
    pair = [codes["sync8_c0"], codes["sync8_c1"]]

    assert find_suffix_prefix_overlaps(pair) == ()
    validate_no_suffix_prefix(pair)

    with pytest.raises(ValueError, match="suffix-prefix"):
        validate_no_suffix_prefix({"a": "SLS", "b": "SLL"})


def test_center_pause_resets_target_polarity_and_uses_smooth_transitions():
    waveform = WaveformSpec(sample_rate_hz=100)
    code = OcularCode("pause", "EEPEE")
    values = generate_template(code, waveform).values

    # The pause is a long central run; both blocks restart on positive polarity.
    central = np.flatnonzero(np.isclose(values, 0.0))
    runs = np.split(central, np.flatnonzero(np.diff(central) != 1) + 1)
    assert max(map(len, runs)) >= round(waveform.pause_seconds * 100)
    positive_runs = np.split(
        np.flatnonzero(values > 0.99),
        np.flatnonzero(np.diff(np.flatnonzero(values > 0.99)) != 1) + 1,
    )
    assert len([run for run in positive_runs if run.size]) == 2
    # Cosine easing has bounded changes and no single-sample step to a target.
    assert np.max(np.abs(np.diff(values))) < 0.25


def test_normalized_cross_correlation_is_polarity_invariant_at_detection():
    waveform = WaveformSpec(sample_rate_hz=100)
    code = OcularCode("test", "SSLSLSLL")
    bank = build_template_bank(code, waveform, [0.9, 1.0, 1.1])
    template = bank[1].values
    start = 700
    mask = np.ones(3000, dtype=bool)

    events = []
    positive_signal = np.random.default_rng(31).normal(0.0, 0.12, mask.size)
    positive_signal[start : start + template.size] += 4.0 * template
    for polarity, signal in ((1, positive_signal), (-1, -positive_signal)):
        detections = detect_code(
            signal,
            bank,
            calibration_mad=1.0,
            score_threshold=0.75,
            minimum_amplitude_mad=1.5,
            eligible_mask=mask,
            scan_step_seconds=0.05,
            nms_seconds=1.0,
        )
        nearest = min(detections, key=lambda item: abs(item.start_sample - start))
        assert abs(nearest.start_sample - start) <= 5
        assert nearest.polarity == polarity
        events.append(nearest)

    assert events[0].score == pytest.approx(events[1].score, abs=1e-12)
    assert events[0].signed_score == pytest.approx(-events[1].signed_score, abs=1e-12)


def test_perturbed_injection_is_distinct_and_recovered_across_scales():
    waveform, codes, benchmark = _frozen_specs()
    code = codes["sync8_c0"]
    detector = benchmark["detector"]
    injection_cfg = benchmark["synthetic_injection"]
    perturbation = PerturbationSpec.from_mapping(
        injection_cfg,
        interval_jitter_fraction=injection_cfg["primary_interval_jitter_fraction"],
    )
    bank = build_template_bank(code, waveform, detector["time_scales"])
    injection = synthesize_perturbed_code(
        code,
        waveform,
        amplitude=injection_cfg["primary_amplitude_mad"],
        rng=np.random.default_rng(20260819),
        perturbation=perturbation,
        polarity=-1,
    )

    canonical = generate_template(code, waveform).values
    assert injection.size != canonical.size or not np.allclose(injection, canonical)

    event_start = 1_000
    signal = np.random.default_rng(8).normal(0.0, 0.25, 4_000)
    signal[event_start : event_start + injection.size] += injection
    detections = detect_code(
        signal,
        bank,
        calibration_mad=1.0,
        score_threshold=0.5,
        minimum_amplitude_mad=1.5,
        eligible_mask=np.ones(signal.size, dtype=bool),
        scan_step_seconds=detector["scan_step_seconds"],
        nms_seconds=detector["nms_seconds"],
    )

    recovered = [
        item
        for item in detections
        if abs(item.start_sample - event_start)
        <= round(detector["match_tolerance_seconds"] * waveform.sample_rate_hz)
    ]
    assert len(recovered) == 1
    assert recovered[0].polarity == -1
    assert recovered[0].score >= 0.5
    # NMS must collapse the nearby multi-scale matches into a single event.
    assert sum(abs(item.center_sample - recovered[0].center_sample) <= 100 for item in detections) == 1


def test_eligible_mask_requires_full_window_containment():
    waveform = WaveformSpec(sample_rate_hz=100)
    code = OcularCode("test", "EEEE")
    bank = build_template_bank(code, waveform, [1.0])
    template = bank[0].values
    event_start = 400
    signal = np.random.default_rng(1).normal(0.0, 0.05, 2_000)
    signal[event_start : event_start + template.size] += 5.0 * template

    mask = np.ones(signal.size, dtype=bool)
    mask[event_start + template.size // 2] = False
    detections = detect_code(
        signal,
        bank,
        calibration_mad=1.0,
        score_threshold=0.8,
        minimum_amplitude_mad=1.5,
        eligible_mask=mask,
        scan_step_seconds=0.05,
        nms_seconds=1.0,
    )

    assert all(mask[item.start_sample : item.end_sample].all() for item in detections)
    assert not any(abs(item.start_sample - event_start) <= 5 for item in detections)


def test_ncc_amplitude_gate_uses_fitted_template_units_over_mad():
    waveform = WaveformSpec(sample_rate_hz=100)
    template = generate_template(OcularCode("test", "EEEE"), waveform).values
    start = 250
    signal = np.zeros(1_500)
    signal[start : start + template.size] = 1.2 * template

    trace = normalized_cross_correlation(signal, template, scan_step_samples=5)
    index = int(np.where(trace.start_samples == start)[0][0])
    assert trace.scores[index] == pytest.approx(1.0, abs=1e-12)
    assert trace.fitted_amplitudes[index] == pytest.approx(1.2, abs=1e-12)

    detections = detect_code(
        signal,
        [generate_template(OcularCode("test", "EEEE"), waveform)],
        calibration_mad=1.0,
        score_threshold=0.9,
        minimum_amplitude_mad=1.5,
        scan_step_seconds=0.05,
    )
    assert detections == ()


def test_seeded_perturbed_synthesis_is_deterministic_but_not_canonical():
    waveform = WaveformSpec(sample_rate_hz=100)
    code = OcularCode("test", "EEEEPEEEE")
    first = synthesize_perturbed_code(
        code, waveform, amplitude=4.0, rng=np.random.default_rng(17)
    )
    second = synthesize_perturbed_code(
        code, waveform, amplitude=4.0, rng=np.random.default_rng(17)
    )

    np.testing.assert_array_equal(first, second)
    assert np.max(np.abs(first)) > 0
    assert first.size != generate_template(code, waveform).n_samples or not np.allclose(
        first, generate_template(code, waveform).values
    )


def test_ncc_scales_to_a_moderate_continuous_record_without_direct_convolution(
    monkeypatch,
):
    """Guard the rolling mask check against an accidental O(signal*template) path."""

    waveform = WaveformSpec(sample_rate_hz=100)
    template = generate_template(OcularCode("test", "SSLSLSLL"), waveform).values
    signal = np.random.default_rng(3).normal(size=300_000)
    mask = np.ones(signal.size, dtype=bool)
    mask[125_000:125_010] = False

    def reject_direct_convolution(*args, **kwargs):
        raise AssertionError("rolling eligibility must use cumulative sums")

    monkeypatch.setattr(np, "convolve", reject_direct_convolution)
    trace = normalized_cross_correlation(
        signal,
        template,
        eligible_mask=mask,
        scan_step_samples=5,
    )

    expected = (signal.size - template.size) // 5 + 1
    assert trace.start_samples.size == expected
    crossing = (trace.start_samples <= 125_000) & (
        trace.start_samples + template.size > 125_000
    )
    assert crossing.any()
    assert not trace.eligible[crossing].any()


def _detection(center, score, amplitude=1.0):
    return Detection(
        code_id="test",
        start_sample=int(center),
        end_sample=int(center) + 1,
        center_sample=float(center),
        time_scale=1.0,
        score=float(score),
        signed_score=float(score),
        fitted_amplitude=float(amplitude),
        amplitude_mad=abs(float(amplitude)),
        polarity=1,
    )


def _naive_nms(detections, radius):
    ranked = sorted(
        detections,
        key=lambda item: (
            item.score,
            item.amplitude_mad,
            -abs(item.time_scale - 1.0),
        ),
        reverse=True,
    )
    kept = []
    for candidate in ranked:
        if all(abs(candidate.center_sample - prior.center_sample) > radius for prior in kept):
            kept.append(candidate)
    return tuple(sorted(kept, key=lambda item: item.center_sample))


@pytest.mark.parametrize("radius", [0.0, 0.3, 1.0, 3.5, 10.0])
def test_bucketed_nms_is_exactly_equivalent_to_naive_greedy_nms(radius):
    rng = np.random.default_rng(29)
    detections = [
        _detection(center, score, amplitude)
        for center, score, amplitude in zip(
            rng.integers(-20, 200, size=500) / 2,
            rng.random(500),
            rng.uniform(0.5, 5.0, size=500),
        )
    ]
    assert non_maximum_suppression(detections, nms_samples=radius) == _naive_nms(
        detections, radius
    )


def test_zero_radius_nms_scales_to_many_unique_candidates():
    detections = [_detection(index, 1.0 - index / 100_000) for index in range(20_000)]
    kept = non_maximum_suppression(detections, nms_samples=0.0)
    assert len(kept) == len(detections)
