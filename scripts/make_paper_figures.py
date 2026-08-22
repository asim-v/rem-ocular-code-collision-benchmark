"""Build manuscript figures from the tracked result tables.

The script intentionally depends only on compact, versioned CSV outputs. Raw
polysomnography is not required to regenerate any manuscript figure.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / "paper" / "figures"
SC_ANALYSIS = ROOT / "outputs" / "ocular-code-confirmatory" / "sc-analysis"
SC_EVENTS = ROOT / "outputs" / "ocular-code-confirmatory" / "sc" / "background_events.csv"
SC_EXPOSURE = ROOT / "outputs" / "ocular-code-confirmatory" / "sc" / "exposure.csv"
ST_ANALYSIS = ROOT / "outputs" / "ocular-code-external95" / "st-analysis"
ST_EVENTS = ROOT / "outputs" / "ocular-code-external95" / "st-placebo" / "background_events.csv"
ST_EXPOSURE = ROOT / "outputs" / "ocular-code-external95" / "st-placebo" / "exposure.csv"

CANDIDATE = "sync8_c0"
CONTROL = "iso8_matched"
CODE_LABELS = {CANDIDATE: "Rhythmic", CONTROL: "Isochronous"}
CODE_COLORS = {CANDIDATE: "#0072B2", CONTROL: "#D55E00"}


def _set_style() -> None:
    sns.set_theme(context="paper", style="whitegrid", font_scale=1.0)
    plt.rcParams.update(
        {
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 120,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def _save(fig: plt.Figure, stem: str) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {"Author": "Javier Emilio Bazan Sanchez", "Creator": "Python figure pipeline"}
    fig.savefig(FIGURE_DIR / f"{stem}.pdf", bbox_inches="tight", metadata=metadata)
    fig.savefig(FIGURE_DIR / f"{stem}.png", dpi=300, bbox_inches="tight", metadata=metadata)
    plt.close(fig)


def plot_code_timing() -> None:
    """Show the matched duration and distinct interval structures."""
    codes = [
        (CANDIDATE, np.array([0.35, 0.35, 0.75, 0.35, 0.75, 0.35, 0.75, 0.75]), list("SSLSLSLL")),
        (CONTROL, np.repeat(0.55, 8), ["0.55"] * 8),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 3.25), sharex=True)
    for ax, (code_id, intervals, interval_labels) in zip(axes, codes, strict=True):
        boundaries = np.r_[0.0, np.cumsum(intervals)]
        positions = np.array([1, -1] * 4)
        ax.step(boundaries, np.r_[positions, positions[-1]], where="post", color=CODE_COLORS[code_id], lw=2.2)
        ax.fill_between(
            boundaries,
            np.r_[positions, positions[-1]],
            0,
            step="post",
            color=CODE_COLORS[code_id],
            alpha=0.11,
        )
        for left, right, label in zip(boundaries[:-1], boundaries[1:], interval_labels, strict=True):
            ax.text((left + right) / 2, 1.22, label, ha="center", va="center", fontsize=7.5)
        ax.set_yticks([-1, 1], ["right", "left"])
        ax.set_ylim(-1.5, 1.55)
        ax.grid(axis="x", color="#D8D8D8", lw=0.6)
        ax.grid(axis="y", visible=False)
        ax.set_title(f"{CODE_LABELS[code_id]} code", loc="left", fontsize=10)
        ax.text(4.4, -1.34, "total dwell: 4.4 s", ha="right", va="center", fontsize=8, color="#444444")
    axes[-1].set_xlabel("Time from code onset (s)")
    axes[-1].set_xlim(0, 4.4)
    fig.suptitle("Equal duration and movement count, different temporal structure", y=1.01, fontsize=11, fontweight="bold")
    fig.tight_layout()
    _save(fig, "code_timing")


def load_contrasts() -> pd.DataFrame:
    """Load the four manuscript contrasts in display order."""
    sc = pd.read_csv(SC_ANALYSIS / "clustered_contrasts.csv")
    st = pd.read_csv(ST_ANALYSIS / "clustered_contrast.csv")
    rows: list[dict[str, float | str]] = []
    for recovery, role in [(0.85, "descriptive"), (0.90, "primary"), (0.95, "descriptive")]:
        row = sc.loc[np.isclose(sc["requested_recovery_fraction"], recovery)].iloc[0]
        rows.append(
            {
                "label": f"SC {int(recovery * 100)}% ({role})",
                "recovery": recovery,
                "estimate": row["estimate"],
                "lower": row["lower"],
                "upper": row["upper"],
                "panel": "SC lower-rate points" if recovery < 0.95 else "High-recovery tests",
            }
        )
    row = st.iloc[0]
    rows.append(
        {
            "label": "ST 95% (external)",
            "recovery": 0.95,
            "estimate": row["estimate"],
            "lower": row["lower"],
            "upper": row["upper"],
            "panel": "High-recovery tests",
        }
    )
    return pd.DataFrame(rows)


def plot_matched_contrasts() -> None:
    """Plot participant-bootstrap intervals at every reported operating point."""
    data = load_contrasts()
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.15), gridspec_kw={"width_ratios": [1.0, 1.35]})
    specifications = [
        (axes[0], "SC lower-rate points", (-1.3, 1.3)),
        (axes[1], "High-recovery tests", (-55, 17)),
    ]
    for panel_index, (ax, panel, limits) in enumerate(specifications):
        subset = data.loc[data["panel"] == panel].reset_index(drop=True)
        y = np.arange(len(subset))[::-1]
        colors = ["#6A3D9A" if "primary" in label or "external" in label else "#777777" for label in subset["label"]]
        for row_index, (yi, (_, row), color) in enumerate(zip(y, subset.iterrows(), colors, strict=True)):
            ax.errorbar(
                row["estimate"],
                yi,
                xerr=[[row["estimate"] - row["lower"]], [row["upper"] - row["estimate"]]],
                fmt="o",
                color=color,
                ecolor=color,
                elinewidth=1.8,
                capsize=3,
                ms=5,
            )
            label_y = yi - 0.18 if row_index == 0 else yi + 0.18
            ax.text(row["estimate"], label_y, f"{row['estimate']:.2f}", ha="center", va="center", fontsize=7.5, color=color)
        ax.axvline(0, color="#222222", lw=1.0)
        ax.set_yticks(y, subset["label"])
        ax.set_xlim(*limits)
        ax.set_ylim(-0.25, 1.25)
        ax.set_title(f"{chr(65 + panel_index)}  {panel}", loc="left", fontsize=10)
        ax.set_xlabel("Rhythmic minus isochronous events/h")
        ax.grid(axis="y", visible=False)
    fig.suptitle("Matched-recovery estimates do not show a stable code advantage", y=1.04, fontsize=11, fontweight="bold")
    fig.tight_layout()
    _save(fig, "matched_contrasts")


def participant_rate_differences(
    events_path: Path,
    exposure_path: Path,
    thresholds: dict[str, float],
    corpus_label: str,
) -> pd.DataFrame:
    """Calculate descriptive participant-level rate differences."""
    events = pd.read_csv(events_path)
    exposure = pd.read_csv(exposure_path)
    hours = exposure.groupby("subject_id", sort=True)["eligible_rem_hours"].sum()
    result = pd.DataFrame({"subject_id": hours.index, "eligible_rem_hours": hours.values})
    for code_id, threshold in thresholds.items():
        selected = events.loc[(events["code_id"] == code_id) & (events["score"] >= threshold)]
        counts = selected.groupby("subject_id").size()
        result[code_id] = result["subject_id"].map(counts).fillna(0).astype(int)
        result[f"{code_id}_rate"] = result[code_id] / result["eligible_rem_hours"]
    result["rate_difference"] = result[f"{CANDIDATE}_rate"] - result[f"{CONTROL}_rate"]
    result["corpus"] = corpus_label
    return result


def load_participant_differences() -> pd.DataFrame:
    sc_points = pd.read_csv(SC_ANALYSIS / "matched_froc_points.csv")
    st_points = pd.read_csv(ST_ANALYSIS / "matched_froc_points.csv")

    def thresholds_at(points: pd.DataFrame, recovery: float) -> dict[str, float]:
        selected = points.loc[np.isclose(points["requested_recovery_fraction"], recovery)]
        return dict(zip(selected["code_id"], selected["threshold"], strict=True))

    sc = participant_rate_differences(SC_EVENTS, SC_EXPOSURE, thresholds_at(sc_points, 0.90), "SC 90%\n(n = 66)")
    st = participant_rate_differences(ST_EVENTS, ST_EXPOSURE, thresholds_at(st_points, 0.95), "ST 95%\n(n = 22)")
    return pd.concat([sc, st], ignore_index=True)


def plot_participant_heterogeneity() -> None:
    """Show that participant-level direction is heterogeneous in both corpora."""
    data = load_participant_differences()
    order = ["SC 90%\n(n = 66)", "ST 95%\n(n = 22)"]
    fig, ax = plt.subplots(figsize=(5.7, 3.35))
    sns.violinplot(
        data=data,
        x="corpus",
        y="rate_difference",
        order=order,
        inner=None,
        cut=0,
        density_norm="width",
        color="#B9D8EB",
        linewidth=0.9,
        ax=ax,
    )
    sns.boxplot(
        data=data,
        x="corpus",
        y="rate_difference",
        order=order,
        width=0.18,
        showfliers=False,
        boxprops={"facecolor": "white", "edgecolor": "#333333"},
        medianprops={"color": "#333333", "linewidth": 1.4},
        whiskerprops={"color": "#333333"},
        capprops={"color": "#333333"},
        ax=ax,
    )
    sns.stripplot(
        data=data,
        x="corpus",
        y="rate_difference",
        order=order,
        color="#2F4B7C",
        alpha=0.62,
        jitter=0.16,
        size=3.2,
        ax=ax,
    )
    ax.axhline(0, color="#222222", lw=1.0)
    ax.set_xlabel("")
    ax.set_ylabel("Rhythmic minus isochronous events/h")
    ax.set_title("Participant-level direction varies within each corpus", loc="left", fontsize=10.5)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    _save(fig, "participant_heterogeneity")


def load_transport_points() -> pd.DataFrame:
    transported = pd.read_csv(ST_ANALYSIS / "sc_95_threshold_transport.csv")
    rematched = pd.read_csv(ST_ANALYSIS / "matched_froc_points.csv")
    transported = transported.assign(condition="Fixed SC threshold")
    rematched = rematched.assign(condition="Rematched in ST")
    return pd.concat([transported, rematched], ignore_index=True)


def plot_threshold_transport() -> None:
    """Show collision-rate and recovery changes caused by threshold transport."""
    data = load_transport_points()
    order = ["Fixed SC threshold", "Rematched in ST"]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.25))
    metrics = [
        ("false_events_per_hour", "Background detections in ST", "Events per eligible REM hour"),
        ("synthetic_recovery_fraction", "Engineering recovery in ST", "Recovered synthetic signals (%)"),
    ]
    annotation_offsets = {
        "false_events_per_hour": {
            CANDIDATE: [(0, 10), (0, -18)],
            CONTROL: [(0, -18), (0, 12)],
        },
        "synthetic_recovery_fraction": {
            CANDIDATE: [(0, -18), (0, 16)],
            CONTROL: [(0, 14), (0, -22)],
        },
    }
    for panel_index, (ax, (metric, title, ylabel)) in enumerate(zip(axes, metrics, strict=True)):
        for code_id in [CANDIDATE, CONTROL]:
            subset = data.loc[data["code_id"] == code_id].set_index("condition").loc[order]
            values = subset[metric].to_numpy(dtype=float)
            if metric == "synthetic_recovery_fraction":
                values = values * 100
            ax.plot(
                order,
                values,
                marker="o",
                ms=6,
                lw=2,
                color=CODE_COLORS[code_id],
                label=CODE_LABELS[code_id],
            )
            for point_index, (x, value) in enumerate(zip(order, values, strict=True)):
                label = f"{value:.2f}" if metric == "false_events_per_hour" else f"{value:.1f}%"
                ax.annotate(
                    label,
                    xy=(x, value),
                    xytext=annotation_offsets[metric][code_id][point_index],
                    textcoords="offset points",
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=CODE_COLORS[code_id],
                )
        ax.set_title(f"{chr(65 + panel_index)}  {title}", loc="left", fontsize=10)
        ax.set_xlabel("")
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=8)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylim(0, 19)
    axes[1].set_ylim(92.5, 97.0)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Transported thresholds change both sensitivity and apparent specificity", y=1.12, fontsize=11, fontweight="bold")
    fig.tight_layout()
    _save(fig, "threshold_transport")


def main() -> None:
    _set_style()
    plot_code_timing()
    plot_matched_contrasts()
    plot_participant_heterogeneity()
    plot_threshold_transport()
    print(f"Wrote manuscript figures to {FIGURE_DIR}")


if __name__ == "__main__":
    main()
