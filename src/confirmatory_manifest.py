"""Validated manifests and file routes for the confirmatory benchmark."""

from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path, PurePosixPath
import re
from typing import Iterable


SLEEP_EDF_BASE = "https://physionet.org/files/sleep-edfx/1.0.0"
CAP_BASE = "https://physionet.org/files/capslpdb/1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
OPERATIONS = {"identity", "subtract_a_minus_b"}
REQUIRED_FIELDS = {
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
}


@dataclass(frozen=True)
class ManifestRecord:
    participant_id: str
    record_id: str
    cohort: str
    analysis_role: str
    condition: str
    source_subdirectory: str
    signal_file: str
    signal_sha256: str
    annotation_file: str
    annotation_sha256: str
    eog_channel_a: str
    eog_channel_b: str
    eog_operation: str
    source_sample_rate_hz: float
    target_sample_rate_hz: float

    @property
    def dataset(self) -> str:
        return "sleep-edf" if self.source_subdirectory else "cap-sleep"

    @property
    def source_base_url(self) -> str:
        if self.source_subdirectory:
            return f"{SLEEP_EDF_BASE}/{self.source_subdirectory}"
        return CAP_BASE

    @property
    def local_subdirectory(self) -> PurePosixPath:
        if self.source_subdirectory:
            return PurePosixPath("sleep-edf") / self.source_subdirectory
        return PurePosixPath("cap-sleep")


@dataclass(frozen=True)
class ManifestAsset:
    participant_id: str
    cohort: str
    role: str
    filename: str
    sha256: str
    base_url: str
    local_subdirectory: PurePosixPath


def load_confirmatory_manifest(
    path: str | Path,
    *,
    cohorts: Iterable[str] | None = None,
    analysis_roles: Iterable[str] | None = None,
) -> tuple[ManifestRecord, ...]:
    """Load, validate and optionally filter one frozen CSV manifest."""

    selected_cohorts = None if cohorts is None else set(cohorts)
    selected_roles = None if analysis_roles is None else set(analysis_roles)
    source = Path(path)
    records: list[ManifestRecord] = []
    seen_record_ids: set[str] = set()
    seen_assets: set[tuple[str, str]] = set()
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS.difference(reader.fieldnames or ())
        if missing:
            raise ValueError("manifest is missing columns: " + ", ".join(sorted(missing)))
        for row_number, row in enumerate(reader, start=2):
            record = _record_from_row(row, row_number=row_number)
            if record.record_id in seen_record_ids:
                raise ValueError(f"duplicate record_id {record.record_id!r}")
            seen_record_ids.add(record.record_id)
            for filename, digest in (
                (record.signal_file, record.signal_sha256),
                (record.annotation_file, record.annotation_sha256),
            ):
                key = (record.source_subdirectory, filename)
                if key in seen_assets:
                    raise ValueError(f"duplicate manifest asset {key}")
                seen_assets.add(key)
                if not SHA256_RE.fullmatch(digest):
                    raise ValueError(f"manifest row {row_number} has invalid SHA256")
            if selected_cohorts is not None and record.cohort not in selected_cohorts:
                continue
            if selected_roles is not None and record.analysis_role not in selected_roles:
                continue
            records.append(record)
    if not records:
        raise ValueError("manifest selection contains no records")
    return tuple(records)


def manifest_assets(records: Iterable[ManifestRecord]) -> tuple[ManifestAsset, ...]:
    """Expand records into separately verified signal and annotation assets."""

    assets: list[ManifestAsset] = []
    for record in records:
        for role, filename, digest in (
            ("signal", record.signal_file, record.signal_sha256),
            ("annotation", record.annotation_file, record.annotation_sha256),
        ):
            assets.append(
                ManifestAsset(
                    participant_id=record.participant_id,
                    cohort=record.cohort,
                    role=role,
                    filename=filename,
                    sha256=digest,
                    base_url=record.source_base_url,
                    local_subdirectory=record.local_subdirectory,
                )
            )
    return tuple(assets)


def _record_from_row(row: dict[str, str], *, row_number: int) -> ManifestRecord:
    values = {key: (row.get(key) or "").strip() for key in REQUIRED_FIELDS}
    for key in ("participant_id", "record_id", "cohort", "analysis_role", "condition"):
        if not SAFE_ID_RE.fullmatch(values[key]):
            raise ValueError(f"manifest row {row_number} has invalid {key}")
    for key in ("signal_file", "annotation_file"):
        filename = values[key]
        if not filename or filename != Path(filename).name or "/" in filename or "\\" in filename:
            raise ValueError(f"manifest row {row_number} has unsafe {key}")
    subdirectory = values["source_subdirectory"]
    if subdirectory not in {"", "sleep-cassette", "sleep-telemetry"}:
        raise ValueError(f"manifest row {row_number} has invalid source_subdirectory")
    operation = values["eog_operation"]
    if operation not in OPERATIONS:
        raise ValueError(f"manifest row {row_number} has invalid EOG operation")
    if not values["eog_channel_a"]:
        raise ValueError(f"manifest row {row_number} has no primary EOG channel")
    if operation == "identity" and values["eog_channel_b"]:
        raise ValueError(f"manifest row {row_number} identity operation has channel B")
    if operation == "subtract_a_minus_b" and not values["eog_channel_b"]:
        raise ValueError(f"manifest row {row_number} subtraction has no channel B")
    try:
        source_rate = float(values["source_sample_rate_hz"])
        target_rate = float(values["target_sample_rate_hz"])
    except ValueError as exc:
        raise ValueError(f"manifest row {row_number} has a nonnumeric sample rate") from exc
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError(f"manifest row {row_number} has a nonpositive sample rate")
    return ManifestRecord(
        participant_id=values["participant_id"],
        record_id=values["record_id"],
        cohort=values["cohort"],
        analysis_role=values["analysis_role"],
        condition=values["condition"],
        source_subdirectory=subdirectory,
        signal_file=values["signal_file"],
        signal_sha256=values["signal_sha256"].lower(),
        annotation_file=values["annotation_file"],
        annotation_sha256=values["annotation_sha256"].lower(),
        eog_channel_a=values["eog_channel_a"],
        eog_channel_b=values["eog_channel_b"],
        eog_operation=operation,
        source_sample_rate_hz=source_rate,
        target_sample_rate_hz=target_rate,
    )
