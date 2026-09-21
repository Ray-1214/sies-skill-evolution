#!/usr/bin/env python3
"""
demo/build_data.py — demo 視窗的靜態資料包產生器
================================================

把既有的圖 / 執行 / 演化 / 體檢資料匯出成單一個 demo/data.json，
讓 demo 前端不必在展示當下碰 LanceDB、LLM server 或 Docker。

原則：
  - **只讀不改**任何來源檔。本腳本唯一的寫入是 demo/data.json。
  - **不載入 EmbeddingEngine、不建 LLMClient**（兩者都是重成本且 demo 不需要）。
  - LanceDB 只用來取 count_rows()，不做任何向量查詢。

來源：
  skills/GRAPH_INDEX.md                               圖（Meta / Nodes / Edges）
  skills/{active,cold,archive}/**/SKILL.md            技能全文
  memory/episodic/evolution_log.jsonl                 Φ 演化記錄
  data/w16/runs/<run_id>/manifest.json                長跑設定
  data/w16/runs/<run_id>/attempts.jsonl               長跑 50 筆 attempt
  data/w16/runs/<run_id>/checkpoints/0{10..50}.json   5 個 checkpoint
  scripts/sies_doctor.py --json                       體檢輸出（子行程 stdout）

用法：
    python demo/build_data.py                 # 寫到 demo/data.json
    python demo/build_data.py --out X.json    # 換輸出路徑
    python demo/build_data.py --run <run_id>  # 換長跑
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TZ_TPE = timezone(timedelta(hours=8))

DEFAULT_RUN_ID = "w16-pipeline-20260908T014100"

GRAPH_INDEX = ROOT / "skills" / "GRAPH_INDEX.md"
EVOLUTION_LOG = ROOT / "memory" / "episodic" / "evolution_log.jsonl"
RUN_SUMMARY = ROOT / "memory" / "episodic" / "run_summary.jsonl"
DOCTOR = ROOT / "scripts" / "sies_doctor.py"
CONFIG = ROOT / "config.yaml"


# ── manifest.config 的匯出白名單 ──────────────────────────────
#
# 長跑的 manifest.json 會把當下整份 config.yaml 原樣快照起來，好讓事後能重建
# 執行條件。那對 run 目錄是對的，但這份 JSON 的去向不一樣：它會被
# build_html.py **內嵌進 demo/index.html**，而 index.html 是要給人看、要進
# 公開 repo 的。config.yaml 裡有 llm.api_key。
#
# 這裡用**白名單**而不是「排除 api_key」的黑名單，理由是兩者的失效方向相反：
#   - 黑名單只擋得住寫它的人當下想得到的欄位。config.yaml 之後多一個
#     token / password / webhook_url / 任何帶憑證的新區塊，黑名單不會自己長
#     出來，而漏出去的東西會留在 git 歷史裡，回不來。
#   - 白名單的預設是「不匯出」。新欄位要出現在 demo 上，得有人明確加進來，
#     而那個人就會在這裡看到這段註解。
#
# 判準：只放**讀者看得懂、且對理解結果有用**的欄位 —— 演算法超參數、模型
# 與端點、向量庫與沙箱。路徑類（*_path / *_dir / project_root）一律不放：
# 沒有解釋價值，又會洩漏開發機的目錄結構。
CONFIG_EXPORT_KEYS: dict[str, tuple[str, ...]] = {
    "utility":          ("alpha", "beta", "gamma_cost", "gamma_decay"),
    "memory_tiers":     ("theta_high", "theta_low", "epsilon_high", "epsilon_low"),
    "evolution":        ("delta", "theta_dup", "max_skills", "triggers"),
    "planner":          ("lambda1", "lambda2", "lambda3", "top_k",
                         "max_tokens_for_skills", "recent_traces"),
    "skill_validator":  ("theta_dup",),
    "embedding":        ("model", "device", "fallback", "batch_size", "max_seq_length"),
    "vector_store":     ("backend", "table_name"),
    "agent_zero":       ("docker_enabled", "docker_image", "container_name",
                         "timeout", "max_subordinates", "library_mode", "port"),
    "llm":              ("base_url", "api_format", "model", "temperature",
                         "max_tokens", "max_retries", "timeout"),
    "llm_tier_b":       ("base_url", "api_format", "model", "temperature",
                         "max_tokens", "max_retries", "timeout"),
    "curriculum_loop":  ("idle_threshold_seconds", "poll_interval_seconds",
                         "phi_every_n_tasks", "k_per_cluster",
                         "max_consecutive_empty_generations"),
    "web_search":       ("web_timeout", "max_results", "read_max_chars", "provider"),
}


def filter_config_snapshot(config: dict) -> dict:
    """把 manifest 的 config 快照縮成 CONFIG_EXPORT_KEYS 允許的欄位。

    白名單外的區塊（metaclaw / simplemem / curriculum / system …）整塊不匯出；
    白名單內的區塊也只留列舉到的鍵。輸入不會被就地修改。
    """
    out = {}
    for section, keys in CONFIG_EXPORT_KEYS.items():
        src = config.get(section)
        if not isinstance(src, dict):
            continue
        kept = {k: src[k] for k in keys if k in src}
        if kept:
            out[section] = kept
    return out


# ── 小工具 ────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    """逐行讀 JSONL，跳過空行；壞行直接拋（資料包不容忍靜默遺漏）。"""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{i} 不是合法 JSON: {e}") from e
    return out


def _parse_graph_index(path: Path) -> tuple[dict, list[dict], list[dict]]:
    """從 GRAPH_INDEX.md 的三個 ```yaml 區塊取出 meta / nodes / edges。"""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    if len(blocks) < 3:
        raise ValueError(f"{path} 只找到 {len(blocks)} 個 yaml 區塊，預期 3 個")
    meta = yaml.safe_load(blocks[0]) or {}
    nodes = (yaml.safe_load(blocks[1]) or {}).get("nodes") or []
    edges = (yaml.safe_load(blocks[2]) or {}).get("edges") or []
    return meta, nodes, edges


# learned 只能由明確列入允許清單的 provenance 值產生。
# 目前該清單是空的 —— 誠實牆上「學習來的邊 = 0」因此是結構保證，
# 不是碰巧正確。新增任何一類邊時，必須明確決定它屬於哪一格。
_LEARNED_PROVENANCE: frozenset[str] = frozenset()


def _provenance_class(edge: dict) -> str:
    """照 sies_doctor 的分類把一條邊歸類。

    白名單制：不在任何一張清單上的 provenance 一律歸 unclassified，
    絕不預設成 learned。原本的 fallback 是 `return "learned"`，
    任何新來源的邊（例如記憶層的 observational_v1）會被靜默算成學習成果。
    """
    prov = edge.get("provenance")
    if prov == "curriculum_path":
        return "curriculum"
    if prov == "phi_iii_contraction":
        return "contraction"
    if prov is None:
        return "bootstrap"
    if prov in _LEARNED_PROVENANCE:
        return "learned"
    return "unclassified"


def _lance_rows() -> int | None:
    """只取 row count，不做查詢；失敗回 None 而不是讓整包產不出來。"""
    try:
        import lancedb
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        vs = cfg.get("vector_store", {})
        raw = vs.get("path", "./data/lancedb")
        db_path = (CONFIG.resolve().parent / raw).resolve()
        table = vs.get("table_name", "skill_embeddings")
        return lancedb.connect(str(db_path)).open_table(table).count_rows()
    except Exception as e:  # noqa: BLE001 — demo 資料包不該因為這個中斷
        print(f"  [warn] LanceDB count_rows 失敗: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _run_doctor() -> dict | None:
    """跑 scripts/sies_doctor.py --json，parse stdout。

    doctor 的 --json 模式把人看的報告全部送到 stderr，stdout 只留純 JSON。
    它只用 lancedb，不建 EmbeddingEngine 也不建 LLMClient。
    """
    try:
        r = subprocess.run(
            [sys.executable, str(DOCTOR), "--json"],
            capture_output=True, text=True, timeout=300, cwd=str(ROOT),
        )
        if r.returncode != 0:
            print(f"  [warn] sies_doctor 退出碼 {r.returncode}", file=sys.stderr)
        return json.loads(r.stdout)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] sies_doctor --json 失敗: {type(e).__name__}: {e}", file=sys.stderr)
        return None


# ── 組裝 ──────────────────────────────────────────────────────

def build(run_id: str) -> dict:
    run_dir = ROOT / "data" / "w16" / "runs" / run_id

    # 圖
    print("  讀 GRAPH_INDEX.md ...")
    meta, raw_nodes, raw_edges = _parse_graph_index(GRAPH_INDEX)

    # 每個節點的進出邊總數
    degree: Counter[str] = Counter()
    for e in raw_edges:
        degree[e.get("source")] += 1
        degree[e.get("target")] += 1

    nodes = []
    for n in raw_nodes:
        name = n.get("name")
        nodes.append({
            "name": name,
            "tier": n.get("tier"),
            "utility": n.get("utility"),
            "frequency": n.get("frequency"),
            "domain": n.get("domain"),
            "type": n.get("type"),
            "path": n.get("path"),
            "is_macro": bool(str(name).startswith("macro-")),
            "parent_skills": n.get("parent_skills") or None,
            "degree": degree.get(name, 0),
        })

    edges = [{
        "source": e.get("source"),
        "target": e.get("target"),
        "relation": e.get("relation"),
        "weight": e.get("weight"),
        "provenance_class": _provenance_class(e),
    } for e in raw_edges]

    # 技能全文
    print("  讀 SKILL.md 全文 ...")
    skills: dict[str, str] = {}
    for n in raw_nodes:
        name, rel = n.get("name"), n.get("path")
        if not (name and rel):
            continue
        p = ROOT / rel
        if p.exists():
            skills[name] = p.read_text(encoding="utf-8")
        else:
            print(f"  [warn] SKILL.md 不存在: {rel}", file=sys.stderr)

    # 演化記錄
    print("  讀 evolution_log.jsonl ...")
    evolution_log = _read_jsonl(EVOLUTION_LOG)

    # 長跑
    print(f"  讀 run {run_id} ...")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    # manifest 的 config 是整份 config.yaml 的原樣快照，含 llm.api_key。
    # 這份 JSON 會被內嵌進公開的 index.html，所以只留白名單內的欄位。
    manifest["config"] = filter_config_snapshot(manifest.get("config", {}))
    attempts = _read_jsonl(run_dir / "attempts.jsonl")
    checkpoints = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((run_dir / "checkpoints").glob("*.json"))
    ]

    # 體檢
    print("  跑 sies_doctor.py --json ...")
    doctor = _run_doctor()

    # 向量庫
    print("  取 LanceDB row count ...")
    lance_rows = _lance_rows()

    # ── counts ────────────────────────────────────────────────
    tier_counter = Counter(n["tier"] for n in nodes)
    prov_counter = Counter(e["provenance_class"] for e in edges)

    touched = {e["source"] for e in edges} | {e["target"] for e in edges}
    isolated = [n["name"] for n in nodes if n["name"] not in touched]

    runs = _read_jsonl(RUN_SUMMARY)
    vi = [r for r in runs if r.get("verification_status") == "verified_independent"]

    counts = {
        "nodes_total": len(nodes),
        "edges_total": len(edges),
        "tier": {
            "active": tier_counter.get("active", 0),
            "cold": tier_counter.get("cold", 0),
            "archive": tier_counter.get("archive", 0),
        },
        "edges_by_provenance": {
            "bootstrap": prov_counter.get("bootstrap", 0),
            "curriculum": prov_counter.get("curriculum", 0),
            "contraction": prov_counter.get("contraction", 0),
            # 刻意保留：目前必然是 0，這一格才是「系統學會連接」的證據位
            "learned": prov_counter.get("learned", 0),
            # 白名單之外的 provenance 落在這裡，而不是被算成 learned。
            # 非 0 代表有新來源的邊進了圖卻沒人決定它算哪一類 —— 要去分類，不要忽略。
            "unclassified": prov_counter.get("unclassified", 0),
        },
        "isolated_nodes": len(isolated),
        "isolated_ratio": round(len(isolated) / len(nodes), 4) if nodes else 0.0,
        "macros": sum(1 for n in nodes if n["is_macro"]),
        "verified_independent_total": len(vi),
        "verified_independent_true": sum(1 for r in vi if r.get("verified_success") is True),
        "evolve_calls": len(evolution_log),
        "evolve_forced": sum(1 for r in evolution_log if r.get("triggered_by") == ["force"]),
        "skills_inserted_total": sum(r.get("inserted_count", 0) or 0 for r in evolution_log),
        "skills_rejected_total": sum(r.get("rejected_count", 0) or 0 for r in evolution_log),
        "tier_migrations_total": sum(r.get("tier_migrations", 0) or 0 for r in evolution_log),
    }

    return {
        "generated_at": datetime.now(TZ_TPE).isoformat(),
        "system": {
            "llm": {"model": "Gemma-4-26B-A4B IQ4_XS", "endpoint": "localhost:8080"},
            "embedding": {
                "model": "nvidia/llama-embed-nemotron-8b",
                "device": "cpu",
                "dim": 4096,
            },
            "vector": {"backend": "lancedb", "rows": lance_rows},
            "sandbox": {"container": "sies-agent-zero", "image": "frdel/agent-zero:latest"},
            "hardware": "i9-13900K + RTX 4060 Ti 16GB",
            "note": "全程本地推論，無雲端 API 呼叫",
        },
        "graph": {"meta": meta, "nodes": nodes, "edges": edges},
        "skills": skills,
        "evolution_log": evolution_log,
        "run": {
            "run_id": run_id,
            "manifest": manifest,
            "attempts": attempts,
            "checkpoints": checkpoints,
        },
        "doctor": doctor,
        "counts": counts,
    }


def _resanitize(path: Path) -> int:
    """只重套 config 白名單，其餘一個位元組都不動。

    完整重建會把 generated_at 換成今天、並重跑 doctor 與 LanceDB 計數 ——
    那會讓已經發布的四張圖與 README 的數字對不上。這條路徑只改
    run.manifest.config 一處，快照日期與所有統計值原樣保留。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    before = data["run"]["manifest"].get("config", {})
    after = filter_config_snapshot(before)
    data["run"]["manifest"]["config"] = after

    dropped = sorted(set(before) - set(after))
    trimmed = sorted(k for k in after if set(before.get(k, {})) - set(after[k]))
    print(f"[build_data] --resanitize {path}")
    print(f"  整塊移除的區塊 : {', '.join(dropped) or '（無）'}")
    print(f"  只留部分鍵的區塊: {', '.join(trimmed) or '（無）'}")
    print(f"  generated_at 維持 {data['generated_at']}（未重建）")

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已寫回 {path.stat().st_size:,} bytes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=DEFAULT_RUN_ID, help=f"長跑 run_id（預設 {DEFAULT_RUN_ID}）")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "data.json"),
                    help="輸出路徑（預設 demo/data.json）")
    ap.add_argument("--resanitize", action="store_true",
                    help="不重建資料，只把既有 --out 檔的 run.manifest.config "
                         "重新套一次 CONFIG_EXPORT_KEYS 白名單後寫回。"
                         "用於既有快照裡有不該匯出的欄位、但又要保住 "
                         "generated_at 與所有統計值不動的情況。")
    args = ap.parse_args()

    if args.resanitize:
        return _resanitize(Path(args.out))

    print(f"[build_data] run_id = {args.run}")
    data = build(args.run)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    size = out.stat().st_size
    print(f"\n[build_data] 已寫出 {out}")
    print(f"[build_data] 大小 = {size:,} bytes ({size / 1024:.1f} KiB)")
    print(f"[build_data] skills 全文 {len(data['skills'])} 筆 / "
          f"evolution_log {len(data['evolution_log'])} 筆 / "
          f"attempts {len(data['run']['attempts'])} 筆 / "
          f"checkpoints {len(data['run']['checkpoints'])} 筆")
    print("\n[build_data] counts =")
    print(json.dumps(data["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
