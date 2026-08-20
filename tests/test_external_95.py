from hashlib import sha256
import json
import subprocess

from scripts.analyze_external_95_froc import fixed_sc_threshold_frame
from scripts.run_confirmatory_benchmark import (
    CAP_GATE,
    EXTERNAL_95_ST_GATE,
    TEMAZEPAM_GATE,
    TRANSPORT_GATE,
    stage_gate_paths,
)


def test_external_gate_freezes_sc_result_and_high_recovery_question():
    gate = json.loads(EXTERNAL_95_ST_GATE.read_text(encoding="utf-8"))

    assert gate["primary_cohort"] == "sleep_edf_st_placebo"
    assert gate["recovery_target"] == 0.95
    assert gate["candidate_storage_floor"] == 0.0
    assert gate["temazepam_access_authorized"] is False
    assert gate["cap_access_authorized"] is False
    root = EXTERNAL_95_ST_GATE.parents[1]
    for relative, expected in gate["generated_from"]["files"].items():
        blob = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        assert sha256(blob).hexdigest() == expected

    frozen = fixed_sc_threshold_frame(gate).iloc[0]
    assert frozen["candidate_threshold"] == gate["sc_95_descriptive_thresholds"][
        "candidate_threshold"
    ]
    assert frozen["control_threshold"] == gate["sc_95_descriptive_thresholds"][
        "control_threshold"
    ]


def test_stage_gates_keep_unapproved_external_corpora_sealed():
    assert stage_gate_paths("sc") == ()
    assert stage_gate_paths("st-placebo") == (
        TRANSPORT_GATE,
        EXTERNAL_95_ST_GATE,
    )
    assert stage_gate_paths("st-temazepam") == (TRANSPORT_GATE, TEMAZEPAM_GATE)
    assert stage_gate_paths("cap-normal") == (CAP_GATE,)
