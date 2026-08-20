"""Create a non-preprocessing inventory of the released Donders files.

The audit reads EDF headers and embedded annotations without loading continuous
signals into memory. It does not select trials or assign scientific labels.
"""

from __future__ import annotations

import argparse
import json
import platform
from collections import Counter
from pathlib import Path

import mne
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "extracted",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs" / "data-audit",
    )
    return parser.parse_args()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def serialize_date(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def type_from_name(name: str) -> str:
    upper = name.upper()
    if "EOG" in upper:
        return "eog"
    if "EMG" in upper:
        return "emg"
    if "ECG" in upper or "EKG" in upper:
        return "ecg"
    return "eeg"


def inventory_edf(path: Path, root: Path) -> tuple[dict, list[dict], list[dict]]:
    raw = mne.io.read_raw_edf(path, preload=False, verbose="ERROR")
    channel_types = raw.get_channel_types()
    name_inferred_types = [type_from_name(name) for name in raw.ch_names]
    duration = float(raw.n_times / raw.info["sfreq"])
    record = {
        "relative_path": relative(path, root),
        "bytes": path.stat().st_size,
        "n_channels": len(raw.ch_names),
        "sampling_frequency_hz": float(raw.info["sfreq"]),
        "n_samples": int(raw.n_times),
        "duration_seconds": duration,
        "measurement_date": serialize_date(raw.info.get("meas_date")),
        "n_annotations": len(raw.annotations),
        "mne_channel_type_counts": json.dumps(
            dict(sorted(Counter(channel_types).items()))
        ),
        "name_inferred_channel_type_counts": json.dumps(
            dict(sorted(Counter(name_inferred_types).items()))
        ),
    }
    channels = [
        {
            "relative_path": record["relative_path"],
            "channel_index": index,
            "channel_name": name,
            "mne_channel_type": channel_type,
            "name_inferred_channel_type": inferred_type,
        }
        for index, (name, channel_type, inferred_type) in enumerate(
            zip(raw.ch_names, channel_types, name_inferred_types)
        )
    ]
    annotations = [
        {
            "relative_path": record["relative_path"],
            "annotation_index": index,
            "onset_seconds": float(onset),
            "duration_seconds": float(duration_value),
            "description": str(description),
        }
        for index, (onset, duration_value, description) in enumerate(
            zip(raw.annotations.onset, raw.annotations.duration, raw.annotations.description)
        )
    ]
    raw.close()
    return record, channels, annotations


def main() -> None:
    args = parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    root = args.data_root.resolve()
    output_dir = args.output_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"Data root does not exist: {root}")
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in root.rglob("*") if path.is_file())
    file_rows = [
        {
            "relative_path": relative(path, root),
            "suffix": path.suffix.lower(),
            "bytes": path.stat().st_size,
        }
        for path in files
    ]

    edf_rows: list[dict] = []
    channel_rows: list[dict] = []
    annotation_rows: list[dict] = []
    edf_errors: list[dict] = []
    for path in (path for path in files if path.suffix.lower() == ".edf"):
        try:
            record, channels, annotations = inventory_edf(path, root)
            edf_rows.append(record)
            channel_rows.extend(channels)
            annotation_rows.extend(annotations)
        except Exception as exc:  # Preserve all failures in the audit output.
            edf_errors.append(
                {
                    "relative_path": relative(path, root),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    pd.DataFrame(file_rows).to_csv(output_dir / "file_inventory.csv", index=False)
    pd.DataFrame(edf_rows).to_csv(output_dir / "edf_inventory.csv", index=False)
    pd.DataFrame(channel_rows).to_csv(output_dir / "channel_inventory.csv", index=False)
    pd.DataFrame(
        annotation_rows,
        columns=[
            "relative_path",
            "annotation_index",
            "onset_seconds",
            "duration_seconds",
            "description",
        ],
    ).to_csv(output_dir / "annotation_inventory.csv", index=False)
    pd.DataFrame(
        edf_errors,
        columns=["relative_path", "exception_type", "message"],
    ).to_csv(output_dir / "edf_errors.csv", index=False)

    suffix_counts = Counter(row["suffix"] or "[no suffix]" for row in file_rows)
    try:
        portable_data_root = root.relative_to(repository_root).as_posix()
    except ValueError:
        portable_data_root = "[external data root]"
    summary = {
        "data_root": portable_data_root,
        "n_files": len(file_rows),
        "total_bytes": sum(row["bytes"] for row in file_rows),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "n_edf_files": len(edf_rows),
        "n_edf_errors": len(edf_errors),
        "n_embedded_annotations": len(annotation_rows),
        "software": {
            "python": platform.python_version(),
            "mne": mne.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
