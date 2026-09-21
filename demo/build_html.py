#!/usr/bin/env python3
"""
demo/build_html.py — 把資料 inline 進 demo/index.html
=====================================================

demo 必須用 file:// 直接開就能完整運作，所以不能 fetch 任何東西。
這支腳本把三份 JSON 內嵌進 template.html 的 <script type="application/json">
區塊，產出單一檔 demo/index.html。

內嵌的三份資料：
  demo/data.json                          ← demo/build_data.py 產生
  demo/queries.json                       ← demo/build_queries.py 產生
  data/w16/runs/<run_id>/tasks.jsonl      ← 題目描述（見下）

為什麼要第三份：`attempts.jsonl`（data.json 的 run.attempts）**沒有題目描述**
欄位，它只有 task_id。長跑回放分頁要顯示題目，描述必須從同一個 run 的
tasks.jsonl 以 task_id 對回去。這裡只取 title / task_description 兩個欄位，
不動 build_data.py。

只讀不改：唯一的寫入是 demo/index.html。

用法：
    python demo/build_html.py
    python demo/build_html.py --out X.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

TEMPLATE = HERE / "template.html"
DATA_JSON = HERE / "data.json"
QUERIES_JSON = HERE / "queries.json"


def _inline_json(obj) -> str:
    """把物件序列化成可安全放進 <script> 的 JSON 字串。

    HTML parser 看到 `</script` 就會結束 script 區塊，而 SKILL.md 的內容是
    使用者資料、不能假設裡面沒有這串。JSON 字串中的 `/` 可以寫成 `\\/`，
    語意完全相同，所以把 `</` 換成 `<\\/` 是安全且無損的。
    同理處理 `<!--`（HTML 註解起始）與 U+2028/2029（JS 中是換行符）。
    """
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("</", "<\\/")
    s = s.replace("<!--", "<\\u0021--")
    s = s.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return s


def load_task_descriptions(run_id: str) -> dict:
    """從該 run 的 tasks.jsonl 取 {task_id: {title, task_description}}。"""
    p = ROOT / "data" / "w16" / "runs" / run_id / "tasks.jsonl"
    if not p.exists():
        print(f"  [warn] {p} 不存在，長跑回放分頁將沒有題目描述")
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        out[t["task_id"]] = {
            "title": t.get("title", ""),
            "task_description": t.get("task_description", ""),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE / "index.html"))
    args = ap.parse_args()

    for p in (TEMPLATE, DATA_JSON, QUERIES_JSON):
        if not p.exists():
            print(f"[build_html] 缺少 {p}")
            return 1

    print("[build_html] 讀 template.html ...")
    html = TEMPLATE.read_text(encoding="utf-8")

    print("[build_html] 讀 data.json ...")
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    print("[build_html] 讀 queries.json ...")
    queries = json.loads(QUERIES_JSON.read_text(encoding="utf-8"))

    run_id = data["run"]["run_id"]
    print(f"[build_html] 讀 tasks.jsonl (run={run_id}) ...")
    tasks = load_task_descriptions(run_id)
    matched = sum(1 for a in data["run"]["attempts"] if a["task_id"] in tasks)
    print(f"[build_html]   題目描述 {len(tasks)} 筆，對得上 attempts 的 "
          f"{matched}/{len(data['run']['attempts'])}")

    subs = {
        "__SIES_DATA_JSON__": _inline_json(data),
        "__SIES_QUERIES_JSON__": _inline_json(queries),
        "__SIES_TASKS_JSON__": _inline_json(tasks),
    }
    for token, payload in subs.items():
        if token not in html:
            print(f"[build_html] template 中找不到 {token}")
            return 1
        html = html.replace(token, payload)
        print(f"[build_html]   {token:26s} → {len(payload):>9,} bytes")

    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    size = out.stat().st_size

    # 自我檢查：內嵌後不應該再有任何未被跳脫的 </script 提前關閉區塊
    n_open = html.count('<script')
    n_close = html.count('</script>')
    print(f"\n[build_html] 已寫出 {out}")
    print(f"[build_html] 大小 = {size:,} bytes ({size/1024:.1f} KiB)")
    print(f"[build_html] <script 標籤 {n_open} 個 / </script> {n_close} 個 "
          f"{'(配對正確)' if n_open == n_close else '(不配對！)'}")
    return 0 if n_open == n_close else 1


if __name__ == "__main__":
    raise SystemExit(main())
