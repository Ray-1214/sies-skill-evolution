"""
scripts/w13_runner.py — W13 對照實驗 Day 2 / Day 4 執行入口
==============================================================
包 AgentRunner.run_batch()，加四件 W13 專屬邏輯：
  1. 每 10 題 checkpoint：跑完 task 10/20/30/40/50 後觸發 evolution_operator
     + build_w13_metrics
  2. case study trace dump：跑完任一 task_idx ∈ CASE_STUDIES.task_idx 即 dump
     trace 到 data/w13/case_studies/{variant}/CS-{N}.json
  3. tee log：所有 stdout/stderr 同時寫到 data/w13/{variant}_log_{ISO_ts}.txt
  4. --resume-from N：crash recovery，跳過已完成 task_idx

CLI:
    python scripts/w13_runner.py --variant {baseline,improved} [--resume-from N]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

# 確保 repo root 在 sys.path（從 scripts/ 直接執行時）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.agent_runner import AgentRunner, RunResult  # noqa: E402
from scripts.w13_50_tasks import TASKS_50, CASE_STUDIES  # noqa: E402

W13_DIR = ROOT / "data" / "w13"
SKILLS_DIR = ROOT / "skills"
BUILD_METRICS_SCRIPT = ROOT / "scripts" / "build_w13_metrics.py"

logger = logging.getLogger("w13_runner")


# ---------------------------------------------------------------------------
# Tee log
# ---------------------------------------------------------------------------


class _Tee:
    """同步寫到多個 stream（stdout + 檔案）。"""

    def __init__(self, *streams: TextIO):
        self.streams = streams

    def write(self, data: str) -> int:
        n = 0
        for s in self.streams:
            try:
                n = s.write(data)
                s.flush()
            except (ValueError, OSError):
                pass
        return n

    def flush(self) -> None:
        for s in self.streams:
            try:
                s.flush()
            except (ValueError, OSError):
                pass

    def isatty(self) -> bool:
        return False


def setup_tee_log(variant: str) -> tuple[Path, TextIO]:
    """安裝 tee：stdout/stderr 同時寫到 data/w13/{variant}_log_{ISO_ts}.txt。

    Returns (log_path, file_handle)。caller 在 main 結束時關 file_handle。
    """
    W13_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    log_path = W13_DIR / f"{variant}_log_{ts}.txt"

    fh = open(log_path, "a", encoding="utf-8", buffering=1)

    sys.stdout = _Tee(sys.__stdout__, fh)  # type: ignore[assignment]
    sys.stderr = _Tee(sys.__stderr__, fh)  # type: ignore[assignment]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    return log_path, fh


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def trigger_evolution(variant: str) -> None:
    """跑 evolution_operator（subprocess 隔離記憶體狀態）。

    失敗時 raise CalledProcessError，由 caller 中止 runner。
    """
    print(f"[W13] === Triggering evolution_operator (variant={variant}) ===")
    res = subprocess.run(
        [sys.executable, "-m", "evolution.evolution_operator"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    print("[W13] === evolution_operator done ===")


def write_checkpoint(variant: str, batch_end: int) -> None:
    """跑 build_w13_metrics.py 寫 checkpoint。

    輸出檔：data/w13/{variant}_checkpoints/{batch_end}.json
    若 build_w13_metrics.py 還沒寫（W13 後續日才補）→ 印 warning 不 crash。
    """
    if not BUILD_METRICS_SCRIPT.exists():
        print(
            f"[W13] WARN: {BUILD_METRICS_SCRIPT.relative_to(ROOT)} not yet written, "
            f"skipping checkpoint at batch_end={batch_end}"
        )
        return

    print(
        f"[W13] === Writing checkpoint (variant={variant}, batch_end={batch_end}) ==="
    )
    try:
        res = subprocess.run(
            [
                sys.executable,
                str(BUILD_METRICS_SCRIPT),
                "--variant",
                variant,
                "--batch-end",
                str(batch_end),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        if res.stdout:
            print(res.stdout)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(
            f"[W13] WARN: build_w13_metrics failed (exit {e.returncode}), "
            f"continuing runner"
        )
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr, file=sys.stderr)


# ---------------------------------------------------------------------------
# Case study dump
# ---------------------------------------------------------------------------


def _cs_id_for(task_idx: int) -> Optional[str]:
    """task_idx → 'CS-N'（從 CASE_STUDIES 反查），無對應回 None。"""
    for cs_key, meta in CASE_STUDIES.items():
        if meta.get("task_idx") == task_idx:
            return cs_key.split("_", 1)[0]
    return None


def _graph_state_snapshot() -> dict:
    """fs 計數 skills/{active,cold,archive}/**/SKILL.md + active 下 macro-* 目錄。"""
    def count(tier: str) -> int:
        d = SKILLS_DIR / tier
        if not d.exists():
            return 0
        return sum(1 for _ in d.glob("**/SKILL.md"))

    macros: list[str] = []
    active = SKILLS_DIR / "active"
    if active.exists():
        macros = sorted(d.name for d in active.glob("macro-*") if d.is_dir())

    return {
        "active_count": count("active"),
        "cold_count": count("cold"),
        "archive_count": count("archive"),
        "macros": macros,
    }


def _candidates_payload(result: RunResult) -> list[dict]:
    """從 extraction_result.candidates 取**全部** candidate（不是 dedup 後）。

    每個 candidate 標 `validated` bool 與 `rejection_reason`。對應的
    validation_report.results 與 extraction.candidates 是 index-aligned。
    """
    ev = getattr(result, "evaluation", None)
    if ev is None:
        return []

    extraction = getattr(ev, "extraction_result", None)
    if extraction is None or not getattr(extraction, "candidates", None):
        return []

    val_report = getattr(ev, "validation_report", None)
    val_results = list(getattr(val_report, "results", [])) if val_report else []

    payload = []
    for i, c in enumerate(extraction.candidates):
        vr = val_results[i] if i < len(val_results) else None
        passed = bool(getattr(vr, "passed", False)) if vr else False
        rej = (
            getattr(vr, "rejection_reason", None)
            if vr and not getattr(vr, "passed", False)
            else None
        )
        payload.append({
            "name": getattr(c, "name", ""),
            "type": getattr(c, "type", ""),
            "domain": list(getattr(c, "domain", []) or []),
            "validated": passed,
            "rejection_reason": rej,
        })
    return payload


def dump_case_study(result: RunResult, task_idx: int, variant: str) -> Path:
    """Dump case study JSON → data/w13/case_studies/{variant}/CS-{N}.json。

    Schema 必須對齊 docs/w13_case_study_expected.md（pass criterion 引用此欄位名）。
    """
    cs_id = _cs_id_for(task_idx)
    if cs_id is None:
        raise ValueError(f"task_idx={task_idx} not in CASE_STUDIES")

    out_dir = W13_DIR / "case_studies" / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cs_id}.json"

    plan = getattr(result, "plan_result", None) or {}
    selected = plan.get("selected_skills", []) or []
    a2_recall = [s.get("name", "") for s in selected if isinstance(s, dict)]

    extraction = getattr(getattr(result, "evaluation", None), "extraction_result", None)
    used_template_mode = bool(getattr(extraction, "used_template_mode", False))

    data = {
        "cs_id": cs_id,
        "task_idx": task_idx,
        "task": result.task,
        "variant": variant,
        "candidates": _candidates_payload(result),
        "a2_recall_top6": a2_recall,
        "trace_steps_count": int(getattr(result, "execution_steps", 0) or 0),
        "agent_outcome": "success" if getattr(result, "execution_success", False) else "failure",
        "graph_state_snapshot": _graph_state_snapshot(),
        "extraction_used_template_mode": used_template_mode,
        "elapsed_seconds": float(getattr(result, "elapsed_seconds", 0.0) or 0.0),
    }

    if getattr(result, "error", None):
        data["error_stage"] = getattr(result, "error_stage", None)
        data["error"] = result.error

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[W13] Case study dumped: {cs_id} → {out_path.relative_to(ROOT)}")
    return out_path


# ---------------------------------------------------------------------------
# Resume detection
# ---------------------------------------------------------------------------


_BATCH_DONE_RE = re.compile(r"Batch (\d+)/50 DONE")


def detect_resume_point(variant: str) -> int:
    """從 data/w13/{variant}_log_*.txt 最後一筆 'Batch N/50 DONE' 推 resume_from。

    無 log → 回 0。掃所有歷史 log 取最大 N，避免 crash 後新 log 蓋掉進度。
    """
    if not W13_DIR.exists():
        return 0
    logs = sorted(W13_DIR.glob(f"{variant}_log_*.txt"))
    if not logs:
        return 0

    last_done = 0
    for log in logs:
        try:
            with open(log, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _BATCH_DONE_RE.search(line)
                    if m:
                        n = int(m.group(1))
                        if n > last_done:
                            last_done = n
        except OSError:
            continue
    return last_done


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="W13 controlled-experiment runner (50 tasks × {baseline,improved})."
    )
    p.add_argument(
        "--variant",
        choices=["baseline", "improved"],
        required=True,
        help="A3 prompt 版本（決定輸出目錄與 case study 子目錄）",
    )
    p.add_argument(
        "--resume-from",
        type=int,
        default=None,
        metavar="N",
        help=(
            "從 task_idx=N（0-based）開始。預設 None → 自動從 log 推 resume "
            "point；要強制從頭跑用 --resume-from 0。"
        ),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    variant: str = args.variant

    log_path, log_fh = setup_tee_log(variant)
    print(f"[W13] === Run start: variant={variant} log={log_path.name} ===")

    (W13_DIR / f"{variant}_checkpoints").mkdir(parents=True, exist_ok=True)
    (W13_DIR / "case_studies" / variant).mkdir(parents=True, exist_ok=True)

    if args.resume_from is None:
        resume_from = detect_resume_point(variant)
        if resume_from > 0:
            print(f"[W13] Auto-detected resume point: task_idx={resume_from}")
    else:
        resume_from = max(0, args.resume_from)
        print(f"[W13] Manual resume from task_idx={resume_from}")

    if resume_from >= len(TASKS_50):
        print(f"[W13] resume_from={resume_from} ≥ {len(TASKS_50)}, nothing to do")
        log_fh.close()
        return 0

    cs_task_idxs = {meta["task_idx"] for meta in CASE_STUDIES.values()}

    runner = AgentRunner(str(ROOT / "config.yaml"))
    t_run0 = time.time()
    successes = 0
    failures = 0

    for task_idx in range(resume_from, len(TASKS_50)):
        n = task_idx + 1
        task = TASKS_50[task_idx]
        print(f"\n[W13] === Batch {n}/50 START (task_idx={task_idx}) ===")
        print(f"[W13] Task: {task[:120]}{'...' if len(task) > 120 else ''}")

        try:
            r = runner.run(task, skip_a3=False, write_candidates=True)
        except Exception as e:  # 不讓單題 crash 整個 50 題 run
            print(f"[W13] FATAL run() exception at task_idx={task_idx}: {e}")
            failures += 1
            continue

        if r.execution_success:
            successes += 1
        else:
            failures += 1

        if task_idx in cs_task_idxs:
            try:
                dump_case_study(r, task_idx, variant)
            except Exception as e:
                print(f"[W13] WARN: case study dump failed at task_idx={task_idx}: {e}")

        print(
            f"[W13] === Batch {n}/50 DONE "
            f"(success={r.execution_success}, steps={r.execution_steps}, "
            f"elapsed={r.elapsed_seconds}s) ==="
        )

        if n % 10 == 0:
            try:
                trigger_evolution(variant)
            except subprocess.CalledProcessError as e:
                print(
                    f"[W13] FATAL: evolution_operator failed (exit {e.returncode}) "
                    f"after batch {n}, aborting runner"
                )
                if e.stdout:
                    print(e.stdout)
                if e.stderr:
                    print(e.stderr, file=sys.stderr)
                log_fh.close()
                return 2
            write_checkpoint(variant, batch_end=n)

    elapsed = round(time.time() - t_run0, 2)
    print(
        f"\n[W13] === Run complete: variant={variant} "
        f"success={successes} failure={failures} elapsed={elapsed}s ==="
    )
    print(f"[W13] Log: {log_path}")
    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
