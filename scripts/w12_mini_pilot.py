"""
scripts/w12_mini_pilot.py — W12 末尾 mini pilot 一鍵執行
==========================================================
Phase 1: 跑前 snapshot
Phase 2: 跑 12 題（runner.run_batch）
Phase 3: 觸發 Φ（subprocess: python evolution/evolution_operator.py）
Phase 4: 跑後診斷 + LanceDB 一致性檢查 + 共現分析

用法（從專案根目錄）：
    python scripts/w12_mini_pilot.py

Tee 自動寫入 scripts/mini_pilot_log_<timestamp>.txt 供事後回看。
所有 phase 用 try/except 包裹，單 phase 失敗不影響後續診斷。
"""

import json
import os
import statistics
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

# 切到專案根目錄（讓相對路徑 config.yaml / skills/ / memory/ 都對得上）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────
# 12 題 task list（Day 8 mini pilot）
# ──────────────────────────────────────────────────────────

TASKS = [
    'Write a Python function that reads a text file and returns the line count. Save sample input to /tmp first, then verify with 3 test cases (empty, single line, multi-line).',
    'Create a function that writes a list of dicts to a JSON file and reads it back. Verify round-trip equality with assertions.',
    'Implement a function that counts unique words in a text file (case-insensitive). Test with a sample file you create yourself.',
    'Write a function to merge two text files line by line into a third file. Test with files of different lengths.',
    'Implement bubble sort in Python without using sorted() or list.sort(). Verify with 4 test cases including empty list and reversed list.',
    'Write a function to find the second largest unique number in a list. Test with various inputs including duplicates.',
    'Implement binary search and verify with sorted lists of size 1, 5, and 100.',
    'Write a function to check if a string is a palindrome ignoring case and spaces. Test with edge cases.',
    'Write a function that returns the first sentence of a paragraph (split by . ! ?). Verify with 3 multi-sentence inputs.',
    'Create a function that capitalizes every other word in a sentence (case-preserving). Verify with one example.',
    'Calculate the factorial of 12 using recursion. Print the result.',
    'Compute GCD of 48 and 36 using Euclidean algorithm. Print intermediate steps.',
]


# ──────────────────────────────────────────────────────────
# Tee（同時寫 stdout/stderr 與 log file）
# ──────────────────────────────────────────────────────────

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
            st.flush()

    def flush(self):
        for st in self.streams:
            st.flush()


# ──────────────────────────────────────────────────────────
# 圖譜 snapshot 工具
# ──────────────────────────────────────────────────────────

def take_snapshot(label):
    """讀 GRAPH_INDEX.md 並印出統計。回傳 dict 供 phase 4 算 delta。"""
    from parse_graph_index import parse_graph_index, build_graph
    parsed = parse_graph_index('skills/GRAPH_INDEX.md')
    G = build_graph(parsed)

    utils = [a.get('utility', 0) for _, a in G.nodes(data=True)]
    freqs = [a.get('frequency', 0) for _, a in G.nodes(data=True)]
    tiers = Counter(a.get('tier', '?') for _, a in G.nodes(data=True))
    macros = [n for n in G.nodes if n.startswith('macro-')]

    print(f'\n--- {label} ---')
    print(f'  Total nodes: {len(utils)}')
    print(f'  Tier distribution: {dict(tiers)}')

    if utils:
        u_mean = sum(utils) / len(utils)
        u_std = statistics.stdev(utils) if len(utils) > 1 else 0.0
        print(f'  U  mean={u_mean:.4f}  stdev={u_std:.4f}  '
              f'max={max(utils):.4f}  min={min(utils):.4f}')
        print(f'  U > 0.65 (active 區): {sum(1 for u in utils if u > 0.65)}')
        print(f'  U < 0.25 (archive 區): {sum(1 for u in utils if u < 0.25)}')
    else:
        u_mean = u_std = 0.0

    if freqs:
        f0 = sum(1 for f in freqs if f == 0)
        f12 = sum(1 for f in freqs if 1 <= f <= 2)
        f3p = sum(1 for f in freqs if f >= 3)
        print(f'  Frequency: f=0:{f0}, f=1-2:{f12}, f≥3:{f3p}')

    if macros:
        print(f'  Macro-skills: {len(macros)} → {macros}')
    else:
        print(f'  Macro-skills: 0')

    return {
        'graph': G,
        'n_nodes': len(utils),
        'u_mean': u_mean,
        'u_std': u_std,
        'tiers': dict(tiers),
        'macros': macros,
    }


# ──────────────────────────────────────────────────────────
# Phase 1: 跑前 snapshot
# ──────────────────────────────────────────────────────────

def phase_1():
    print('\n' + '=' * 70)
    print('PHASE 1: PRE-PILOT SNAPSHOT')
    print('=' * 70)

    # run_summary 行數
    summary_path = PROJECT_ROOT / 'memory/episodic/run_summary.jsonl'
    n_lines = 0
    if summary_path.exists():
        n_lines = sum(1 for _ in open(summary_path, encoding='utf-8'))
    print(f'  run_summary.jsonl: {n_lines} lines (pre-pilot)')

    return take_snapshot('Pre-pilot graph state')


# ──────────────────────────────────────────────────────────
# Phase 2: 12 題 batch
# ──────────────────────────────────────────────────────────

def phase_2():
    print('\n' + '=' * 70)
    print(f'PHASE 2: RUN {len(TASKS)} TASKS')
    print('=' * 70)
    print(f'Estimated time: ~{len(TASKS) * 75 / 60:.1f} minutes (75s/task baseline)\n')

    from agents.agent_runner import AgentRunner
    runner = AgentRunner('config.yaml')

    t0 = time.time()
    results = runner.run_batch(TASKS)
    elapsed = time.time() - t0

    print(f'\n[batch elapsed: {elapsed:.1f}s = {elapsed/60:.1f}min, '
          f'avg {elapsed/len(TASKS):.1f}s/task]\n')

    print('--- AgentRunner.summarize_results ---')
    try:
        summary = AgentRunner.summarize_results(results)
        print(summary)
    except Exception as e:
        print(f'  summarize_results failed: {e}')

    # Per-task quick view（即使 summarize 失敗也能看）
    print('\n--- Per-task outcomes ---')
    for i, r in enumerate(results, 1):
        success = getattr(r, 'execution_success', '?')
        steps = '?'
        skills = []
        if hasattr(r, 'execution_trace') and r.execution_trace:
            steps = len(r.execution_trace) if hasattr(r.execution_trace, '__len__') else '?'
        if hasattr(r, 'evaluation') and r.evaluation:
            skills = getattr(r, 'skills_used', [])
        print(f'  T{i:02d} success={success} steps={steps}')

    return results


# ──────────────────────────────────────────────────────────
# Phase 3: 觸發 Φ
# ──────────────────────────────────────────────────────────

def phase_3():
    print('\n' + '=' * 70)
    print('PHASE 3: TRIGGER Φ (evolution_operator)')
    print('=' * 70)

    cmd = [sys.executable, 'evolution/evolution_operator.py']
    print(f'Running: {" ".join(cmd)}\n')

    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT),
        capture_output=True, text=True
    )
    elapsed = time.time() - t0

    print('--- evolution_operator stdout ---')
    print(proc.stdout if proc.stdout else '(empty)')

    if proc.stderr:
        print('\n--- evolution_operator stderr ---')
        print(proc.stderr)

    print(f'\n[Φ elapsed: {elapsed:.1f}s, return code: {proc.returncode}]')


# ──────────────────────────────────────────────────────────
# Phase 4: 跑後診斷
# ──────────────────────────────────────────────────────────

def phase_4(pre):
    print('\n' + '=' * 70)
    print('PHASE 4: POST-PILOT DIAGNOSTICS')
    print('=' * 70)

    post = take_snapshot('Post-pilot graph state')
    G = post['graph']

    # Delta vs pre
    print('\n--- Delta vs pre-pilot ---')
    print(f'  Nodes:   {pre["n_nodes"]} → {post["n_nodes"]} '
          f'(Δ={post["n_nodes"] - pre["n_nodes"]:+d})')
    print(f'  U mean:  {pre["u_mean"]:.4f} → {post["u_mean"]:.4f} '
          f'(Δ={post["u_mean"] - pre["u_mean"]:+.4f})')
    print(f'  U stdev: {pre["u_std"]:.4f} → {post["u_std"]:.4f} '
          f'(Δ={post["u_std"] - pre["u_std"]:+.4f})')
    print(f'  Macros:  {len(pre["macros"])} → {len(post["macros"])} '
          f'(Δ={len(post["macros"]) - len(pre["macros"]):+d})')
    print(f'  Tiers:   {pre["tiers"]} → {post["tiers"]}')

    # Top / bottom by utility
    ranked = sorted(
        [(n, a.get('utility', 0), a.get('frequency', 0), a.get('tier', '?'))
         for n, a in G.nodes(data=True)],
        key=lambda x: -x[1]
    )

    print('\n--- Top 10 by utility ---')
    for name, u, f, t in ranked[:10]:
        print(f'  {name:55s} U={u:.4f} f={f:>2d} tier={t}')

    print('\n--- Bottom 5 by utility ---')
    for name, u, f, t in ranked[-5:]:
        print(f'  {name:55s} U={u:.4f} f={f:>2d} tier={t}')

    # 共現分析（嚴格 + 寬鬆兩套）
    print('\n--- Cooccurrence analysis ---')
    try:
        from evolution.skill_cooccurrence import analyze_cooccurrence

        strict = analyze_cooccurrence(
            'memory/episodic/run_summary.jsonl',
            min_support=0.3, min_lift=1.5,
        )
        diag = analyze_cooccurrence(
            'memory/episodic/run_summary.jsonl',
            min_support=0.1, min_lift=1.0,
        )
        print(f'  Strict     (Φ-iii 觸發: support≥0.3 AND lift>1.5): '
              f'{len(strict)} pairs')
        print(f'  Diagnostic (寬鬆: support≥0.1 AND lift>1.0):       '
              f'{len(diag)} pairs')

        if diag:
            print('\n  Diagnostic top 10 (按 support 降序、lift 降序):')
            for p in diag[:10]:
                marker = '★' if (p.support >= 0.3 and p.lift > 1.5) else ' '
                print(f'  {marker} ({p.skill_a} × {p.skill_b}) '
                      f'support={p.support:.2f} lift={p.lift:.2f} '
                      f'count={p.count}')

            by_lift = sorted(diag, key=lambda p: -p.lift)
            print('\n  Diagnostic top 5 by LIFT (最強關聯訊號):')
            for p in by_lift[:5]:
                print(f'    ({p.skill_a} × {p.skill_b}) '
                      f'lift={p.lift:.2f} support={p.support:.2f}')
    except Exception as e:
        print(f'  Cooccurrence analysis failed: {e}')
        traceback.print_exc()

    # LanceDB consistency
    print('\n--- LanceDB ↔ GRAPH consistency ---')
    try:
        from vector_store import VectorStore
        vs = VectorStore('config.yaml')
        ldb_count = vs.count()
        graph_count = G.number_of_nodes()
        print(f'  LanceDB count: {ldb_count}')
        print(f'  GRAPH nodes:   {graph_count}')
        if ldb_count == graph_count:
            print(f'  ✓ Consistent')
        else:
            print(f'  ✗ MISMATCH (Δ={ldb_count - graph_count:+d}) — TD-13 風險，請檢查')
    except Exception as e:
        print(f'  LanceDB check failed: {e}')
        traceback.print_exc()

    # run_summary 行數
    print('\n--- run_summary.jsonl line count ---')
    summary_path = PROJECT_ROOT / 'memory/episodic/run_summary.jsonl'
    if summary_path.exists():
        n_lines = sum(1 for _ in open(summary_path, encoding='utf-8'))
        print(f'  {summary_path.name}: {n_lines} lines '
              f'(pre 應為 11，post 預期 23 = 11 + 12)')

    # Evolution log 最新一筆
    print('\n--- Latest evolution_log.jsonl entry ---')
    log_path = PROJECT_ROOT / 'memory/episodic/evolution_log.jsonl'
    if log_path.exists():
        lines = log_path.read_text(encoding='utf-8').strip().split('\n')
        if lines and lines[-1]:
            try:
                last = json.loads(lines[-1])
                for k, v in last.items():
                    print(f'  {k}: {v}')
            except json.JSONDecodeError as e:
                print(f'  Could not parse last line: {e}')


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def main():
    # Tee stdout/stderr → log file
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = PROJECT_ROOT / f'scripts/mini_pilot_log_{ts}.txt'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)

    overall_t0 = time.time()

    print('=' * 70)
    print(f'W12 mini pilot — started {datetime.now().isoformat()}')
    print(f'Project root: {PROJECT_ROOT}')
    print(f'Log file:     {log_path}')
    print('=' * 70)

    pre = None
    try:
        pre = phase_1()
    except Exception as e:
        print(f'\n[ERROR] Phase 1 failed: {e}')
        traceback.print_exc()

    try:
        phase_2()
    except Exception as e:
        print(f'\n[ERROR] Phase 2 failed: {e}')
        traceback.print_exc()
        # 即使 phase 2 部分失敗，後續診斷仍有價值（部分 trace 已寫入）

    try:
        phase_3()
    except Exception as e:
        print(f'\n[ERROR] Phase 3 failed: {e}')
        traceback.print_exc()

    if pre is not None:
        try:
            phase_4(pre)
        except Exception as e:
            print(f'\n[ERROR] Phase 4 failed: {e}')
            traceback.print_exc()
    else:
        print('\n[SKIP] Phase 4 skipped because Phase 1 had no baseline')

    overall_elapsed = time.time() - overall_t0
    print('\n' + '=' * 70)
    print(f'Total elapsed: {overall_elapsed:.1f}s = {overall_elapsed/60:.1f} min')
    print(f'Log saved to:  {log_path}')
    print('=' * 70)

    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    log_file.close()


if __name__ == '__main__':
    main()