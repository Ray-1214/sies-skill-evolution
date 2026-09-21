#!/usr/bin/env python3
"""build_w13_metrics.py — W13 對照實驗 incremental metrics builder (W13 Day 5-6).

讀 run_summary.jsonl + evolution_log.jsonl，產 5 checkpoint × 2 variant = 10 JSON。
4 指標：ρ_t, κT_t, |ΔH_t|, candidate_rate_t（cumulative）。

輸出：
  data/w13/{variant}_checkpoints/{10,20,30,40,50}.json

對照 plan_v4_10_1.md §7.6 schema；圖表由後續 plotting script 讀本目錄產出。
"""

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def sanity_check_variant(variant: str, tasks: list[dict], w13_evol: list[dict]) -> None:
    """Abort with descriptive error if W13 slices look wrong."""
    if len(tasks) != 50:
        sys.exit(
            f"[build_w13_metrics] ABORT {variant}: expected last 50 tasks, "
            f"got {len(tasks)}"
        )
    if len(w13_evol) != 5:
        sys.exit(
            f"[build_w13_metrics] ABORT {variant}: expected last 5 evolution "
            f"entries, got {len(w13_evol)}"
        )
    for i, ev in enumerate(w13_evol):
        triggered_by = ev.get("triggered_by", [])
        if "force" not in triggered_by:
            sys.exit(
                f"[build_w13_metrics] ABORT {variant}: w13_evol[{i}] "
                f"triggered_by={triggered_by} does not contain 'force' — "
                f"slice may not be a real W13 batch"
            )


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------

def shannon_entropy_natural(counter: Counter) -> float:
    """H(P) = -Σ p_i ln(p_i) on a counter's normalized distribution; 0 if empty."""
    total = sum(counter.values())
    if total == 0:
        return 0.0
    return -sum(
        (c / total) * math.log(c / total)
        for c in counter.values()
        if c > 0
    )


def mean_steps(tasks: list[dict]) -> float:
    if not tasks:
        return 0.0
    return sum(t.get("total_steps", 0) for t in tasks) / len(tasks)


# ---------------------------------------------------------------------------
# Per-variant metric build
# ---------------------------------------------------------------------------

@dataclass
class CheckpointMetrics:
    variant: str
    batch_end: int
    rho_t: float
    kappa_T_t: float
    delta_H_t_abs: float
    candidate_rate_t: float
    raw: dict


def build_variant(
    variant: str, run_summary_path: Path, evolution_log_path: Path,
) -> list[CheckpointMetrics]:
    all_tasks = load_jsonl(run_summary_path)
    all_evol = load_jsonl(evolution_log_path)
    tasks = all_tasks[-50:]
    w13_evol = all_evol[-5:]
    sanity_check_variant(variant, tasks, w13_evol)

    # Reference batch (tasks 1-10) for ρ_t baseline
    ref_avg = mean_steps(tasks[0:10])

    cum_counter: Counter = Counter()
    cum_candidates = 0
    H_prev = 0.0  # H_0 = 0 (empty distribution)
    results: list[CheckpointMetrics] = []

    for batch_idx in range(5):
        batch_end = (batch_idx + 1) * 10
        batch_tasks = tasks[batch_idx * 10 : batch_end]
        evol = w13_evol[batch_idx]

        # (1) ρ_t — compression ratio vs reference batch
        batch_avg = mean_steps(batch_tasks)
        if ref_avg > 0:
            rho_t = 1.0 - (batch_avg / ref_avg)
        else:
            rho_t = 0.0

        # (2) κT_t — macro share of total Φ ops in this batch
        macros = evol.get("macro_skills_created", 0)
        n_inserted = evol.get("inserted_count", 0)
        n_rejected = evol.get("rejected_count", 0)
        n_tier_mig = evol.get("tier_migrations", 0)
        ops_total = n_inserted + macros + n_tier_mig + n_rejected
        kappa_T_t = (macros / ops_total) if ops_total > 0 else 0.0

        # (3) |ΔH_t| — change in cumulative skill-use Shannon entropy
        for task in batch_tasks:
            for skill in task.get("skills_used", []):
                cum_counter[skill] += 1
        H_t = shannon_entropy_natural(cum_counter)
        delta_H_t_abs = abs(H_t - H_prev)

        # (4) candidate_rate_t (cumulative)
        cands_in_batch = evol.get("candidates_found", 0)
        cum_candidates += cands_in_batch
        candidate_rate_t = cum_candidates / batch_end if batch_end > 0 else 0.0

        failed_in_batch = sum(1 for t in batch_tasks if not t.get("success"))

        raw = {
            "avg_steps_in_batch": batch_avg,
            "avg_steps_reference_batch1": ref_avg,
            "n_insertions_in_batch": n_inserted,
            "n_rejected_in_batch": n_rejected,
            "n_macros_in_batch": macros,
            "n_tier_migrations_in_batch": n_tier_mig,
            "candidates_found_in_batch": cands_in_batch,
            "cumulative_candidates": cum_candidates,
            "graph_entropy_H_t": H_t,
            "graph_entropy_H_t_minus_10": H_prev,
            "graph_nodes_before": evol.get("graph_nodes_before"),
            "graph_nodes_after": evol.get("graph_nodes_after"),
            "failed_tasks_in_batch": failed_in_batch,
        }

        results.append(CheckpointMetrics(
            variant=variant,
            batch_end=batch_end,
            rho_t=rho_t,
            kappa_T_t=kappa_T_t,
            delta_H_t_abs=delta_H_t_abs,
            candidate_rate_t=candidate_rate_t,
            raw=raw,
        ))

        H_prev = H_t

    return results


def write_checkpoints(metrics: list[CheckpointMetrics], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for m in metrics:
        out_path = output_dir / f"{m.batch_end}.json"
        payload = {
            "variant": m.variant,
            "batch_end": m.batch_end,
            "rho_t": m.rho_t,
            "kappa_T_t": m.kappa_T_t,
            "delta_H_t_abs": m.delta_H_t_abs,
            "candidate_rate_t": m.candidate_rate_t,
            "raw": m.raw,
        }
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def print_trajectory(variant: str, metrics: list[CheckpointMetrics]) -> None:
    print(f"[build_w13_metrics] {variant} trajectory:", file=sys.stderr)
    for m in metrics:
        print(
            f"  t={m.batch_end:<2d}  "
            f"ρ={m.rho_t:+.3f}  κT={m.kappa_T_t:.3f}  "
            f"|ΔH|={m.delta_H_t_abs:.3f}  "
            f"cand_rate={m.candidate_rate_t:.2f}  "
            f"(steps {m.raw['avg_steps_in_batch']:.1f}, "
            f"+{m.raw['n_macros_in_batch']} macros, "
            f"+{m.raw['n_insertions_in_batch']} inserted, "
            f"-{m.raw['n_rejected_in_batch']} rejected)",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-run-summary", required=True, type=Path)
    ap.add_argument("--baseline-evolution-log", required=True, type=Path)
    ap.add_argument("--improved-run-summary", required=True, type=Path)
    ap.add_argument("--improved-evolution-log", required=True, type=Path)
    ap.add_argument(
        "--output-dir", required=True, type=Path,
        help="Parent dir; writes {variant}_checkpoints/{batch_end}.json",
    )
    args = ap.parse_args()

    baseline_metrics = build_variant(
        "baseline", args.baseline_run_summary, args.baseline_evolution_log,
    )
    improved_metrics = build_variant(
        "improved", args.improved_run_summary, args.improved_evolution_log,
    )

    write_checkpoints(baseline_metrics, args.output_dir / "baseline_checkpoints")
    write_checkpoints(improved_metrics, args.output_dir / "improved_checkpoints")

    print_trajectory("baseline", baseline_metrics)
    print_trajectory("improved", improved_metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
