from math import isclose

import numpy as np
import pytest

from src.benchmark import (
    butterworth_bandpass_sos,
    choose_shared_anchors,
    clopper_pearson,
    exact_poisson_rate,
    match_events,
    prespecified_threshold_grid,
    query_window_false_probability,
    robust_mad,
    select_synthetic_threshold,
)


def test_zero_event_upper_limit_is_minus_log_alpha_over_exposure():
    interval = exact_poisson_rate(0, 100.0, confidence_level=0.95)
    assert interval.rate_per_hour == 0.0
    assert interval.lower_per_hour == 0.0
    assert isclose(interval.upper_one_sided_per_hour, -np.log(0.05) / 100, rel_tol=1e-12)


def test_clopper_pearson_contains_observed_fraction():
    interval = clopper_pearson(9, 10)
    assert interval.lower < interval.estimate < interval.upper
    assert interval.estimate == 0.9


def test_threshold_rule_uses_largest_threshold_that_meets_target():
    scores = [0.91] * 9 + [0.61]
    result = select_synthetic_threshold(scores, [0.5, 0.6, 0.7, 0.8, 0.9, 0.925], 0.9)
    assert result.calibrated
    assert result.threshold == 0.9
    assert result.successes == 9


def test_threshold_rule_fails_closed():
    result = select_synthetic_threshold([0.4, 0.5], [0.6, 0.7], 0.9)
    assert not result.calibrated
    assert result.threshold is None


def test_anchors_are_fully_eligible_reproducible_and_separated():
    mask = np.zeros(2000, dtype=bool)
    mask[100:1900] = True
    mask[800:850] = False
    kwargs = dict(
        eligible_mask=mask,
        signal_length_samples=50,
        minimum_separation_samples=200,
        maximum_anchors=6,
        candidate_stride_samples=10,
    )
    first = choose_shared_anchors(rng=np.random.default_rng(17), **kwargs)
    second = choose_shared_anchors(rng=np.random.default_rng(17), **kwargs)
    assert np.array_equal(first, second)
    assert len(first) == 6
    assert np.all(np.diff(first) >= 200)
    assert all(mask[start : start + 50].all() for start in first)


def test_temporal_matching_is_one_to_one():
    count, pairs = match_events([10, 20, 30], [9.8, 10.2, 20.6, 30.1], 0.5)
    assert count == 2
    assert pairs == [(10.0, 9.8), (30.0, 30.1)]


def test_query_window_probability_matches_poisson_formula():
    probability = query_window_false_probability(1.0, 10.0)
    assert probability == pytest.approx(1 - np.exp(-10 / 3600))


def test_robust_mad_ignores_nonfinite_values():
    assert robust_mad([0, 1, 2, np.nan, np.inf]) == pytest.approx(1.4826)


def test_filter_and_threshold_grid_validate_protocol_values():
    sos = butterworth_bandpass_sos(100.0, 0.1, 8.0, 4)
    assert sos.shape[1] == 6
    assert np.allclose(
        prespecified_threshold_grid(0.5, 0.95, 0.025),
        np.linspace(0.5, 0.95, 19),
    )
