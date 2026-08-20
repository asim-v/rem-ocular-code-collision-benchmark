"""Audit internal consistency and event availability in the Donders release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "extracted",
    )
    parser.add_argument(
        "--inventory-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs" / "data-audit",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def explicit_study_map(description: str) -> dict[str, int]:
    pattern = re.compile(
        r"\*\s+(?P<title>[^\n]+?)\(study no:\s*(?P<study>\d+)\).*?"
        r"(?=(?:\n\*\s+[^\n]+?\(study no:)|\nNote:)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    mapping: dict[str, int] = {}
    for match in pattern.finditer(description):
        study = int(match.group("study"))
        for path in re.findall(r"Data/PSG/([^\s]+\.edf)", match.group(0), re.IGNORECASE):
            mapping[path.replace("\\", "/")] = study
    return mapping


def main() -> None:
    args = parse_args()
    root = args.data_root.resolve()
    inventory_dir = args.inventory_dir.resolve()
    inventory_dir.mkdir(parents=True, exist_ok=True)

    records = pd.read_csv(root / "Records.csv", dtype=str).fillna("")
    description = (root / "ExperimentalDescription.txt").read_text(encoding="utf-8")
    study_map = explicit_study_map(description)

    record_map = {
        row["Filename"].replace("\\", "/"): int(row["Treatment group"])
        for _, row in records.iterrows()
    }
    conflicts = [
        {
            "filename": filename,
            "study_in_experimental_description": expected,
            "treatment_group_in_records_csv": record_map.get(filename),
        }
        for filename, expected in sorted(study_map.items())
        if record_map.get(filename) != expected
    ]

    report_hashes: dict[str, list[str]] = defaultdict(list)
    for path in sorted((root / "Data" / "Reports").rglob("*.docx")):
        report_hashes[sha256(path)].append(path.relative_to(root).as_posix())
    duplicate_report_groups = [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(report_hashes.items())
        if len(paths) > 1
    ]

    annotation_path = inventory_dir / "annotation_inventory.csv"
    try:
        annotations = pd.read_csv(annotation_path)
        n_annotations = len(annotations)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        n_annotations = 0

    event_sidecar_suffixes = {".vmrk", ".tsv", ".eve", ".events", ".set", ".fif"}
    event_sidecars = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in event_sidecar_suffixes
    ]

    result = {
        "n_records": len(records),
        "declared_subject_count": 6,
        "unique_subject_ids_in_records": sorted(records["Subject ID"].unique().tolist()),
        "n_unique_subject_ids_in_records": int(records["Subject ID"].nunique()),
        "explicit_description_study_map": study_map,
        "records_csv_treatment_group_map": record_map,
        "n_study_code_conflicts": len(conflicts),
        "study_code_conflicts": conflicts,
        "n_duplicate_report_groups": len(duplicate_report_groups),
        "duplicate_report_groups": duplicate_report_groups,
        "n_embedded_edf_annotations": n_annotations,
        "event_sidecar_files": event_sidecars,
        "trial_reconstruction_from_release": (
            "not directly possible: no embedded EDF annotations or event sidecars"
        ),
    }
    output_path = inventory_dir / "release_metadata_audit.json"
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
