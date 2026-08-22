from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_paper_figures import (  # noqa: E402
    CANDIDATE,
    CONTROL,
    load_contrasts,
    load_participant_differences,
    load_transport_points,
)


def test_manuscript_contrasts_match_tracked_results() -> None:
    contrasts = load_contrasts()
    assert contrasts["label"].tolist() == [
        "SC 85% (descriptive)",
        "SC 90% (primary)",
        "SC 95% (descriptive)",
        "ST 95% (external)",
    ]
    assert np.allclose(contrasts["estimate"], [0.1016187, 0.1298461, -25.4159623, -0.3797037])


def test_participant_summary_preserves_counts_and_exposure() -> None:
    data = load_participant_differences()
    sc = data.loc[data["corpus"].str.startswith("SC")]
    st = data.loc[data["corpus"].str.startswith("ST")]
    assert len(sc) == 66
    assert len(st) == 22
    assert np.isclose(sc["eligible_rem_hours"].sum(), 177.1327778)
    assert np.isclose(st["eligible_rem_hours"].sum(), 34.2372222)
    assert int(sc[CANDIDATE].sum()) == 323
    assert int(sc[CONTROL].sum()) == 300
    assert int(st[CANDIDATE].sum()) == 308
    assert int(st[CONTROL].sum()) == 321


def test_transport_table_contains_fixed_and_rematched_points() -> None:
    transport = load_transport_points()
    fixed = transport.loc[transport["condition"] == "Fixed SC threshold"].set_index("code_id")
    rematched = transport.loc[transport["condition"] == "Rematched in ST"].set_index("code_id")
    assert np.isclose(fixed.loc[CANDIDATE, "synthetic_recovery_fraction"], 415 / 440)
    assert np.isclose(fixed.loc[CONTROL, "synthetic_recovery_fraction"], 421 / 440)
    assert np.isclose(rematched.loc[CANDIDATE, "synthetic_recovery_fraction"], 0.95)
    assert np.isclose(rematched.loc[CONTROL, "synthetic_recovery_fraction"], 0.95)
