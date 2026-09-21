"""
_check_runner.py — 宣告式驗證檢查的執行器（在沙箱容器內跑）
============================================================
這支腳本被 base64 送進 `sies-agent-zero` 容器，讀一份 JSON spec，回報通過與否。

設計約束（P5-0 實測推導）：
  1. **只驗磁碟上的產物，不看 agent 的最終答案。**
     P5-0 的 G2 捏造了 `COLLISION=20`，落在合理區間內 —— 解析 agent 輸出或用
     LLM judge 都會 false-pass。只有「去磁碟找檔案、實際執行它」擋得住。
  2. **kind 是封閉集合。** 不在 CHECK_KINDS 裡的一律硬失敗，不是略過。
  3. **沒有 eval / python_code 逃生艙。** 那會重新引入 LLM 寫的驗證邏輯
     （P5-0 證明有洞），也等於讓生成器驅動任意程式執行。
  4. **fail-closed。** 只有印出 VERIFY_PASS 才算通過；exit 0 本身不算
     （崩在印出之前也會 exit 0）。

spec 一律是資料，永遠不會被字串插進程式碼裡，所以沒有注入面。

用法（由 host 端的 verify_runner 呼叫）：
    python3 _check_runner.py <spec.json> <workdir>
"""

import json
import os
import re
import subprocess
import sys

CHECK_KINDS = {"json_equals", "csv_column", "pptx_outline", "run_capture", "file_exists"}

# 這兩類 kind 明確不存在，列在這裡是為了讓有人想加的時候先看到理由
_REJECTED_KINDS = {
    "regex_on_agent_stdout":
        "解析 agent 的最終答案 —— P5-0 的 G2 就是這樣讓捏造的 COLLISION=20 通過的",
    "python_code":
        "LLM 寫的驗證邏輯有洞（P5-0 實證），且等於任意程式執行",
    "eval": "同上",
}


def _num_eq(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _deep_eq(got, exp, tol):
    """結構嚴格、數值容忍。

    tol 只放寬**數值葉節點**；key 集合與 list 長度仍要完全相符。
    （P5-0 的 D3：若容忍寫成「只比對兩邊都有的 key」，{"North":25.0} 單獨就過了。）
    """
    if isinstance(exp, dict):
        if not isinstance(got, dict) or set(got) != set(exp):
            return False
        return all(_deep_eq(got[k], exp[k], tol) for k in exp)
    if isinstance(exp, list):
        if not isinstance(got, list) or len(got) != len(exp):
            return False
        return all(_deep_eq(g, e, tol) for g, e in zip(got, exp))
    if isinstance(exp, bool) or isinstance(got, bool):
        return got is exp          # bool 不跟 0/1 互通
    if isinstance(exp, (int, float)) and tol:
        return _num_eq(got, exp, tol)
    return got == exp


# ── 五種 check kind ────────────────────────────────────────────────

def _c_file_exists(spec, wd):
    p = os.path.join(wd, spec["path"])
    if not os.path.isfile(p):
        return False, f"{spec['path']} 不存在"
    n = os.path.getsize(p)
    lo = spec.get("min_bytes", 0)
    if n < lo:
        return False, f"{spec['path']} 只有 {n} bytes < {lo}"
    return True, "ok"


def _c_json_equals(spec, wd):
    p = os.path.join(wd, spec["path"])
    if not os.path.isfile(p):
        return False, f"{spec['path']} 不存在"
    try:
        got = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return False, f"{spec['path']} 不是合法 JSON: {type(e).__name__}"
    if _deep_eq(got, spec["value"], spec.get("tol", 0)):
        return True, "ok"
    return False, f"值不符：got={json.dumps(got, ensure_ascii=False)[:150]}"


def _c_csv_column(spec, wd):
    import csv
    p = os.path.join(wd, spec["path"])
    if not os.path.isfile(p):
        return False, f"{spec['path']} 不存在"
    with open(p, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        hdr = rd.fieldnames or []
        rows = list(rd)
    if "header" in spec and hdr != spec["header"]:
        return False, f"欄位不符：got={hdr} want={spec['header']}"
    if "rows" in spec and len(rows) != spec["rows"]:
        return False, f"列數 {len(rows)} != {spec['rows']}"
    col, want, tol = spec["column"], spec["values"], spec.get("tol", 0)
    if col not in hdr:
        return False, f"沒有欄位 {col}"
    got = [r[col] for r in rows]
    if len(got) != len(want):
        return False, f"{col} 有 {len(got)} 個值，預期 {len(want)}"
    for i, (g, w) in enumerate(zip(got, want)):
        ok = _num_eq(g, w, tol) if isinstance(w, (int, float)) else (g == w)
        if not ok:
            return False, f"{col}[{i}]: {g!r} != {w!r}"
    return True, "ok"


def _c_pptx_outline(spec, wd):
    p = os.path.join(wd, spec["path"])
    if not os.path.isfile(p):
        return False, f"{spec['path']} 不存在"
    try:
        from pptx import Presentation
        pres = Presentation(p)
    except Exception as e:
        return False, f"python-pptx 開不起來: {type(e).__name__}"

    slides = []
    for s in pres.slides:
        title = s.shapes.title.text.strip() if s.shapes.title else ""
        body = ""
        for sh in s.shapes:
            if sh.has_text_frame and (not s.shapes.title or sh != s.shapes.title):
                if len(sh.text_frame.text) > len(body):
                    body = sh.text_frame.text
        slides.append({"title": title,
                       "bullets": [l.strip() for l in body.split("\n") if l.strip()]})

    want_n = spec.get("slides")
    if isinstance(want_n, int) and len(slides) != want_n:
        return False, f"{len(slides)} 張投影片 != {want_n}"
    if isinstance(want_n, dict):
        if len(slides) < want_n.get("min", 0) or len(slides) > want_n.get("max", 10**6):
            return False, f"{len(slides)} 張投影片不在 {want_n}"

    t = spec.get("titles") or {}
    if "set" in t and {s["title"] for s in slides} != set(t["set"]):
        return False, f"標題集合 {sorted(s['title'] for s in slides)} != {sorted(t['set'])}"
    for k, cond in t.items():
        if k == "set":
            continue
        i = int(k)
        if i >= len(slides):
            return False, f"沒有第 {i} 張投影片"
        if "contains" in cond and cond["contains"] not in slides[i]["title"]:
            return False, f"投影片 {i} 標題不含 {cond['contains']!r}"
        if "equals" in cond and slides[i]["title"] != cond["equals"]:
            return False, f"投影片 {i} 標題 {slides[i]['title']!r} != {cond['equals']!r}"

    for k, cond in (spec.get("bullets") or {}).items():
        i = int(k)
        if i >= len(slides):
            return False, f"沒有第 {i} 張投影片"
        bl = slides[i]["bullets"]
        if len(bl) < cond.get("min", 0):
            return False, f"投影片 {i} 只有 {len(bl)} 個 bullet < {cond['min']}"
        if len(bl) > cond.get("max", 10**6):
            return False, f"投影片 {i} 有 {len(bl)} 個 bullet > {cond['max']}"
        mw = cond.get("max_words")
        if mw:
            bad = [b for b in bl if len(b.split()) > mw]
            if bad:
                return False, f"投影片 {i} 有 bullet 超過 {mw} 字: {bad[:2]}"
    return True, "ok"


def _c_run_capture(spec, wd):
    """執行**磁碟上的產物**，比對它自己的 stdout。永遠不看 agent 的回答。

    `cases` 是把這個 kind 從 liveness 升級成 independent 的關鍵：多組參數、
    每組有各自的正解，一個「直接印出常數」的腳本會在第二組掛掉。
    """
    p = os.path.join(wd, spec["path"])
    if not os.path.isfile(p):
        return False, f"{spec['path']} 不存在"
    env = dict(os.environ)
    env.update(spec.get("env") or {})
    interp = spec.get("interpreter", sys.executable)
    cases = spec.get("cases") or [{"argv": spec.get("argv") or [],
                                   "bounds": spec.get("bounds"),
                                   "equals": spec.get("equals")}]
    pat = re.compile(spec["pattern"])
    for ci, case in enumerate(cases):
        try:
            r = subprocess.run([interp, p, *[str(a) for a in (case.get("argv") or [])]],
                               capture_output=True, text=True,
                               timeout=spec.get("timeout", 60), env=env, cwd=wd)
        except subprocess.TimeoutExpired:
            return False, f"case {ci} 逾時"
        if r.returncode != spec.get("exit_code", 0):
            return False, f"case {ci} exit {r.returncode}: {(r.stderr or '')[-140:]}"
        m = pat.search(r.stdout)
        if not m:
            return False, f"case {ci} stdout 不符 pattern: {(r.stdout or '')[-140:]}"
        gd = m.groupdict()
        for k, want in (case.get("equals") or {}).items():
            if k not in gd or str(gd[k]) != str(want):
                return False, f"case {ci} {k}={gd.get(k)!r} != {want!r}"
        for k, b in (case.get("bounds") or {}).items():
            if k not in gd:
                return False, f"case {ci} pattern 沒有 group {k}"
            v = float(gd[k])
            if v < b.get("min", -1e18) or v > b.get("max", 1e18):
                return False, f"case {ci} {k}={v} 不在 {b}"
    return True, "ok"


_DISPATCH = {
    "file_exists": _c_file_exists,
    "json_equals": _c_json_equals,
    "csv_column": _c_csv_column,
    "pptx_outline": _c_pptx_outline,
    "run_capture": _c_run_capture,
}


def main():
    spec_path, wd = sys.argv[1], sys.argv[2]
    specs = json.load(open(spec_path, encoding="utf-8"))
    results = []
    for name, spec in specs.items():
        spec = dict(spec)
        spec.setdefault("path", name)
        kind = spec.get("kind")
        if kind in _REJECTED_KINDS:
            ok, detail = False, f"kind {kind!r} 已被明確拒絕：{_REJECTED_KINDS[kind]}"
        elif kind not in CHECK_KINDS:
            ok, detail = False, f"未知的 kind {kind!r}（封閉集合，不略過）"
        else:
            try:
                ok, detail = _DISPATCH[kind](spec, wd)
            except Exception as e:  # noqa: BLE001 — 任何例外都算失敗，fail-closed
                ok, detail = False, f"{type(e).__name__}: {e}"
        results.append({"artifact": name, "kind": kind, "passed": ok, "detail": detail})

    print("CHECK_RESULTS=" + json.dumps(results, ensure_ascii=False))
    if results and all(r["passed"] for r in results):
        print("VERIFY_PASS")


if __name__ == "__main__":
    main()
