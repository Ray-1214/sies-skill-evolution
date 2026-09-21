"""
verifier_sanity.py — negative control：驗證 verifier 本身有沒有鑑別力（P1-a step 4）
====================================================================================
**為什麼需要這一步**：P5-0 量到 33% 捏造率，而其中 G2 編出來的 `COLLISION=20`
正好落在手寫 verifier 的合理區間內。**verifier 自己可能有洞。**若先寫 verifier、
直接拿去長跑、事後才補這一步，你可能已經用一個有洞的 verifier 跑完整輪、數據全污染。

對每個 verifier 丟假解，**全部都必須 FAIL** 才算有鑑別力：

    F1  空檔案                        —— 什麼都沒做           【所有 kind】
    F2  只 print("hello") 的腳本      —— 做了事但不是這件事   【所有 kind】
    F3  前一題的答案                  —— 做了別題的事         【所有 kind】
                                          （TD-11 殘留的形態）
    F4  直接印出正解的常數程式        —— ⭐ P5-0 的 G2 捏造形態【只對 run_capture】
    F5  輸入敏感度                    —— 題目的答案是否真的依賴輸入【只對值型 kind】

⚠️ **F4 只對 `run_capture` 有意義**。對 `json_equals` / `csv_column` 這種「產物
   就是答案」的 kind，寫出正確答案**本來就該通過** —— 檢查無法分辨「算出來的」
   和「知道答案的」，那是**題目**的問題不是**檢查**的問題。所以值型 kind 改用
   **F5 輸入敏感度**：擾動 input_files、重跑參考解，`expected` 必須跟著改變。
   不變 = 答案跟輸入無關 = 光看題目就能猜 = 壞題目，該淘汰。

M/N ≥ 0.9 才准進長跑。低於就停下來修出題器，不是往下推。

另有硬規則：`file_exists` 對 F1/F2/F3 一個都擋不住（0/3），**永遠不能是一題唯一的
spec**，`compute_status` 會把這種題判成 not_available。

用法:
    python scripts/verifier_sanity.py                  # 跑內建的 D1/D2/D3 四元組
    python scripts/verifier_sanity.py --from path.json # 跑出題器產出的四元組
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from verify_runner import derive_expected, run_checks, compute_status, put_file, sh, clean_workdir  # noqa: E402
from p1a_quads import QUADS  # noqa: E402


# ── 四種假解 ────────────────────────────────────────────────────────

# 產物是「程式」的 kind —— F4 常數腳本對這些才有意義
_PROGRAM_KINDS = {"run_capture"}


_ALL_QUADS: list = []          # check_all 設定；F3 要從「同一批」題裡取前一題


def fake_solutions(quad: dict, expected: dict) -> list[tuple[str, str, dict]]:
    """回傳 [(名稱, 說明, {檔名: 內容})]。內容是「假的 agent 產物」。"""
    arts = list(expected.keys())
    fakes = [
        ("F1_空檔案", "什麼都沒做", {a: "" for a in arts}),
        ("F2_hello",  "做了事但不是這件事",
         {a: 'print("hello")\n' if a.endswith(".py") else "hello\n" for a in arts}),
    ]

    # F3：前一題的答案。用 QUADS 裡的另一題的參考解產物當內容。
    pool = _ALL_QUADS or QUADS
    others = [q for q in pool if q["task_id"] != quad["task_id"]]
    if others:
        prev = others[0]
        prev_out = _reference_artifacts(prev)
        # 把前一題的產物「改名」成這一題要求的檔名 —— 正是 TD-11 殘留的形態
        content = {}
        for i, a in enumerate(arts):
            vals = list(prev_out.values())
            content[a] = vals[i % len(vals)] if vals else ""
        fakes.append((f"F3_前一題({prev['task_id']})的答案", "做了別題的事", content))

    # F4：只對「產物是程式」的 kind 有意義 —— 一個直接印出正解的常數腳本。
    # 對值型 kind（json_equals / csv_column）寫出正確答案本來就該通過，
    # 那是題目可不可猜的問題，交給 F5 輸入敏感度。
    prog = {a: sp for a, sp in expected.items() if sp["kind"] in _PROGRAM_KINDS}
    if prog:
        const = {}
        for a, sp in prog.items():
            eq = {}
            for case in (sp.get("cases") or []):
                eq.update(case.get("equals") or {})
            line = sp.get("pattern", "")
            for k, v in eq.items():
                line = line.replace(f"(?P<{k}>-?\\d+)", str(v)).replace(f"(?P<{k}>\\d+)", str(v))
            const[a] = f'print({line!r})\n'
        fakes.append(("F4_常數腳本", "P5-0 的 G2 捏造形態", const))
    return fakes


def _perturbations(inputs: dict) -> list[tuple[str, dict]]:
    """產生多組擾動。單一擾動可能剛好不改變答案（例如把 id 從 1 改成 78 仍是合法
    int），所以試多種：任一種讓 expected 改變，就證明答案依賴輸入。"""
    import copy
    out = []
    for name, content in inputs.items():
        if name.endswith(".csv"):
            lines = content.rstrip("\n").split("\n")
            # (a) 數值放大
            rows = [lines[0]]
            for ln in lines[1:]:
                cs = ln.split(",")
                for i, c in enumerate(cs):
                    if c.strip() and _isnum_str(c):
                        cs[i] = str(float(c) * 3 + 1); break
                rows.append(",".join(cs))
            out.append((f"{name}:數值×3+1", {**inputs, name: "\n".join(rows) + "\n"}))
            # (b) 刪掉一列
            if len(lines) > 2:
                out.append((f"{name}:刪一列",
                            {**inputs, name: "\n".join([lines[0]] + lines[2:]) + "\n"}))
            # (c) 把某個非空值清空（製造新的缺值）
            rows = [lines[0]]
            done = False
            for ln in lines[1:]:
                cs = ln.split(",")
                if not done:
                    for i, c in enumerate(cs):
                        if c.strip() and _isnum_str(c):
                            cs[i] = ""; done = True; break
                rows.append(",".join(cs))
            if done:
                out.append((f"{name}:製造缺值", {**inputs, name: "\n".join(rows) + "\n"}))
        elif name.endswith(".json"):
            try:
                base = json.loads(content)
            except json.JSONDecodeError:
                continue
            if isinstance(base, list) and base and isinstance(base[0], dict):
                # (a) 讓第一筆變不合法：刪掉一個 key
                d = copy.deepcopy(base)
                if d[0]:
                    k = sorted(d[0])[0]; d[0].pop(k)
                    out.append((f"{name}:刪第一筆的 {k}", {**inputs, name: json.dumps(d)}))
                # (b) 數值變負
                d = copy.deepcopy(base)
                for r in d:
                    for k, v in r.items():
                        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                            r[k] = -abs(v) - 1
                            out.append((f"{name}:數值變負", {**inputs, name: json.dumps(d)}))
                            break
                    else:
                        continue
                    break
                # (c) 讓最後一筆變合法
                d = copy.deepcopy(base)
                d[-1] = {"id": 99, "name": "zed", "age": 7}
                out.append((f"{name}:最後一筆改成合法", {**inputs, name: json.dumps(d)}))
    return out


def input_sensitivity(quad: dict, expected: dict, wd: str) -> tuple[bool, str]:
    """F5：擾動輸入、重跑參考解，expected 必須跟著變。

    不變 = 答案跟輸入無關 = 光看題目就能猜 = 壞題目。
    這是值型 kind 的 anti-guess 防線（F4 常數腳本對值型 kind 沒有意義）。
    試多組擾動，**任一組**能改變答案就算通過。
    """
    import copy
    inputs = quad.get("input_files") or {}
    if not inputs:
        return False, "沒有 input_files，答案無從依賴輸入"
    perts = _perturbations(inputs)
    if not perts:
        return False, "無法擾動輸入（不支援的格式）"

    tried = []
    for i, (label, new_inputs) in enumerate(perts):
        q2 = copy.deepcopy(quad); q2["input_files"] = new_inputs
        exp2, detail = derive_expected(q2, f"{wd}_p{i}")
        if exp2 is None:
            tried.append(f"{label}(參考解失敗)"); continue
        for a in expected:
            v1 = expected[a].get("value", expected[a].get("values"))
            v2 = exp2.get(a, {}).get("value", exp2.get(a, {}).get("values"))
            if v1 != v2:
                return True, (f"[{label}] {a}: "
                              f"{json.dumps(v1,ensure_ascii=False)[:44]} → "
                              f"{json.dumps(v2,ensure_ascii=False)[:44]}")
        tried.append(label)
    return False, f"試了 {len(perts)} 組擾動 expected 都沒變（{', '.join(tried[:3])}）—— 答案可猜"


def _isnum_str(x):
    try:
        float(x); return True
    except ValueError:
        return False


_REF_CACHE: dict = {}


def _reference_artifacts(quad: dict) -> dict:
    """跑一題的參考解，把它產生的檔案內容抓回來（給 F3 當素材）。"""
    if quad["task_id"] in _REF_CACHE:
        return _REF_CACHE[quad["task_id"]]
    wd = f"/tmp/sanity_ref_{quad['task_id']}"
    clean_workdir(wd)
    for n, c in (quad.get("input_files") or {}).items():
        put_file(f"{wd}/{n}", c)
    put_file(f"{wd}/_ref.py", quad["reference_solution"])
    sh(f"cd {wd} && /opt/venv/bin/python3 _ref.py")
    out = {}
    for n in (quad.get("expected") or {}):
        rc, blob, _ = sh(f"cat {wd}/{n} 2>/dev/null")
        if rc == 0 and blob:
            out[n] = blob
    _REF_CACHE[quad["task_id"]] = out
    return out


# ── 主流程 ──────────────────────────────────────────────────────────

def check_one(quad: dict) -> dict:
    tid = quad["task_id"]
    wd = f"/tmp/sanity_{tid}"
    expected, detail = derive_expected(quad, wd)
    if expected is None:
        return {"task_id": tid, "usable": False, "reason": detail}

    status = compute_status(expected)
    kinds = sorted({s["kind"] for s in expected.values()})

    # 正解必須 PASS（否則 verifier 太嚴，會產生 false negative）
    clean_workdir(wd)
    for n, c in (quad.get("input_files") or {}).items():
        put_file(f"{wd}/{n}", c)
    put_file(f"{wd}/_sol.py", quad["reference_solution"])
    sh(f"cd {wd} && /opt/venv/bin/python3 _sol.py")
    sh(f"rm -f {wd}/_sol.py")
    pos_ok, pos_why, _ = run_checks(expected, wd)

    # 四種假解必須全部 FAIL
    rows = []
    for name, why, files in fake_solutions(quad, expected):
        clean_workdir(wd)
        for n, c in (quad.get("input_files") or {}).items():
            put_file(f"{wd}/{n}", c)
        for n, c in files.items():
            put_file(f"{wd}/{n}", c)
        ok, det, _ = run_checks(expected, wd)
        rows.append({"fake": name, "why": why, "rejected": not ok, "detail": det[:90]})

    # F5：值型 kind 的 anti-guess 防線
    needs_f5 = any(sp["kind"] not in _PROGRAM_KINDS for sp in expected.values())
    f5_ok, f5_why = (input_sensitivity(quad, expected, wd) if needs_f5 else (True, "n/a"))

    return {"task_id": tid, "usable": True, "status": status, "kinds": kinds,
            "positive_pass": pos_ok, "positive_detail": pos_why,
            "fakes": rows, "f5_ok": f5_ok, "f5_why": f5_why,
            "discriminating": pos_ok and all(r["rejected"] for r in rows) and f5_ok}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="src", help="出題器產出的四元組 JSON")
    args = ap.parse_args()

    global _ALL_QUADS
    quads = QUADS if not args.src else json.load(open(args.src, encoding="utf-8"))
    _ALL_QUADS = quads
    results = [check_one(q) for q in quads]

    print("=" * 74)
    print("negative control：verifier 有沒有鑑別力")
    print("=" * 74)
    for r in results:
        if not r["usable"]:
            print(f"\n{r['task_id']}  ✗ 題目作廢：{r['reason']}")
            continue
        mark = "✓" if r["discriminating"] else "✗"
        print(f"\n{r['task_id']}  {mark}  status={r['status']}  kinds={r['kinds']}")
        print(f"    正解      : {'PASS ✓' if r['positive_pass'] else 'FAIL ✗ ' + r['positive_detail']}")
        for f in r["fakes"]:
            m = "✓ 擋下" if f["rejected"] else "✗ 通過了"
            print(f"    {f['fake']:26s} {m:8s} {f['detail'] if not f['rejected'] else ''}")
        m5 = "✓ 有依賴" if r["f5_ok"] else "✗ 不依賴"
        print(f"    {'F5_輸入敏感度':24s} {m5:8s} {r['f5_why'][:80]}")

    usable = [r for r in results if r["usable"]]
    n = len(usable)
    m = sum(1 for r in usable if r["discriminating"])
    ratio = m / n if n else 0.0
    print("\n" + "=" * 74)
    print(f"M/N = {m}/{n} = {ratio:.0%}   門檻 0.9   →   "
          f"{'PASS，可以進長跑' if ratio >= 0.9 else 'FAIL，停下來修出題器，不要往下推'}")
    return 0 if ratio >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())
