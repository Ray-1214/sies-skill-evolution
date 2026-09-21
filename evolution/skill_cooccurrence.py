"""
skill_cooccurrence.py — 技能多重集合共現分析 (W12)
====================================================
讀 memory/episodic/run_summary.jsonl 的 skills_used，計算 pair 的：
  - support: P(A,B) = #(同時包含 A 和 B 的 trace) / #(全部 trace)
  - lift:    P(A,B) / (P(A) · P(B))

雙閾值過濾後排序回傳，供 graph_contractor 取 top-1 進行收縮。

依賴：標準庫
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CooccurrencePair:
    skill_a: str
    skill_b: str
    support: float
    lift: float
    count: int


def analyze_cooccurrence(
    summary_path: str = "memory/episodic/run_summary.jsonl",
    min_support: float = 0.3,
    min_lift: float = 1.5,
) -> list[CooccurrencePair]:
    """
    從 run_summary.jsonl 提取技能 pair 共現。
    
    Returns:
        通過雙閾值的 CooccurrencePair list，按 (support 降序, lift 降序) 排序。
    """
    path = Path(summary_path)
    if not path.exists():
        logger.warning(f"[skill_cooccurrence] {path} not found")
        return []
    
    traces = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            skills = r.get("skills_used") or []
            if skills:
                traces.append(set(skills))
    
    n = len(traces)
    if n == 0:
        logger.info("[skill_cooccurrence] No traces with skills_used")
        return []
    
    skill_count = Counter()
    for s in traces:
        skill_count.update(s)
    
    pair_count = Counter()
    for s in traces:
        for a, b in combinations(sorted(s), 2):
            pair_count[(a, b)] += 1
    
    candidates = []
    for (a, b), cnt in pair_count.items():
        support = cnt / n
        p_a = skill_count[a] / n
        p_b = skill_count[b] / n
        denom = p_a * p_b
        lift = support / denom if denom > 0 else float("inf")
        
        if support >= min_support and lift > min_lift:
            candidates.append(CooccurrencePair(
                skill_a=a,
                skill_b=b,
                support=round(support, 4),
                lift=round(lift, 4),
                count=cnt,
            ))
    
    candidates.sort(key=lambda p: (-p.support, -p.lift))
    
    logger.info(
        f"[skill_cooccurrence] Analyzed {n} traces, "
        f"found {len(candidates)} pairs passing "
        f"(support≥{min_support}, lift>{min_lift})"
    )
    return candidates


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    summary = sys.argv[1] if len(sys.argv) > 1 else "memory/episodic/run_summary.jsonl"
    pairs = analyze_cooccurrence(summary)
    
    print(f"\n{'='*70}")
    print(f"Co-occurrence Analysis: {summary}")
    print(f"{'='*70}")
    if not pairs:
        print("(No pairs passed both thresholds)")
    else:
        print(f"{'A':35s} {'B':35s} {'support':>8s} {'lift':>6s}")
        print("-" * 90)
        for p in pairs:
            print(f"{p.skill_a:35s} {p.skill_b:35s} {p.support:>8.2f} {p.lift:>6.2f}")