import csv
from pathlib import Path

import pytest

from src.confirmatory_manifest import (
    load_confirmatory_manifest,
    manifest_assets,
)


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_confirmatory_manifests_have_expected_participants_and_records():
    sleep = load_confirmatory_manifest(ROOT / "config" / "sleep_edf_confirmatory_manifest.csv")
    cap = load_confirmatory_manifest(ROOT / "config" / "cap_normal_manifest.csv")

    sc = [row for row in sleep if row.cohort == "sleep_edf_sc_confirmatory"]
    placebo = [row for row in sleep if row.cohort == "sleep_edf_st_placebo"]
    temazepam = [row for row in sleep if row.cohort == "sleep_edf_st_temazepam"]
    assert len(sc) == 129
    assert len({row.participant_id for row in sc}) == 66
    assert not {f"SC{number:02d}" for number in range(12)} & {
        row.participant_id for row in sc
    }
    assert len(placebo) == len(temazepam) == 22
    assert len(cap) == 15
    assert {row.record_id for row in cap} == {f"n{number}" for number in range(1, 16)}


def test_manifest_assets_route_sleep_edf_and_cap_separately():
    sleep = load_confirmatory_manifest(
        ROOT / "config" / "sleep_edf_confirmatory_manifest.csv",
        cohorts=["sleep_edf_st_placebo"],
    )
    cap = load_confirmatory_manifest(ROOT / "config" / "cap_normal_manifest.csv")
    sleep_assets = manifest_assets(sleep)
    cap_assets = manifest_assets(cap)

    assert len(sleep_assets) == 44
    assert all(asset.local_subdirectory.as_posix() == "sleep-edf/sleep-telemetry" for asset in sleep_assets)
    assert all("sleep-edfx/1.0.0/sleep-telemetry" in asset.base_url for asset in sleep_assets)
    assert len(cap_assets) == 30
    assert all(asset.local_subdirectory.as_posix() == "cap-sleep" for asset in cap_assets)
    assert all("capslpdb/1.0.0" in asset.base_url for asset in cap_assets)


def test_manifest_rejects_unsafe_filename(tmp_path):
    source = ROOT / "config" / "cap_normal_manifest.csv"
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["signal_file"] = "../n1.edf"
    target = tmp_path / "unsafe.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="unsafe signal_file"):
        load_confirmatory_manifest(target)
