#!/usr/bin/env python3
"""W14 web search E2E test.

跑 5 個 research task 透過 SimpleAgent ReAct loop，
驗證 web_search / read_page tool 整合是否真能解 research domain 任務。

依賴：
  - LLM server localhost:8080 (Gemma-4-26B-A4B IQ4_XS)
  - web-search-server localhost:8081 (FastAPI + SearxNG + Scrapling)
  - SearxNG container localhost:8082

輸出：
  - stdout：per-task 一行 summary + final PASS x/5
  - data/w14/e2e/{id}.json：每個 task 的完整 trace + answer + metadata
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.simple_agent import SimpleAgent


TASKS = [
    {"id": "R1",
     "task": "查詢 PEP 703 的目前狀態 Status 是 Accepted 還是其他？請查證後回答。",
     "expect": ["Accepted", "accepted"]},
    {"id": "R2",
     "task": "FastAPI 要啟用 CORS 跨來源請求，應加入哪個 middleware 類別？",
     "expect": ["CORSMiddleware"]},
    {"id": "R3",
     "task": "SearxNG 是哪一種類型的搜尋軟體？",
     "expect": ["metasearch", "聚合", "元搜尋", "隱私", "privacy"]},
    {"id": "R4",
     "task": "Python 套件 Trafilatura 主要用途是什麼？",
     "expect": ["萃取", "正文", "extract", "網頁", "content"]},
    {"id": "R5",
     "task": "Python 套件管理工具 uv 是哪一家公司開發的？請查證。",
     "expect": ["Astral", "astral"]},
]


OUT_DIR = Path("data/w14/e2e")


def run_one(agent: SimpleAgent, task: dict) -> dict:
    t0 = time.time()
    result = agent.run(task["task"], task_id=task["id"])
    elapsed = time.time() - t0

    trace = result.get("trace", []) or []
    final = result.get("answer", "") or ""
    actions_used = sorted({(r.get("action") or "").lower() for r in trace if r.get("action")})

    used_web = "web_search" in actions_used
    used_read = "read_page" in actions_used
    hit = any(k.lower() in final.lower() for k in task["expect"])
    passed = used_web and hit

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dump = {
        "id": task["id"],
        "task": task["task"],
        "expect": task["expect"],
        "final_answer": final,
        "total_steps": result.get("total_steps", len(trace)),
        "actions_used": actions_used,
        "used_web_search": used_web,
        "used_read_page": used_read,
        "hit_keyword": hit,
        "passed": passed,
        "elapsed_seconds": round(elapsed, 2),
        "trace": trace,
    }
    (OUT_DIR / f"{task['id']}.json").write_text(
        json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return dump


def main() -> int:
    agent = SimpleAgent("config.yaml")

    summary = []
    print(f"{'id':<4} {'web':<5} {'read':<5} {'steps':>5} {'hit':<5} {'pass':<5} final[:80]")
    print("-" * 100)
    for task in TASKS:
        try:
            d = run_one(agent, task)
        except Exception as e:
            print(f"{task['id']:<4} ERROR: {e}", flush=True)
            summary.append({"id": task["id"], "passed": False, "error": str(e)})
            continue
        print(
            f"{d['id']:<4} "
            f"{str(d['used_web_search']):<5} "
            f"{str(d['used_read_page']):<5} "
            f"{d['total_steps']:>5} "
            f"{str(d['hit_keyword']):<5} "
            f"{str(d['passed']):<5} "
            f"{(d['final_answer'] or '')[:80]!r}",
            flush=True,
        )
        summary.append(d)

    n_pass = sum(1 for s in summary if s.get("passed"))
    print("-" * 100)
    print(f"PASS: {n_pass}/{len(TASKS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
