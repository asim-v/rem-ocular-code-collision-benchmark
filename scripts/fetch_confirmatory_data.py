#!/usr/bin/env python3
"""Download and SHA256-verify one explicitly selected frozen cohort."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_sleep_edf import DownloadSpec, bounded_workers, download_one  # noqa: E402
from src.confirmatory_manifest import (  # noqa: E402
    load_confirmatory_manifest,
    manifest_assets,
)


DEFAULT_SLEEP_MANIFEST = ROOT / "config" / "sleep_edf_confirmatory_manifest.csv"
DEFAULT_CAP_MANIFEST = ROOT / "config" / "cap_normal_manifest.csv"
DEFAULT_DATA_ROOT = ROOT / "data" / "confirmatory"
COHORTS = {
    "sc": (DEFAULT_SLEEP_MANIFEST, "sleep_edf_sc_confirmatory"),
    "st-placebo": (DEFAULT_SLEEP_MANIFEST, "sleep_edf_st_placebo"),
    "st-temazepam": (DEFAULT_SLEEP_MANIFEST, "sleep_edf_st_temazepam"),
    "cap-normal": (DEFAULT_CAP_MANIFEST, "cap_normal_external"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=tuple(COHORTS), required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--workers", type=bounded_workers, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.retries < 0:
        parser.error("--retries must be nonnegative")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def main() -> None:
    args = parse_args()
    manifest, cohort = COHORTS[args.cohort]
    records = load_confirmatory_manifest(manifest, cohorts=[cohort])
    assets = manifest_assets(records)
    data_root = args.data_root.resolve()
    print(
        f"Selected cohort={args.cohort}: {len(records)} records, "
        f"{len(assets)} checksum-verified assets"
    )
    if args.dry_run:
        for asset in assets:
            relative = asset.local_subdirectory / asset.filename
            print(f"{asset.participant_id}\t{asset.role}\t{relative.as_posix()}")
        return

    failures: list[str] = []
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for asset in assets:
            destination = data_root.joinpath(*asset.local_subdirectory.parts)
            spec = DownloadSpec(
                subject_id=asset.participant_id,
                split=asset.cohort,
                role=asset.role,
                filename=asset.filename,
                sha256=asset.sha256,
            )
            future = executor.submit(
                download_one,
                spec,
                destination,
                asset.base_url,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
            )
            futures[future] = asset
        for future in as_completed(futures):
            asset = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"[{result.status}] {asset.filename} ({result.n_bytes:,} bytes)")
            except Exception as exc:
                failures.append(f"{asset.filename}: {exc}")
                print(f"[failed] {asset.filename}: {exc}")
    if failures:
        raise SystemExit(
            f"{len(failures)} of {len(assets)} assets failed; verified files were kept"
        )
    downloaded = sum(result.status == "downloaded" for result in results)
    existing = sum(result.status == "verified-existing" for result in results)
    print(
        f"Verified {len(results)} assets: {downloaded} downloaded, "
        f"{existing} already present"
    )


if __name__ == "__main__":
    main()
