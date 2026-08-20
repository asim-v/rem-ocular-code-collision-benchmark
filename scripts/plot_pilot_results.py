#!/usr/bin/env python3
"""Create publication-ready figures from committed pilot outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs" / "ocular-code-pilot"
DEFAULT_OUTPUT = DEFAULT_INPUT / "figures"
CODE_ORDER = [
    "legacy_lrl",
    "legacy_lrlr",
    "legacy_lrlrlr",
    "double_lrlr_pause",
    "iso8_matched",
    "sync8_c1",
    "sync8_c0",
]
CODE_LABELS = {
    "legacy_lrl": "LRL",
    "legacy_lrlr": "LRLR",
    "legacy_lrlrlr": "LRLRLR",
    "double_lrlr_pause": "LRLR pause LRLR",
    "iso8_matched": "Isochronous 8",
    "sync8_c1": "Rhythmic C1",
    "sync8_c0": "Rhythmic C0",
}
SPLIT_COLORS = {"development": "#7A7A7A", "test": "#167D9A"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_rate_frame(input_root: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for split in ("development", "test"):
        summary = json.loads((input_root / split / "summary.json").read_text())
        for value in summary["background_rates"]:
            if value["scope"] == "rem":
                rows.append({"split": split, **value})
    return pd.DataFrame(rows)


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_collision_rates(rates: pd.DataFrame, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    positions = np.arange(len(CODE_ORDER))
    offsets = {"development": -0.13, "test": 0.13}
    for split in ("development", "test"):
        selected = rates[rates["split"] == split].set_index("code_id").loc[CODE_ORDER]
        y = selected["rate_per_hour"].to_numpy()
        lower = y - selected["lower_per_hour"].to_numpy()
        upper = selected["upper_per_hour"].to_numpy() - y
        ax.errorbar(
            positions + offsets[split],
            y,
            yerr=np.vstack([lower, upper]),
            fmt="o",
            markersize=6,
            capsize=3,
            linewidth=1.2,
            color=SPLIT_COLORS[split],
            label=split.capitalize(),
        )
    ax.set_yscale("log")
    ax.set_ylabel("False detections per REM hour")
    ax.set_xticks(positions, [CODE_LABELS[code] for code in CODE_ORDER], rotation=28, ha="right")
    ax.grid(axis="y", which="both", alpha=0.22)
    ax.legend(frameon=False)
    ax.set_title("Continuous background collision rates at frozen thresholds")
    fig.tight_layout()
    save_figure(fig, output_dir, "rem_collision_rates")


def plot_primary_pairs(input_root: Path, output_dir: Path) -> None:
    frames: list[pd.DataFrame] = []
    for split in ("development", "test"):
        frame = pd.read_csv(input_root / split / "background_by_recording.csv", dtype={"subject_id": str})
        frame["subject_id"] = frame["subject_id"].str.zfill(2)
        frame["split"] = split
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    data = data[
        (data["scope"] == "rem")
        & data["code_id"].isin(["iso8_matched", "sync8_c0"])
    ]

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.2), sharey=True)
    for ax, split in zip(axes, ("development", "test")):
        selected = data[data["split"] == split]
        pivot = selected.pivot(index="subject_id", columns="code_id", values="events")
        for subject, row in pivot.iterrows():
            ax.plot(
                [0, 1],
                [row["iso8_matched"], row["sync8_c0"]],
                marker="o",
                linewidth=1.2,
                alpha=0.8,
                label=subject,
            )
        ax.set_xticks([0, 1], ["Isochronous 8", "Rhythmic C0"])
        ax.set_title(split.capitalize())
        ax.grid(axis="y", alpha=0.2)
    axes[0].set_ylabel("REM collision count per participant")
    fig.suptitle("Prespecified paired comparison")
    fig.tight_layout()
    save_figure(fig, output_dir, "primary_paired_counts")


def plot_primary_synthetic_recovery(input_root: Path, output_dir: Path) -> None:
    rows: list[pd.DataFrame] = []
    for split in ("development", "test"):
        frame = pd.read_csv(input_root / split / "synthetic_summary.csv")
        frame = frame[
            (frame["amplitude_mad"] == 4.0)
            & (frame["interval_jitter_fraction"] == 0.15)
            & frame["code_id"].isin(["iso8_matched", "sync8_c0"])
        ].copy()
        frame["split"] = split
        rows.append(frame)
    data = pd.concat(rows, ignore_index=True)

    fig, ax = plt.subplots(figsize=(5.8, 4.2))
    code_positions = {"iso8_matched": 0, "sync8_c0": 1}
    split_offsets = {"development": -0.12, "test": 0.12}
    for split in ("development", "test"):
        selected = data[data["split"] == split].set_index("code_id")
        x = np.array([code_positions[code] for code in ("iso8_matched", "sync8_c0")])
        y = selected.loc[["iso8_matched", "sync8_c0"], "synthetic_recovery_fraction"].to_numpy()
        lower = y - selected.loc[["iso8_matched", "sync8_c0"], "exact_lower"].to_numpy()
        upper = selected.loc[["iso8_matched", "sync8_c0"], "exact_upper"].to_numpy() - y
        ax.errorbar(
            x + split_offsets[split],
            y,
            yerr=np.vstack([lower, upper]),
            fmt="o",
            markersize=7,
            capsize=3,
            color=SPLIT_COLORS[split],
            label=split.capitalize(),
        )
    ax.axhline(0.9, color="#444444", linestyle=":", linewidth=1, label="Development target")
    ax.set_ylim(0.72, 1.01)
    ax.set_ylabel("Synthetic engineering recovery")
    ax.set_xticks([0, 1], ["Isochronous 8", "Rhythmic C0"])
    ax.grid(axis="y", alpha=0.2)
    ax.legend(frameon=False)
    ax.set_title("Recovery at frozen thresholds")
    fig.tight_layout()
    save_figure(fig, output_dir, "primary_synthetic_recovery")


def main() -> None:
    args = parse_args()
    input_root = args.input_root.resolve()
    output_dir = args.output_dir.resolve()
    rates = load_rate_frame(input_root)
    plot_collision_rates(rates, output_dir)
    plot_primary_pairs(input_root, output_dir)
    plot_primary_synthetic_recovery(input_root, output_dir)
    print(f"Wrote six figure files to {output_dir}")


if __name__ == "__main__":
    main()
