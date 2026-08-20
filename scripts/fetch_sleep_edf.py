"""Fetch the frozen Sleep-EDF pilot files from PhysioNet.

Files are first written to a ``.part`` path, verified against the SHA256
recorded in the frozen manifest, and then atomically published. Interrupted
downloads resume when the server honors HTTP Range requests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "config" / "sleep_edf_pilot_manifest.csv"
DEFAULT_DATA_ROOT = REPOSITORY_ROOT / "data" / "sleep-edf" / "sleep-cassette"
DEFAULT_BASE_URL = "https://physionet.org/files/sleep-edfx/1.0.0/sleep-cassette"
MAX_WORKERS = 8
BLOCK_BYTES = 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DownloadSpec:
    """One immutable file request derived from a manifest row."""

    subject_id: str
    split: str
    role: str
    filename: str
    sha256: str


@dataclass(frozen=True)
class DownloadResult:
    """Outcome for one requested file."""

    spec: DownloadSpec
    destination: Path
    status: str
    n_bytes: int


def bounded_workers(value: str) -> int:
    workers = int(value)
    if not 1 <= workers <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(
            f"workers must be between 1 and {MAX_WORKERS}"
        )
    return workers


def nonnegative_integer(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be nonnegative")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and SHA256-verify the frozen Sleep-EDF pilot files."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Frozen pilot manifest CSV.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Destination directory for EDF files.",
    )
    parser.add_argument(
        "--split",
        choices=("development", "test", "all"),
        default="development",
        help="Manifest split to fetch. The safe default is development.",
    )
    parser.add_argument(
        "--workers",
        type=bounded_workers,
        default=2,
        help=f"Concurrent downloads, from 1 to {MAX_WORKERS}.",
    )
    parser.add_argument(
        "--retries",
        type=nonnegative_integer,
        default=2,
        help="Retries after a transfer or checksum failure.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="Timeout for each HTTP operation.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Official PhysioNet release directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and list the selected manifest files without downloading.",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def _validate_filename(filename: str, *, row_number: int, field: str) -> None:
    if (
        not filename
        or filename != Path(filename).name
        or "/" in filename
        or "\\" in filename
        or not filename.lower().endswith(".edf")
    ):
        raise ValueError(
            f"manifest row {row_number} has an invalid {field}: {filename!r}"
        )


def _validate_digest(digest: str, *, row_number: int, field: str) -> str:
    normalized = digest.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"manifest row {row_number} has an invalid {field}: {digest!r}"
        )
    return normalized


def load_manifest(path: Path, split: str) -> tuple[DownloadSpec, ...]:
    """Validate a frozen manifest and return the files in the selected split."""

    if split not in {"development", "test", "all"}:
        raise ValueError(f"unknown split: {split!r}")
    required = {
        "subject_id",
        "split",
        "psg_file",
        "psg_sha256",
        "hypnogram_file",
        "hypnogram_sha256",
    }
    specs: list[DownloadSpec] = []
    seen_subjects: dict[str, str] = {}
    seen_files: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(
                "manifest is missing columns: " + ", ".join(sorted(missing))
            )
        for row_number, row in enumerate(reader, start=2):
            row_split = row["split"].strip()
            subject_id = row["subject_id"].strip()
            if row_split not in {"development", "test"}:
                raise ValueError(
                    f"manifest row {row_number} has an invalid split: {row_split!r}"
                )
            if not subject_id:
                raise ValueError(f"manifest row {row_number} has an empty subject_id")
            prior_split = seen_subjects.get(subject_id)
            if prior_split is not None:
                raise ValueError(
                    f"manifest contains subject {subject_id!r} more than once "
                    f"({prior_split} and {row_split})"
                )
            seen_subjects[subject_id] = row_split

            row_specs: list[DownloadSpec] = []
            for role in ("psg", "hypnogram"):
                filename = row[f"{role}_file"].strip()
                _validate_filename(
                    filename, row_number=row_number, field=f"{role}_file"
                )
                digest = _validate_digest(
                    row[f"{role}_sha256"],
                    row_number=row_number,
                    field=f"{role}_sha256",
                )
                prior_digest = seen_files.get(filename)
                if prior_digest is not None:
                    detail = (
                        "with conflicting SHA256 values"
                        if prior_digest != digest
                        else "more than once"
                    )
                    raise ValueError(
                        f"manifest lists {filename} {detail}"
                    )
                seen_files[filename] = digest
                row_specs.append(
                    DownloadSpec(
                        subject_id=subject_id,
                        split=row_split,
                        role=role,
                        filename=filename,
                        sha256=digest,
                    )
                )
            if split == "all" or row_split == split:
                specs.extend(row_specs)
    if not specs:
        raise ValueError(f"manifest contains no files for split {split!r}")
    return tuple(specs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()  # type: ignore[attr-defined]
    return int(status)


def _stream_once(url: str, part_path: Path, timeout_seconds: float) -> None:
    """Append a byte range when possible, otherwise restart the part file."""

    offset = part_path.stat().st_size if part_path.exists() else 0
    headers = {
        "User-Agent": "lucid-dream-communication-reproducibility/1.0"
    }
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)
    try:
        response_context = urlopen(request, timeout=timeout_seconds)
    except HTTPError as exc:
        if exc.code != 416 or not offset:
            raise
        # A stale or oversized partial file cannot be resumed safely.
        part_path.unlink(missing_ok=True)
        request = Request(
            url,
            headers={
                "User-Agent": "lucid-dream-communication-reproducibility/1.0"
            },
        )
        response_context = urlopen(request, timeout=timeout_seconds)

    with response_context as response:
        status = _response_status(response)
        append = bool(offset and status == 206 and part_path.exists())
        mode = "ab" if append else "wb"
        with part_path.open(mode) as handle:
            while True:
                block = response.read(BLOCK_BYTES)
                if not block:
                    break
                handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())


def download_one(
    spec: DownloadSpec,
    data_root: Path,
    base_url: str,
    *,
    timeout_seconds: float = 60.0,
    retries: int = 2,
) -> DownloadResult:
    """Download, verify, and atomically publish one manifest file."""

    if retries < 0:
        raise ValueError("retries must be nonnegative")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    data_root.mkdir(parents=True, exist_ok=True)
    destination = data_root / spec.filename
    part_path = destination.with_name(destination.name + ".part")

    if destination.is_file() and sha256_file(destination) == spec.sha256:
        part_path.unlink(missing_ok=True)
        return DownloadResult(spec, destination, "verified-existing", destination.stat().st_size)

    url = base_url.rstrip("/") + "/" + quote(spec.filename)
    last_problem = "download did not start"
    for attempt in range(retries + 1):
        try:
            _stream_once(url, part_path, timeout_seconds)
            observed = sha256_file(part_path)
            if observed != spec.sha256:
                last_problem = (
                    f"SHA256 mismatch for {spec.filename}: expected {spec.sha256}, "
                    f"observed {observed}"
                )
                part_path.unlink(missing_ok=True)
                continue
            os.replace(part_path, destination)
            return DownloadResult(
                spec, destination, "downloaded", destination.stat().st_size
            )
        except Exception as exc:
            last_problem = f"{type(exc).__name__}: {exc}"
            if attempt == retries:
                break
    raise RuntimeError(
        f"failed to retrieve {spec.filename} after {retries + 1} attempt(s): "
        f"{last_problem}"
    )


def main() -> None:
    args = parse_args()
    manifest = args.manifest.resolve()
    data_root = args.data_root.resolve()
    specs = load_manifest(manifest, args.split)
    print(
        f"Selected {len(specs)} files for split={args.split}; "
        f"destination={data_root}"
    )
    if args.dry_run:
        for spec in specs:
            print(f"{spec.split}\t{spec.subject_id}\t{spec.role}\t{spec.filename}")
        return

    results: list[DownloadResult] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                download_one,
                spec,
                data_root,
                args.base_url,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(
                    f"[{result.status}] {spec.filename} "
                    f"({result.n_bytes:,} bytes)"
                )
            except Exception as exc:
                message = f"{spec.filename}: {exc}"
                failures.append(message)
                print(f"[failed] {message}")

    if failures:
        raise SystemExit(
            f"{len(failures)} of {len(specs)} downloads failed; verified files were kept"
        )
    downloaded = sum(result.status == "downloaded" for result in results)
    existing = sum(result.status == "verified-existing" for result in results)
    print(
        f"Verified {len(results)} files: {downloaded} downloaded, "
        f"{existing} already present."
    )


if __name__ == "__main__":
    main()
