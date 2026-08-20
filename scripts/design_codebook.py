#!/usr/bin/env python3
"""Print the data-independent construction of the rhythmic code pair."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.code_design import hamming_distance, select_prespecified_pair


def main() -> None:
    first, second = select_prespecified_pair()
    print(
        json.dumps(
            {
                "code_pair": [first, second],
                "hamming_distance": hamming_distance(first, second),
                "selection_used_eog_data": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
