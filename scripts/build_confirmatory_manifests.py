#!/usr/bin/env python3
"""Build frozen confirmatory manifests from verified official metadata.

This script downloads only release inventories, checksum lists and subject
tables. It never downloads or opens a physiological waveform.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import csv
from hashlib import sha256
from pathlib import Path
import re
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SLEEP_EDF_OUTPUT = ROOT / "config" / "sleep_edf_confirmatory_manifest.csv"
DEFAULT_CAP_OUTPUT = ROOT / "config" / "cap_normal_manifest.csv"
USER_AGENT = "rem-ocular-code-collision-benchmark/1.0"

SLEEP_EDF_ROOT = "https://physionet.org/files/sleep-edfx/1.0.0"
CAP_ROOT = "https://physionet.org/files/capslpdb/1.0.0"

METADATA = {
    "sleep_records": (
        f"{SLEEP_EDF_ROOT}/RECORDS",
        "444cb5be68f22dfcc1a4114e6b8b8f99319e28ce7cdd130750d75109b1408286",
    ),
    "sleep_checksums": (
        f"{SLEEP_EDF_ROOT}/SHA256SUMS.txt",
        "1bc88e19e2e921f7851d7cf61e31ceb8f6d670211ca546a323e9db5a77525edf",
    ),
    "sc_subjects": (
        f"{SLEEP_EDF_ROOT}/SC-subjects.xls",
        "93d65494096d375ee302f1ce3a0506575b17a918b93d7cdaa5a2b32727366080",
    ),
    "st_subjects": (
        f"{SLEEP_EDF_ROOT}/ST-subjects.xls",
        "b377133e03897559e3e9fa8ef468f4505becaecebe1bc0c988d39a9158267758",
    ),
    "cap_records": (
        f"{CAP_ROOT}/RECORDS",
        "b794825833c98285c6e9f6052af79837afc1ac1939f7e410fdfc88dded52f945",
    ),
    "cap_checksums": (
        f"{CAP_ROOT}/SHA256SUMS.txt",
        "76988665dccb3d5420a0b9e8b2ef97c96d0e5e9a6a02bd4c5aba7889d309bf43",
    ),
}

FIELDS = (
    "participant_id",
    "record_id",
    "cohort",
    "analysis_role",
    "condition",
    "source_subdirectory",
    "signal_file",
    "signal_sha256",
    "annotation_file",
    "annotation_sha256",
    "eog_channel_a",
    "eog_channel_b",
    "eog_operation",
    "source_sample_rate_hz",
    "target_sample_rate_hz",
)

CAP_EOG = {
    1: ("ROC-LOC", "", "identity", 512),
    2: ("ROC-LOC", "", "identity", 128),
    3: ("ROC-LOC", "", "identity", 128),
    4: ("EOG dx", "EOG sin", "subtract_a_minus_b", 100),
    5: ("ROC-LOC", "", "identity", 128),
    6: ("ROC-A2", "LOC-A1", "subtract_a_minus_b", 128),
    7: ("ROC-A2", "LOC-A1", "subtract_a_minus_b", 128),
    8: ("EOG-R", "EOG-L", "subtract_a_minus_b", 100),
    9: ("ROC-A2", "LOC-A1", "subtract_a_minus_b", 128),
    10: ("ROC-LOC", "", "identity", 128),
    11: ("ROC-LOC", "", "identity", 128),
    12: ("ROC / A1", "LOC / A2", "subtract_a_minus_b", 100),
    13: ("ROC", "LOC", "subtract_a_minus_b", 200),
    14: ("ROC", "LOC", "subtract_a_minus_b", 200),
    15: ("EOG-R", "EOG-L", "subtract_a_minus_b", 200),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sleep-edf-output", type=Path, default=DEFAULT_SLEEP_EDF_OUTPUT)
    parser.add_argument("--cap-output", type=Path, default=DEFAULT_CAP_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if tracked manifests differ.")
    return parser.parse_args()


def fetch_verified(url: str, expected_sha256: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60.0) as response:
        payload = response.read()
    observed = sha256(payload).hexdigest()
    if observed != expected_sha256:
        raise RuntimeError(
            f"metadata checksum mismatch for {url}: expected {expected_sha256}, "
            f"observed {observed}"
        )
    return payload


def checksum_map(payload: bytes) -> dict[str, str]:
    output: dict[str, str] = {}
    for line in payload.decode("ascii").splitlines():
        digest, path = line.split(maxsplit=1)
        if path in output:
            raise ValueError(f"duplicate checksum path: {path}")
        output[path] = digest.lower()
    return output


def hypnogram_for(checksums: dict[str, str], subdirectory: str, record_prefix: str) -> str:
    prefix = f"{subdirectory}/{record_prefix}"
    matches = [
        path.split("/", 1)[1]
        for path in checksums
        if path.startswith(prefix) and path.endswith("-Hypnogram.edf")
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one hypnogram for {record_prefix}, found {matches}")
    return matches[0]


def sleep_edf_rows(metadata: dict[str, bytes]) -> list[dict[str, object]]:
    records = metadata["sleep_records"].decode("ascii").splitlines()
    checksums = checksum_map(metadata["sleep_checksums"])

    sc_table = pd.read_excel(BytesIO(metadata["sc_subjects"]), engine="xlrd")
    sc_available = {
        (int(row.subject), int(row.night))
        for row in sc_table[["subject", "night"]].itertuples(index=False)
    }

    st_table = pd.read_excel(BytesIO(metadata["st_subjects"]), engine="xlrd")
    numeric_subject = pd.to_numeric(st_table["Subject - age - sex"], errors="coerce")
    st_table = st_table[numeric_subject.notna()].copy()
    st_table["subject"] = numeric_subject[numeric_subject.notna()].astype(int)
    st_table["placebo_night"] = pd.to_numeric(st_table["Placebo night"]).astype(int)
    placebo_by_subject = dict(zip(st_table["subject"], st_table["placebo_night"]))

    rows: list[dict[str, object]] = []
    sc_pattern = re.compile(r"sleep-cassette/(SC4(?P<subject>\d{2})(?P<night>[12])[EFG]0-PSG\.edf)")
    st_pattern = re.compile(r"sleep-telemetry/(ST7(?P<subject>\d{2})(?P<night>[12])J0-PSG\.edf)")

    for path in records:
        sc_match = sc_pattern.fullmatch(path)
        st_match = st_pattern.fullmatch(path)
        if sc_match:
            subject = int(sc_match.group("subject"))
            night = int(sc_match.group("night"))
            if subject < 12:
                continue
            if (subject, night) not in sc_available:
                raise ValueError(f"SC record absent from verified subject table: {path}")
            subdirectory = "sleep-cassette"
            filename = sc_match.group(1)
            role = "primary_confirmation"
            condition = "spontaneous"
            participant = f"SC{subject:02d}"
            cohort = "sleep_edf_sc_confirmatory"
        elif st_match:
            subject = int(st_match.group("subject"))
            night = int(st_match.group("night"))
            if subject not in placebo_by_subject:
                raise ValueError(f"ST record absent from verified subject table: {path}")
            subdirectory = "sleep-telemetry"
            filename = st_match.group(1)
            is_placebo = night == placebo_by_subject[subject]
            role = "threshold_transport" if is_placebo else "exploratory_drug_condition"
            condition = "placebo" if is_placebo else "temazepam"
            participant = f"ST{subject:02d}"
            cohort = "sleep_edf_st_placebo" if is_placebo else "sleep_edf_st_temazepam"
        else:
            continue

        record_prefix = filename[:6]
        annotation = hypnogram_for(checksums, subdirectory, record_prefix)
        signal_key = f"{subdirectory}/{filename}"
        annotation_key = f"{subdirectory}/{annotation}"
        rows.append(
            {
                "participant_id": participant,
                "record_id": filename.removesuffix("-PSG.edf"),
                "cohort": cohort,
                "analysis_role": role,
                "condition": condition,
                "source_subdirectory": subdirectory,
                "signal_file": filename,
                "signal_sha256": checksums[signal_key],
                "annotation_file": annotation,
                "annotation_sha256": checksums[annotation_key],
                "eog_channel_a": "EOG horizontal",
                "eog_channel_b": "",
                "eog_operation": "identity",
                "source_sample_rate_hz": 100,
                "target_sample_rate_hz": 100,
            }
        )

    rows.sort(key=lambda row: (str(row["participant_id"]), str(row["record_id"])))
    sc_rows = [row for row in rows if row["analysis_role"] == "primary_confirmation"]
    placebo_rows = [row for row in rows if row["analysis_role"] == "threshold_transport"]
    drug_rows = [row for row in rows if row["analysis_role"] == "exploratory_drug_condition"]
    if len(sc_rows) != 129 or len({row["participant_id"] for row in sc_rows}) != 66:
        raise RuntimeError("unexpected untouched sleep-cassette record count")
    if len(placebo_rows) != 22 or len(drug_rows) != 22:
        raise RuntimeError("unexpected sleep-telemetry condition count")
    return rows


def cap_rows(metadata: dict[str, bytes]) -> list[dict[str, object]]:
    records = set(metadata["cap_records"].decode("ascii").splitlines())
    checksums = checksum_map(metadata["cap_checksums"])
    rows: list[dict[str, object]] = []
    for number, (channel_a, channel_b, operation, source_rate) in CAP_EOG.items():
        signal = f"n{number}.edf"
        annotation = f"n{number}.txt"
        if signal not in records:
            raise ValueError(f"CAP release inventory lacks {signal}")
        rows.append(
            {
                "participant_id": f"CAP-N{number:02d}",
                "record_id": f"n{number}",
                "cohort": "cap_normal_external",
                "analysis_role": "independent_montage_replication",
                "condition": "normal_control",
                "source_subdirectory": "",
                "signal_file": signal,
                "signal_sha256": checksums[signal],
                "annotation_file": annotation,
                "annotation_sha256": checksums[annotation],
                "eog_channel_a": channel_a,
                "eog_channel_b": channel_b,
                "eog_operation": operation,
                "source_sample_rate_hz": source_rate,
                "target_sample_rate_hz": 100,
            }
        )
    return rows


def csv_bytes(rows: list[dict[str, object]]) -> bytes:
    from io import StringIO

    handle = StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def publish(path: Path, payload: bytes, *, check: bool) -> None:
    if check:
        existing = path.read_bytes().replace(b"\r\n", b"\n") if path.is_file() else b""
        expected = payload.replace(b"\r\n", b"\n")
        if existing != expected:
            raise RuntimeError(f"frozen manifest differs from verified metadata: {path}")
        print(f"[verified] {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    print(f"[wrote] {path} ({payload.count(bytes([10])) - 1} records)")


def main() -> None:
    args = parse_args()
    metadata = {
        key: fetch_verified(url, digest)
        for key, (url, digest) in METADATA.items()
    }
    publish(
        args.sleep_edf_output.resolve(),
        csv_bytes(sleep_edf_rows(metadata)),
        check=args.check,
    )
    publish(
        args.cap_output.resolve(),
        csv_bytes(cap_rows(metadata)),
        check=args.check,
    )
    print("No physiological waveform was downloaded or opened.")


if __name__ == "__main__":
    main()
