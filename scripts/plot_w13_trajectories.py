#!/usr/bin/env python3
"""plot_w13_trajectories.py — W13 6 共圖軌跡 (W13 Day 5-6).

從 baseline_checkpoints / improved_checkpoints 各 5 個 json 畫 6 張 baseline vs
improved 共圖 trajectory，輸出 data/w13/figures/0[1-6]_*.png。
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt


BATCH_ENDS = [10, 20, 30, 40, 50]


def load_checkpoints(directory: Path) -> dict:
    out = {}
    for t in BATCH_ENDS:
        path = directory / f"{t}.json"
        with path.open(encoding="utf-8") as f:
            out[t] = json.load(f)
    return out


def extract_series(cps: dict, getter) -> list[float]:
    return [getter(cps[t]) for t in BATCH_ENDS]


def plot_trajectory(
    baseline_y: list[float], improved_y: list[float],
    title: str, ylabel: str, out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.plot(
        BATCH_ENDS, baseline_y,
        color="C3", linestyle="--", marker="o",
        linewidth=2, markersize=8, label="baseline (A3-v1)",
    )
    ax.plot(
        BATCH_ENDS, improved_y,
        color="C0", linestyle="-", marker="s",
        linewidth=2, markersize=8, label="improved (A3-v2)",
    )
    ax.set_title(title)
    ax.set_xlabel("Batch end (cumulative task count)")
    ax.set_ylabel(ylabel)
    ax.set_xticks(BATCH_ENDS)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(loc="best", frameon=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


FIGURES = [
    (
        "01_rho_trajectory.png",
        lambda cp: cp["rho_t"],
        "Trace Compression Ratio ρ_t (within-variant)",
        r"$\rho_t = 1 - \mathrm{avg\_steps}[t-9..t] / \mathrm{avg\_steps}[1..10]$",
    ),
    (
        "02_kappaT_trajectory.png",
        lambda cp: cp["kappa_T_t"],
        r"Graph Contraction Rate $\kappa_{T,t}$",
        r"$\kappa_{T,t}$ (macros / total ops in batch)",
    ),
    (
        "03_deltaH_trajectory.png",
        lambda cp: cp["delta_H_t_abs"],
        r"Graph Entropy Increment $|\Delta H_t|$",
        r"$|\Delta H_t|$ (nats; Shannon entropy of skill-use)",
    ),
    (
        "04_cand_rate_trajectory.png",
        lambda cp: cp["candidate_rate_t"],
        "Candidate Production Rate (cumulative)",
        "Cumulative candidates / t",
    ),
    (
        "05_avg_steps_trajectory.png",
        lambda cp: cp["raw"]["avg_steps_in_batch"],
        "Average Agent Trace Steps per Batch",
        "avg_steps in batch [t-9, t]",
    ),
    (
        "06_n_insertions_trajectory.png",
        lambda cp: cp["raw"]["n_insertions_in_batch"],
        "Skill Insertions per Batch (Φ-ii inserted_count)",
        "n_insertions_in_batch",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-dir", required=True, type=Path)
    ap.add_argument("--improved-dir", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = load_checkpoints(args.baseline_dir)
    improved = load_checkpoints(args.improved_dir)

    for fname, getter, title, ylabel in FIGURES:
        baseline_y = extract_series(baseline, getter)
        improved_y = extract_series(improved, getter)
        out = args.output_dir / fname
        plot_trajectory(baseline_y, improved_y, title, ylabel, out)
        print(f"[plot_w13_trajectories] wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
