#!/usr/bin/env python3
"""
demo/build_queries.py — 預先算好 A2 檢索與 Φ-ii 去重的範例
============================================================

demo 視窗要展示兩件事：
  1. A2 的 Activation Score 怎麼把 top-k 技能挑出來
  2. Φ-ii 的去重閘怎麼用 θdup 擋掉重複技能

兩者都要 embedding 模型。冷啟動約 7.6 秒、每次 select_skills 約 2.5 秒
（實測見 docs/DEMO_FEASIBILITY_20260913.md），所以這裡一個行程跑完全部
再存成 demo/queries.json，讓前端零後端、零網路就能展示。

只讀不改：
  - **只建一次 EmbeddingEngine**，注入給 MemoryPlanner 與 SkillValidator 共用。
  - LanceDB 只做向量查詢（`VectorStore.query`），不做任何寫入。
  - 不呼叫 AgentRunner、不觸發 Φ、不寫 run_summary.jsonl。
  - 唯一的寫入是 demo/queries.json。

用法：
    python demo/build_queries.py
    python demo/build_queries.py --out X.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

TZ_TPE = timezone(timedelta(hours=8))
CONFIG = ROOT / "config.yaml"


# ── 8 組檢索查詢（涵蓋 C1-C5 五個 cluster）────────────────────
# tstruct 只放 memory_planner._build_query_text 會用到的三個欄位：
#   requirements_restatement / subtasks[].description / domain
RETRIEVAL_QUERIES = [
    {
        "query": "read a csv file and convert it to json, print the row count",
        "cluster_hint": "C2",
        "domain": ["data", "engineering"],
        "subtasks": [
            "Read the CSV file from an absolute path",
            "Convert each row into a dictionary",
            "Serialize the list to JSON and print the row count",
        ],
    },
    {
        "query": "validate every record has required fields, split valid and invalid",
        "cluster_hint": "C2",
        "domain": ["data", "engineering"],
        "subtasks": [
            "Load the parsed records from disk",
            "Check each record against the required field schema",
            "Write valid and invalid records to separate output files",
        ],
    },
    {
        "query": "implement a recursive algorithm with memoization and test it",
        "cluster_hint": "C1",
        "domain": ["software-engineering"],
        "subtasks": [
            "Implement the recursive function with a memoization cache",
            "Write a test harness covering base cases and edge cases",
            "Verify results against known expected values",
        ],
    },
    {
        "query": "extract all email addresses from a text file using regex",
        "cluster_hint": "C5",
        "domain": ["data", "software-engineering"],
        "subtasks": [
            "Read the raw text file",
            "Apply a regular expression to find every email address",
            "Write the deduplicated matches to an output file",
        ],
    },
    {
        "query": "list running python processes and filter by name",
        "cluster_hint": "C4",
        "domain": ["engineering", "automation"],
        "subtasks": [
            "Query the operating system for the running process table",
            "Filter the entries whose command matches the target name",
            "Print the matching process ids in a fixed format",
        ],
    },
    {
        "query": "merge two datasets on a common key and generate a summary report",
        "cluster_hint": "C3",
        "domain": ["data", "analysis"],
        "subtasks": [
            "Load both datasets from their absolute paths",
            "Join the rows on the shared key column",
            "Aggregate the merged rows and write a summary report",
        ],
    },
    {
        "query": "implement n-queens with backtracking and verify the solution",
        "cluster_hint": "C3",
        "domain": ["software-engineering"],
        "subtasks": [
            "Implement the backtracking search over board placements",
            "Add constraint validation for rows, columns and diagonals",
            "Verify each returned board is a legal solution",
        ],
    },
    {
        "query": "normalize inconsistent date formats across a data file",
        "cluster_hint": "C5",
        "domain": ["data", "analysis"],
        "subtasks": [
            "Read the data file containing mixed date representations",
            "Detect and parse each of the inconsistent formats",
            "Rewrite every value into one canonical format",
        ],
    },
]


# ── 去重候選池 ────────────────────────────────────────────────
# 先全部量一次，再依 sim 值挑出 demo 要的 4 組（見 pick_dedup_cases）。
# case 1 是真實案例：evolution_log.jsonl 最後一筆把它以 sim=0.9169 擋下。
DEDUP_POOL = [
    {
        "id": "real_rejected",
        "label": "真實案例：長跑最後一筆被擋下的候選",
        "name": "json-field-normalization-pipeline",
        "description": (
            "Read a JSON dataset, apply string cleaning transformations "
            "(like case normalization and whitespace stripping) to specific fields, "
            "and persist the result to a new file."
        ),
        "strategy_steps": [
            "Define absolute paths for input and output to ensure environment consistency",
            "Load the structured data using a standard parser",
            "Iterate through the collection and apply string normalization (lowercase, strip) to target keys",
            "Write the modified collection to the specified output destination",
        ],
        "note": "原文取自 skills/candidates/json-field-normalization-pipeline/SKILL.md",
    },
    {
        "id": "unrelated_cnn",
        "label": "完全不相關的領域",
        "name": "convolutional-network-training",
        "description": (
            "Train a convolutional neural network on an image dataset, "
            "tune the learning rate schedule, and report top-1 accuracy per epoch."
        ),
        "strategy_steps": [
            "Assemble the labelled image dataset and split it into train and validation folds",
            "Define the convolutional architecture and the optimiser",
            "Train for a fixed number of epochs and log validation accuracy",
        ],
        "note": "與既有技能庫（資料處理 / 演算法實作）沒有語意重疊",
    },
    {
        "id": "medium_shell",
        "label": "中等相似：同樣碰檔案，但手法與目的不同",
        "name": "shell-log-tail-monitor",
        "description": (
            "Watch a growing log file from the shell and print new lines that match "
            "a severity keyword as they appear."
        ),
        "strategy_steps": [
            "Open the log file and seek to the end",
            "Poll for appended lines at a fixed interval",
            "Print the lines whose severity field matches the requested level",
        ],
        "note": "檔案讀取語意與資料管線有部分重疊，但任務型態不同",
    },
    {
        "id": "medium_plot",
        "label": "中等相似：資料讀入相同，產出不同",
        "name": "dataset-histogram-plotting",
        "description": (
            "Load a numeric dataset from disk and render a histogram image "
            "showing the distribution of one selected column."
        ),
        "strategy_steps": [
            "Read the dataset from the given absolute path",
            "Select the target numeric column and compute the bin counts",
            "Render the histogram and save it as an image file",
        ],
        "note": "前半段（讀資料）與既有技能重疊，後半段（繪圖）沒有對應技能",
    },
    {
        "id": "boundary_csv_json",
        "label": "邊界案例：換句話說的既有技能",
        "name": "tabular-to-document-converter",
        "description": (
            "Take a tabular data file, turn every row into a document-style record, "
            "and store the resulting collection as a JSON file on disk."
        ),
        "strategy_steps": [
            "Resolve the absolute input and output paths",
            "Parse the tabular file row by row",
            "Emit the rows as a JSON document collection and write it out",
        ],
        "note": "刻意用不同措辭描述既有的 csv→json 管線，測試語意去重而非字面比對",
    },
    {
        "id": "boundary_validate",
        "label": "邊界案例：既有技能加一個額外步驟",
        "name": "schema-validation-with-audit-trail",
        "description": (
            "Validate records against a required-field schema, split them into valid "
            "and invalid outputs, and additionally append a per-record audit trail entry."
        ),
        "strategy_steps": [
            "Load the records and the required field list",
            "Partition the records by whether they satisfy the schema",
            "Write both partitions plus an audit log describing each rejection",
        ],
        "note": "在既有 schema 驗證技能上多一個 audit trail 步驟",
    },
]


def build_tstruct(spec: dict, idx: int) -> dict:
    """組出 memory_planner.plan / select_skills 需要的最小 tstruct。"""
    return {
        "task_id": f"T-demo-q{idx:02d}",
        "requirements_restatement": spec["query"],
        "domain": spec["domain"],
        "subtasks": [
            {"subtask_id": f"ST-demo-{idx:02d}-{i}", "description": d}
            for i, d in enumerate(spec["subtasks"], 1)
        ],
    }


def pick_dedup_cases(measured: list[dict], theta: float) -> list[dict]:
    """從量過的候選池挑 demo 要的 4 組。

    1. real_rejected   —— 真實被擋案例
    2. 中等相似         —— sim 落在 [0.5, theta) 且最靠近區間中點
    3. unrelated_cnn   —— 完全不相關
    4. 邊界案例         —— 剩下的當中 |sim - theta| 最小的
    """
    by_id = {m["id"]: m for m in measured}
    chosen = [by_id["real_rejected"]]
    used = {"real_rejected", "unrelated_cnn"}

    mid_band = [m for m in measured
                if m["id"] not in used and 0.5 <= m["sim"] < theta]
    if mid_band:
        target = (0.5 + theta) / 2
        pick = min(mid_band, key=lambda m: abs(m["sim"] - target))
    else:  # 沒有落在區間內就退而求其次：取 sim 最接近 0.625 的
        pool = [m for m in measured if m["id"] not in used]
        pick = min(pool, key=lambda m: abs(m["sim"] - 0.625))
    chosen.append(pick)
    used.add(pick["id"])

    chosen.append(by_id["unrelated_cnn"])

    rest = [m for m in measured if m["id"] not in used]
    if rest:
        chosen.append(min(rest, key=lambda m: abs(m["sim"] - theta)))
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "queries.json"))
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    planner_cfg = cfg.get("planner", {})
    theta_dup = cfg.get("skill_validator", {}).get("theta_dup", 0.85)

    t_proc = time.time()
    timings: dict[str, float] = {}

    # ── 只建一次 EmbeddingEngine + VectorStore ────────────────
    print("[build_queries] 載入 EmbeddingEngine（冷啟動，只做一次）...")
    t0 = time.time()
    from embedding_engine import EmbeddingEngine
    from vector_store import VectorStore
    engine = EmbeddingEngine(str(CONFIG))
    store = VectorStore(str(CONFIG))
    timings["cold_start"] = time.time() - t0
    print(f"[build_queries]   冷啟動 {timings['cold_start']:.2f}s "
          f"(device={engine.config['device']}, dim={engine.model.get_sentence_embedding_dimension()})")

    # 同一個 engine/store 注入給兩個消費者，不重複載模型
    from memory_planner import MemoryPlanner
    from agents.skill_validator import SkillValidator
    from agents.base_extractor import CandidateSkill

    t0 = time.time()
    planner = MemoryPlanner(str(CONFIG), embedding_engine=engine, vector_store=store)
    timings["planner_ctor"] = time.time() - t0
    print(f"[build_queries]   MemoryPlanner 建構 {timings['planner_ctor']:.2f}s "
          f"(graph {planner.graph.number_of_nodes()} nodes / "
          f"{planner.graph.number_of_edges()} edges)")

    validator = SkillValidator(str(CONFIG), embedding_engine=engine, vector_store=store)
    print(f"[build_queries]   SkillValidator θdup={validator.theta_dup}")

    # ── (a) 8 組檢索 ──────────────────────────────────────────
    print(f"\n[build_queries] === (a) 檢索範例 {len(RETRIEVAL_QUERIES)} 組 ===")
    retrieval = []
    t_retr = time.time()
    for i, spec in enumerate(RETRIEVAL_QUERIES, 1):
        tstruct = build_tstruct(spec, i)
        t0 = time.time()
        selected = planner.select_skills(tstruct)
        dt = time.time() - t0
        retrieval.append({
            "query": spec["query"],
            "cluster_hint": spec["cluster_hint"],
            "domain": spec["domain"],
            "subtasks": [st["description"] for st in tstruct["subtasks"]],
            "elapsed_seconds": round(dt, 3),
            "results": [{
                "name": s["name"],
                "activation_score": s["activation_score"],
                "sim": s["sim"],
                "utility": s["utility"],
                "centrality": s["centrality"],
                "l2_distance": s["l2_distance"],
            } for s in selected],
        })
        top = selected[0]["name"] if selected else "(none)"
        print(f"  [{i}/{len(RETRIEVAL_QUERIES)}] {dt:5.2f}s  "
              f"{len(selected)} skills  top={top[:46]}")
        print(f"        query: {spec['query'][:66]}")
    timings["retrieval_total"] = time.time() - t_retr

    # ── (b) 去重 ──────────────────────────────────────────────
    print(f"\n[build_queries] === (b) 去重範例（候選池 {len(DEDUP_POOL)} 組，挑 4 組）===")
    measured = []
    t_dedup = time.time()
    for spec in DEDUP_POOL:
        cand = CandidateSkill(
            name=spec["name"],
            description=spec["description"],
            type="general",
            domain=["software-engineering"],
            invocation_condition="demo probe — 不會被插入技能庫",
            termination_condition="demo probe — 不會被插入技能庫",
            strategy_steps=spec["strategy_steps"],
            confidence=0.8,
            source_task_id="T-demo-dedup",
        )
        embed_text = SkillValidator._candidate_to_embed_text(cand)
        t0 = time.time()
        passed, reason, closest, sim = validator._check_dedup(cand)
        dt = time.time() - t0
        measured.append({
            "id": spec["id"],
            "label": spec["label"],
            "query": spec["description"],
            "candidate_name": spec["name"],
            "embed_text": embed_text,
            "closest": closest,
            "sim": sim if sim is not None else 0.0,
            "passed": passed,
            "reason": reason,
            "note": spec["note"],
            "elapsed_seconds": round(dt, 3),
        })
        mark = "PASS" if passed else "REJECT"
        print(f"  {dt:5.2f}s  sim={sim if sim is not None else float('nan'):.4f}  "
              f"{mark:6s}  {spec['id']:22s} → {closest}")
    timings["dedup_total"] = time.time() - t_dedup

    chosen = pick_dedup_cases(measured, theta_dup)
    print(f"\n[build_queries]   挑出 4 組: {[c['id'] for c in chosen]}")

    dedup = [{
        "case_id": m["id"],
        "label": m["label"],
        "query": m["query"],
        "candidate_name": m["candidate_name"],
        "embed_text": m["embed_text"],
        "closest": m["closest"],
        "sim": round(m["sim"], 4),
        "verdict": "rejected" if not m["passed"] else "accepted",
        "threshold": theta_dup,
        "above_threshold": bool(m["sim"] > theta_dup),
        "reason": m["reason"],
        "note": m["note"],
    } for m in chosen]

    # ── 輸出 ──────────────────────────────────────────────────
    timings["total"] = time.time() - t_proc
    data = {
        "generated_at": datetime.now(TZ_TPE).isoformat(),
        "config": {
            "top_k": planner_cfg.get("top_k", 6),
            "lambda1": planner_cfg.get("lambda1", 0.5),
            "lambda2": planner_cfg.get("lambda2", 0.3),
            "lambda3": planner_cfg.get("lambda3", 0.2),
            "theta_dup": theta_dup,
            "sim_formula": "1 - d/2",
        },
        "retrieval": retrieval,
        "dedup": dedup,
        "dedup_pool_measured": [{
            "case_id": m["id"], "closest": m["closest"],
            "sim": round(m["sim"], 4), "verdict": "rejected" if not m["passed"] else "accepted",
        } for m in measured],
        "timings_seconds": {k: round(v, 3) for k, v in timings.items()},
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[build_queries] 已寫出 {out}")
    print(f"[build_queries] 大小 = {out.stat().st_size:,} bytes")
    print("\n[build_queries] === 耗時 ===")
    print(f"  冷啟動 (EmbeddingEngine + VectorStore) ... {timings['cold_start']:7.2f} s")
    print(f"  MemoryPlanner 建構 ...................... {timings['planner_ctor']:7.2f} s")
    print(f"  檢索 {len(retrieval)} 組合計 ...................... {timings['retrieval_total']:7.2f} s "
          f"(平均 {timings['retrieval_total']/len(retrieval):.2f} s/組)")
    print(f"  去重 {len(measured)} 組合計 ...................... {timings['dedup_total']:7.2f} s "
          f"(平均 {timings['dedup_total']/len(measured):.2f} s/組)")
    print(f"  ------------------------------------------------")
    print(f"  總耗時 .................................. {timings['total']:7.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
