"""Discrete design constraints for self-synchronizing ocular rhythms."""

from __future__ import annotations

from itertools import combinations


def hamming_distance(first: str, second: str) -> int:
    if len(first) != len(second):
        raise ValueError("Hamming distance requires equal-length strings")
    return sum(left != right for left, right in zip(first, second))


def proper_suffix_prefix_overlaps(first: str, second: str) -> tuple[int, ...]:
    """Lengths at which a proper suffix of first is a prefix of second."""

    maximum = min(len(first), len(second))
    return tuple(
        length
        for length in range(1, maximum)
        if first[-length:] == second[:length]
    )


def is_cross_bifix_free(words: tuple[str, ...]) -> bool:
    """Whether no word suffix is a prefix of itself or another word."""

    return not any(
        proper_suffix_prefix_overlaps(first, second)
        for first in words
        for second in words
    )


def balanced_binary_rhythms(length: int = 8) -> list[str]:
    """Enumerate balanced S/L rhythms with no run longer than two symbols."""

    if length <= 0 or length % 2:
        raise ValueError("length must be a positive even integer")
    rhythms: list[str] = []
    for long_positions in combinations(range(length), length // 2):
        positions = set(long_positions)
        word = "".join("L" if index in positions else "S" for index in range(length))
        if "SSS" not in word and "LLL" not in word:
            rhythms.append(word)
    return rhythms


def select_prespecified_pair() -> tuple[str, str]:
    """Reproduce the frozen pair from data-independent coding constraints.

    Both words start with a unique two-short activation prefix, are balanced,
    avoid runs of three, form a cross-bifix-free set, and maximize their mutual
    Hamming distance. These constraints yield one unordered pair.
    """

    candidates = [
        word
        for word in balanced_binary_rhythms(8)
        if word.startswith("SS") and word.count("SS") == 1
    ]
    admissible = [
        pair for pair in combinations(candidates, 2) if is_cross_bifix_free(pair)
    ]
    if not admissible:
        raise RuntimeError("No admissible code pair")
    maximum_distance = max(hamming_distance(*pair) for pair in admissible)
    maximizers = sorted(pair for pair in admissible if hamming_distance(*pair) == maximum_distance)
    if len(maximizers) != 1:
        raise RuntimeError(f"Design constraints do not identify a unique pair: {maximizers}")
    return maximizers[0]
