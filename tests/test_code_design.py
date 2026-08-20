from src.code_design import (
    balanced_binary_rhythms,
    hamming_distance,
    is_cross_bifix_free,
    select_prespecified_pair,
)


def test_frozen_pair_is_uniquely_reproduced_without_eog_data():
    pair = select_prespecified_pair()
    assert set(pair) == {"SSLSLSLL", "SSLLSLSL"}
    assert is_cross_bifix_free(pair)
    assert hamming_distance(*pair) == 4


def test_balanced_candidates_have_expected_constraints():
    for word in balanced_binary_rhythms(8):
        assert word.count("S") == word.count("L") == 4
        assert "SSS" not in word
        assert "LLL" not in word
