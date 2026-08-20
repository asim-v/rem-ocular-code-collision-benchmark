import numpy as np

from scripts.run_ocular_code_benchmark import condition_seed, trailing_scale


def test_trailing_scale_cannot_see_future_samples():
    rng = np.random.default_rng(4)
    signal = rng.normal(size=2000)
    invalid = np.zeros(2000, dtype=bool)
    first = trailing_scale(signal, invalid, 1000, 10.0, 50.0, 10.0)
    changed_future = signal.copy()
    changed_future[1000:] *= 1000
    second = trailing_scale(changed_future, invalid, 1000, 10.0, 50.0, 10.0)
    assert first == second


def test_condition_seed_is_stable_and_label_specific():
    assert condition_seed(17, "00", "sync8_c0") == condition_seed(
        17, "00", "sync8_c0"
    )
    assert condition_seed(17, "00", "sync8_c0") != condition_seed(
        17, "01", "sync8_c0"
    )
