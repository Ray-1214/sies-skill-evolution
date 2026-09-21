# scripts/analyze_cooccurrence.py
"""
W12 Day 2 — 離線共現分析（不寫進 graph，只 print 分布）

讀 memory/episodic/run_summary.jsonl，計算技能 pair 的：
  - support: P(A,B) = #(同時包含 A 和 B 的 trace) / #(全部 trace)
  - lift:    P(A,B) / (P(A) · P(B))

用途：W12 graph_contractor 動工前先看資料樣貌。
"""

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

SUMMARY_PATH = Path("memory/episodic/run_summary.jsonl")


def main():
    if not SUMMARY_PATH.exists():
        print(f"NOT FOUND: {SUMMARY_PATH}")
        return

    traces = []
    with open(SUMMARY_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            skills = r.get("skills_used") or []
            if skills:
                traces.append(set(skills))

    n = len(traces)
    if n == 0:
        print("No traces with skills_used.")
        return

    print(f"Total traces: {n}\n")

    # 單技能出現次數
    skill_count = Counter()
    for s in traces:
        skill_count.update(s)

    print("=== Skill frequency (P(A)) ===")
    for name, cnt in skill_count.most_common():
        print(f"  {name:40s}  P={cnt/n:.2f}  ({cnt}/{n})")

    # Pair 共現
    pair_count = Counter()
    for s in traces:
        for a, b in combinations(sorted(s), 2):
            pair_count[(a, b)] += 1

    print(f"\n=== Pair co-occurrence (n={len(pair_count)} pairs) ===")
    print(f"{'A':35s} {'B':40s} {'support':>8s} {'lift':>6s}")
    print("-" * 95)

    rows = []
    for (a, b), cnt in pair_count.items():
        support = cnt / n
        p_a = skill_count[a] / n
        p_b = skill_count[b] / n
        lift = support / (p_a * p_b) if (p_a * p_b) > 0 else float("inf")
        rows.append((a, b, support, lift, cnt))

    # 按 support 降序，再按 lift 降序
    rows.sort(key=lambda r: (-r[2], -r[3]))

    for a, b, support, lift, cnt in rows:
        flag = ""
        if support >= 0.3 and lift > 1.5:
            flag = "  ← candidate"
        print(f"{a:35s} {b:40s} {support:>8.2f} {lift:>6.2f}{flag}")

    # Summary
    candidates = [r for r in rows if r[2] >= 0.3 and r[3] > 1.5]
    print(f"\n=== Summary ===")
    print(f"Pairs with support ≥ 0.3 AND lift > 1.5: {len(candidates)}")
    if candidates:
        print("Top candidates for Φ-iii contraction:")
        for a, b, s, l, c in candidates[:5]:
            print(f"  ({a}, {b})  support={s:.2f}  lift={l:.2f}")
    else:
        print("(No pairs pass both thresholds — Φ-iii will not trigger on current data)")


if __name__ == "__main__":
    main()