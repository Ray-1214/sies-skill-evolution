"""
verify_runner.py — 四元組驗證的 host 端（P1-a step 3）
======================================================
出題器產出**四元組**，harness 在沙箱裡把 reference_solution 跑出來推導 `expected`：

    生成器 emit：task_description + input_files + reference_solution + oracle(意圖)
    harness    ：跑 reference_solution → 讀它產生的產物 → 推導 expected
    agent 收到 ：只有 task_description + input_files

**為什麼不讓 LLM 直接寫 expected**：它在腦中算 10.75 或 25.0/70.0/32.0 會偶爾算錯，
而錯的 expected 產生的是 false negative —— 那是跟捏造相反方向的污染。附帶好處：
reference solution 跑不出來的題，在送到 agent 之前就被淘汰，免費的品質過濾。

**verification_status 由這裡算，不信生成器自報**：`oracle` 只留作生成器的**意圖**，
用來當「意圖 independent 但實際只有 liveness」的警報。

依賴：docker exec 進 sies-agent-zero（跟 p5_0_probe.py 同一套 sh/put_file）。
"""

import base64
import json
import subprocess
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = "sies-agent-zero"
PY = "/opt/venv/bin/python3"
CHECKER_SRC = ROOT / "scripts" / "_check_runner.py"

# 一個 check kind 能撐起多強的宣稱。task 的狀態取所有 spec 裡**最弱**的那個。
_STRENGTH = {
    "json_equals": "independent",
    "csv_column": "independent",
    "pptx_outline": "liveness",   # 有 input 導出的字面值才升級，見 _spec_strength
    "run_capture": "liveness",    # 有 cases（多組參數各自有正解）才升級
    "file_exists": "liveness",    # ⚠ 危險：對三種假解一個都擋不住
}


def sh(cmd: str, timeout: int = 180):
    r = subprocess.run(
        ["docker", "exec", "-e", "SDL_VIDEODRIVER=dummy", CONTAINER, "bash", "-lc", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, r.stdout, r.stderr


def put_file(path: str, content: str):
    b = base64.b64encode(content.encode()).decode()
    sh(f"mkdir -p $(dirname {path}) && echo '{b}' | base64 -d > {path}")


def clean_workdir(wd: str):
    """TD-11：每題一個乾淨的工作目錄。沒有這步，verifier 會因前一題的殘留誤判 pass。"""
    sh(f"rm -rf {wd} && mkdir -p {wd}")


# ── 表達不出斷言的 spec ────────────────────────────────────────────

def _is_inert(spec: dict) -> bool:
    """這個 spec 有沒有可用的 oracle。

    `_check_runner._c_run_capture` 第一件事就是 `re.compile(spec["pattern"])`，
    無條件。但生成器很常發出只有 `{kind, path, from_reference}` 的裸 spec，而
    `derive_expected` 只替 json_equals/csv_column 填值、對 run_capture 什麼都不做
    —— 於是 checker 以 KeyError 收場，fail-closed 把它記成「驗證失敗」。

    實測：50 題長跑裡 7 題 run_capture **全部**這樣掛掉、0 題通過，佔了 18 個失敗
    裡的 7 個。那不是 agent 失敗，是這一題根本沒有 oracle —— 沒有 oracle 的題
    不該進 verified 的分母。這裡在 host 端把它濾掉，checker 保持 fail-closed 不動。

    ⚠️ 這**不動**「run_capture 要 ≥2 cases 才算 independent」那條設定（見
    `_spec_strength`）：判定 inert 要求 `cases` 和 `pattern` **兩者都沒有**，
    所以帶 cases 的 spec 一律照舊走 `_spec_strength`，強度規則完全不受影響。

    ⚠️ 已知缺口（不在這次修的範圍）：`cases` 有、`pattern` 沒有的 spec 仍會讓
    checker 在 `re.compile` 掛掉並被記成失敗。這次長跑 50 題裡沒有出現這個形狀
    （7 題全是兩者都缺），留給日後連同 checker 的 lazy-compile 一起處理。
    """
    return (spec.get("kind") == "run_capture"
            and not spec.get("pattern") and not spec.get("cases"))


def _usable(specs: dict) -> dict:
    return {k: v for k, v in specs.items() if not _is_inert(v)}


# ── spec 強度 ──────────────────────────────────────────────────────

def _spec_strength(spec: dict) -> str:
    kind = spec.get("kind")
    if kind == "run_capture":
        # 單一 case 只能證明「跑得動且輸出在範圍內」——一個直接印常數的腳本就過了。
        # 多組參數、每組有各自的正解，常數腳本會在第二組掛掉 → 才算 independent。
        return "independent" if len(spec.get("cases") or []) >= 2 else "liveness"
    if kind == "pptx_outline":
        # 純形狀檢查（幾張投影片、幾個 bullet）連前一題的檔案都能通過。
        # 要有從 input_files 導出的字面值（標題集合／必含字串）才算 independent。
        t = spec.get("titles") or {}
        has_literal = bool(t.get("set")) or any(
            ("contains" in c or "equals" in c) for k, c in t.items() if k != "set")
        return "independent" if has_literal else "liveness"
    return _STRENGTH.get(kind, "liveness")


def compute_status(specs: dict) -> str:
    """從**實際跑過的** spec 算 verification_status，不看生成器的 oracle 欄位。"""
    specs = _usable(specs)          # 表達不出斷言的不算「跑過」
    if not specs:
        return "not_available"
    kinds = [s.get("kind") for s in specs.values()]
    if all(k == "file_exists" for k in kinds):
        # file_exists 對「空檔／hello／前題答案」三種假解都擋不住，
        # 單獨當一題的全部 spec 時不能算驗過。
        return "not_available"
    strengths = [_spec_strength(s) for s in specs.values()]
    return ("verified_independent" if all(x == "independent" for x in strengths)
            else "verified_liveness")


# ── 四元組 → expected ──────────────────────────────────────────────

def derive_expected(quad: dict, wd: str) -> tuple[Optional[dict], str]:
    """在沙箱裡跑 reference_solution，用它產生的產物把 `expected` 的空缺填實。

    回傳 (expected, detail)。reference solution 跑不起來 → (None, why)，該題作廢。
    """
    clean_workdir(wd)
    for name, content in (quad.get("input_files") or {}).items():
        put_file(f"{wd}/{name}", content)

    ref = quad.get("reference_solution")
    if not ref:
        return None, "四元組缺 reference_solution"
    put_file(f"{wd}/_ref.py", ref)
    rc, out, err = sh(f"cd {wd} && {PY} _ref.py")
    if rc != 0:
        return None, f"reference_solution exit {rc}: {(err or out)[-200:]}"

    expected = {}
    for name, tmpl in (quad.get("expected") or {}).items():
        spec = dict(tmpl)
        spec.setdefault("path", name)
        kind = spec.get("kind")
        # 值已經寫死的就照用；標了 "from_reference" 的才去讀參考解的產物。
        # ⚠️ 這個 marker **不能 pop 掉**：pop 之後 expected 就固定死了，
        # verifier_sanity 的 F5（擾動輸入、重推導、看 expected 有沒有變）會拿到
        # 完全相同的值而誤判「答案不依賴輸入」。實測 6/6 全部誤判。
        if not spec.get("from_reference"):
            expected[name] = spec
            continue
        rc2, blob, err2 = sh(
            f"cd {wd} && {PY} -c "
            f"\"import json,sys;sys.argv=['x'];"
            f"print(open({name!r},'rb').read().decode('utf-8'))\"")
        if rc2 != 0:
            return None, f"參考解沒有產出 {name}"
        # 推導失敗一律回 (None, why) 讓呼叫端**淘汰這題**，絕不 raise：
        # 生成器很常編一個參考解根本沒產出的欄位名（實測 KeyError: 'value' 把整場
        # 50 題長跑在出題階段炸掉）。這跟「參考解跑不起來」是同一類的出題品質問題，
        # 不是 harness 故障 —— 走同一條淘汰路徑就好。
        try:
            if kind == "json_equals":
                spec["value"] = json.loads(blob)
            elif kind == "csv_column":
                import csv, io
                rows = list(csv.DictReader(io.StringIO(blob)))
                if not rows:
                    return None, f"參考解產出的 {name} 沒有資料列"
                col = spec.get("column")
                if col not in rows[0]:
                    return None, (f"{name} 沒有欄位 {col!r}"
                                  f"（實際欄位：{','.join(map(str, rows[0].keys()))}）")
                spec["values"] = [
                    float(r[col]) if _isnum(r[col]) else r[col] for r in rows]
                spec.setdefault("rows", len(rows))
                spec.setdefault("header", list(rows[0].keys()))
        except Exception as e:  # noqa: BLE001
            return None, f"{name} 推導 expected 失敗: {type(e).__name__}: {e}"
        expected[name] = spec

    # 參考解留下的檔案要清掉，否則 agent 直接拿現成的
    sh(f"rm -f {wd}/_ref.py " + " ".join(f"{wd}/{n}" for n in expected))
    return expected, "ok"


def _isnum(x):
    try:
        float(x); return True
    except (TypeError, ValueError):
        return False


# ── 執行檢查 ───────────────────────────────────────────────────────

def run_checks(specs: dict, wd: str) -> tuple[Optional[bool], str, list]:
    """把 spec 當**資料**送進沙箱跑固定的 _check_runner.py。

    spec 永遠不會被插進程式碼字串裡，所以沒有注入面。
    fail-closed：只有看到 VERIFY_PASS 才算通過。

    回傳的第一個值可能是 **None** —— 「沒有任何可用的 oracle」，既不是通過也不是
    失敗。呼叫端必須把它映成 verified_success=None，不能當 False。
    """
    specs = _usable(specs)
    if not specs:
        return None, "沒有可用的 oracle：spec 表達不出任何斷言（裸 run_capture）", []
    put_file(f"{wd}/_spec.json", json.dumps(specs, ensure_ascii=False))
    put_file(f"{wd}/_check.py", CHECKER_SRC.read_text(encoding="utf-8"))
    rc, out, err = sh(f"cd {wd} && {PY} _check.py _spec.json {wd}")
    details = []
    for line in out.splitlines():
        if line.startswith("CHECK_RESULTS="):
            try:
                details = json.loads(line[len("CHECK_RESULTS="):])
            except json.JSONDecodeError:
                pass
    passed = "VERIFY_PASS" in out
    if passed:
        return True, "ok", details
    why = next((d["detail"] for d in details if not d["passed"]),
               (err or out or f"exit {rc}").strip().splitlines()[-1:] or ["unknown"])
    return False, (why if isinstance(why, str) else why[0])[:220], details


def _verdict(ok: Optional[bool], status: str) -> Optional[bool]:
    """三層 success 的不變式：`status == "not_available"` ⇔ `verified_success is None`。

    「沒有可用的獨立驗證」跟「驗證跑了而且沒過」是兩件事。舊碼在 not_available 時
    仍回 True/False，等於把「量不到」記成了一個量測結果 —— 那 7 題裸 run_capture
    就是這樣被算進 verified 分母的。§7.1 說 null 絕不能當 True；同理也不能當 False。
    """
    return None if status == "not_available" else ok


def check_only(expected: dict, wd: str, intent: Optional[str] = None) -> dict:
    """**只跑檢查，不重推導。**

    ⚠️ 呼叫端如果已經先 derive 過 expected、放好 input、讓 agent 跑完，就必須用
    這個而不是 verify_task —— verify_task 會再 derive 一次，而 derive_expected
    的第一件事是 clean_workdir()，**會把 agent 的產出整個洗掉再檢查**，結果永遠
    是「檔案不存在」。dry-run 實測 5/5 全部因此誤判失敗。
    """
    ok, why, details = run_checks(expected, wd)
    status = compute_status(expected)
    if intent == "verified_independent" and status != "verified_independent":
        why = f"[意圖 independent 但實際只有 {status}] " + why
    return {"verified_success": _verdict(ok, status),
            "verification_status": status,
            "verify_detail": why, "checks": details}


def verify_task(quad: dict, wd: str) -> dict:
    """從零開始的完整流程：推導 expected → 跑檢查 → 算 status。

    ⚠️ 這會先 clean_workdir()。agent 已經跑完的情況請用 check_only()。
    """
    expected, detail = derive_expected(quad, wd)
    if expected is None:
        return {"verified_success": None, "verification_status": "not_available",
                "verify_detail": f"參考解失敗，題目作廢: {detail}", "checks": []}
    ok, why, details = run_checks(expected, wd)
    status = compute_status(expected)
    intent = quad.get("oracle")
    if intent == "verified_independent" and status != "verified_independent":
        why = f"[意圖 independent 但實際只有 {status}] " + why
    return {"verified_success": _verdict(ok, status),
            "verification_status": status,
            "verify_detail": why, "checks": details, "expected": expected}
