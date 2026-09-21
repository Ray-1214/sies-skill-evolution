"""
executor.py — 計畫執行器 (W7)

策略（v2，降級方案）：
  Agent-Zero 這版沒有外部 HTTP API（只有 CSRF-protected web UI endpoint）。
  採用計畫書 §6.3 降級方案：「直接在 Python 層面記錄 trace」。

  兩種執行模式：
  1. docker_exec 模式（預設）：透過 docker exec 在 Agent-Zero 容器內跑指令
     - 容器有完整 Python/bash 環境 + 沙盒隔離
     - 未來可升級為 Agent-Zero A2A/MCP 介面
  2. local 模式：直接在本機 subprocess 跑
     - 不需要 Docker
     - 用於 Agent-Zero 容器不可用時

  兩種模式都記錄完整 trace → JSONL（memory/episodic/）。

對應論文：
  - 執行層：A2 計畫 → 實體執行 → trace 記錄
  - Me (Episodic Memory): 每次任務產出的完整軌跡

用法：
  from executor import Executor
  exe = Executor("config.yaml")
  result = exe.execute(plan_result)  # plan_result from memory_planner.plan()
"""

import json
import re
import subprocess
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

TZ_TPE = timezone(timedelta(hours=8))


class Executor:
    """
    計畫執行器：將 A2 產出的 execution_plan 逐步執行並記錄 trace。

    W7 最小版：逐步執行、不做平行、安全模式（大部分 step 只做 echo 記錄）。
    W8 會定義完整 trace 格式，屆時 executor 會升級為「真正執行」模式。
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)

        az_cfg = self.config.get("agent_zero", {})
        self.container_name = az_cfg.get("container_name", "sies-agent-zero")
        self.docker_enabled = az_cfg.get("docker_enabled", True)
        self.exec_timeout = az_cfg.get("timeout", 300)

        self.trace_dir = Path(
            self.config.get("system", {}).get("trace_dir", "./memory/episodic")
        )
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        mode = "docker_exec" if self.docker_enabled else "local"
        print(f"[executor] Initialized. Mode: {mode}")

    def _load_config(self, config_path: str) -> dict:
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    # ── 核心 API ──────────────────────────────────────────────

    def execute(self, plan_result: dict) -> dict:
        """
        執行完整計畫並產出 trace。

        Args:
            plan_result: memory_planner.plan() 的回傳值

        Returns:
            {
                "task_id": str,
                "success": bool,
                "total_steps": int,
                "completed_steps": int,
                "failed_steps": int,
                "trace_file": str,
                "trace": list[dict],
                "elapsed_seconds": float,
            }
        """
        task_id = plan_result.get("task_id", "unknown")
        plan = self._parse_plan(plan_result.get("execution_plan", "{}"))
        steps = plan.get("steps", [])

        if not steps:
            print(f"[executor] WARN: no steps in plan for {task_id}")
            return self._empty_result(task_id, "no steps in plan")

        print(f"[executor] Executing {len(steps)} steps for {task_id}")

        trace_records = []
        completed = 0
        failed = 0
        t_start = time.time()

        for step in steps:
            step_id = step.get("step_id", "?")
            action = step.get("action", "")

            print(f"[executor]   Step {step_id}: {action[:60]}...")

            command = self._step_to_command(step)

            t_step = time.time()
            run_result = self._run_command(command)
            elapsed_step = time.time() - t_step

            success = run_result["exit_code"] == 0
            if success:
                completed += 1
            else:
                failed += 1

            record = {
                "task_id": task_id,
                "step_id": step_id,
                "subtask_ref": step.get("subtask_ref", ""),
                "action": action,
                "skill_used": step.get("skill_used", "none"),
                "skill_source": step.get("skill_source", ""),
                "command": command,
                "stdout": run_result["stdout"][:2000],
                "stderr": run_result["stderr"][:1000],
                "exit_code": run_result["exit_code"],
                "outcome": "success" if success else "failed",
                "error": run_result["stderr"][:500] if not success else None,
                "elapsed_seconds": round(elapsed_step, 2),
                "timestamp": datetime.now(TZ_TPE).isoformat(),
                "exec_mode": "docker_exec" if self.docker_enabled else "local",
            }
            trace_records.append(record)

            status = "OK" if success else "FAIL"
            print(f"[executor]     {status} exit={run_result['exit_code']} ({elapsed_step:.1f}s)")

        total_elapsed = time.time() - t_start
        trace_file = self._write_trace(task_id, trace_records)

        result = {
            "task_id": task_id,
            "success": failed == 0 and completed > 0,
            "total_steps": len(steps),
            "completed_steps": completed,
            "failed_steps": failed,
            "trace_file": str(trace_file),
            "trace": trace_records,
            "elapsed_seconds": round(total_elapsed, 2),
        }

        print(
            f"[executor] Done: {completed}/{len(steps)} steps OK, "
            f"{failed} failed, {total_elapsed:.1f}s total"
        )
        return result

    def health_check(self) -> bool:
        """檢查執行環境是否可用"""
        if self.docker_enabled:
            try:
                r = subprocess.run(
                    ["docker", "exec", self.container_name, "echo", "ok"],
                    capture_output=True, text=True, timeout=10,
                )
                return r.returncode == 0 and "ok" in r.stdout
            except Exception as e:
                print(f"[executor] Docker health check failed: {e}")
                return False
        else:
            return True

    # ── Step → Command ────────────────────────────────────────

    def _step_to_command(self, step: dict) -> str:
        """
        將計畫 step 轉為 shell 指令。

        W7 策略（安全模式）：
        - 大部分 step 只做 echo 記錄（不真正執行危險操作）
        - tool_hint == "code_execution" 且 action 看起來像 shell 指令 → 直接跑
        - 其他 → echo 記錄 action 內容

        W8+ 會加入 LLM 輔助的指令生成，真正執行完整計畫。
        """
        action = step.get("action", "echo 'no action'")
        tool_hint = step.get("tool_hint", "").lower()

        # code_execution: 如果 action 本身看起來像可執行的 shell 指令
        if tool_hint in ("code_execution", "code", "terminal"):
            if self._looks_like_shell_command(action):
                return action

        # 預設：echo 記錄（安全模式）
        return f'echo "[SIES] step {step.get("step_id", "?")}: {self._escape(action[:300])}"'

    @staticmethod
    def _looks_like_shell_command(text: str) -> bool:
        """
        判斷文字是否像可執行的 shell 指令。

        只允許安全的唯讀指令通過，避免 rm/dd/mkfs 之類的危險操作。
        """
        safe_prefixes = (
            "ls", "cat", "head", "tail", "wc", "grep", "find",
            "echo", "date", "pwd", "whoami", "uname", "env",
            "python3 -c", "python -c",
            "pip list", "pip show",
            "df", "du", "free",
        )
        text_lower = text.strip().lower()
        return any(text_lower.startswith(p) for p in safe_prefixes)

    # ── 指令執行 ──────────────────────────────────────────────

    def _run_command(self, command: str) -> dict:
        """
        執行指令，回傳 stdout/stderr/exit_code。
        """
        try:
            if self.docker_enabled:
                full_cmd = [
                    "docker", "exec", self.container_name,
                    "bash", "-c", command,
                ]
            else:
                full_cmd = ["bash", "-c", command]

            r = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=self.exec_timeout,
            )
            return {
                "stdout": r.stdout,
                "stderr": r.stderr,
                "exit_code": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"TIMEOUT after {self.exec_timeout}s",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -2,
            }

    # ── Plan 解析 ─────────────────────────────────────────────

    @staticmethod
    def _parse_plan(plan_raw) -> dict:
        """解析 execution_plan（JSON string 或 dict），容錯 markdown fence / <think>。"""
        if isinstance(plan_raw, dict):
            return plan_raw
        if not isinstance(plan_raw, str):
            return {}

        text = plan_raw.strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass

        return {}

    # ── Trace 寫入 ────────────────────────────────────────────

    def _write_trace(self, task_id: str, records: list[dict]) -> Path:
        """寫入 JSONL trace 檔案到 memory/episodic/"""
        ts = datetime.now(TZ_TPE).strftime("%Y%m%d_%H%M%S")
        filename = f"{task_id}_{ts}.jsonl"
        filepath = self.trace_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"[executor] Trace written: {filepath} ({len(records)} records)")
        return filepath

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _escape(s: str) -> str:
        """Escape string for safe shell embedding"""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("\n", " ")

    @staticmethod
    def _empty_result(task_id: str, reason: str) -> dict:
        return {
            "task_id": task_id,
            "success": False,
            "total_steps": 0,
            "completed_steps": 0,
            "failed_steps": 0,
            "trace_file": "",
            "trace": [],
            "elapsed_seconds": 0,
            "error": reason,
        }


# ── 直接執行測試 ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    print("=" * 60)
    print("executor.py — Executor Test")
    print("=" * 60)

    exe = Executor(config_path)

    # Test 0: Health check
    print("\n--- Test 0: health check ---")
    alive = exe.health_check()
    print(f"Executor ready: {alive}")

    if not alive:
        print("Docker not available, switching to local mode.")
        exe.docker_enabled = False

    # Test 1: 簡單計畫
    print("\n--- Test 1: Execute simple plan ---")
    mock_plan = {
        "task_id": "T-exec-test",
        "execution_plan": json.dumps({
            "plan_id": "P-exec-test",
            "steps": [
                {
                    "step_id": 1,
                    "subtask_ref": "ST-1",
                    "action": "ls -la /tmp",
                    "skill_used": "code-execution",
                    "skill_source": "skills/active/code-execution/SKILL.md",
                    "tool_hint": "code_execution",
                    "risk_level": "low",
                    "fallback": "",
                },
                {
                    "step_id": 2,
                    "subtask_ref": "ST-2",
                    "action": "date +%Y-%m-%d",
                    "skill_used": "code-execution",
                    "skill_source": "skills/active/code-execution/SKILL.md",
                    "tool_hint": "code_execution",
                    "risk_level": "low",
                    "fallback": "",
                },
                {
                    "step_id": 3,
                    "subtask_ref": "ST-3",
                    "action": "Search for Python best practices",
                    "skill_used": "web-search",
                    "skill_source": "skills/active/web-search/SKILL.md",
                    "tool_hint": "knowledge",
                    "risk_level": "low",
                    "fallback": "",
                },
            ],
            "execution_order": "sequential",
            "estimated_total_steps": 3,
            "notes": "Simple test",
        }),
        "selected_skills": [],
    }

    result = exe.execute(mock_plan)
    print(f"\nResult: success={result['success']}, "
          f"steps={result['completed_steps']}/{result['total_steps']}, "
          f"time={result['elapsed_seconds']}s")
    print(f"Trace: {result['trace_file']}")

    for t in result["trace"]:
        print(f"  [{t['step_id']}] {t['outcome']} | cmd: {t['command'][:60]}")
        if t["stdout"].strip():
            print(f"         → {t['stdout'][:80].strip()}")

    # Test 2: 驗證 trace JSONL
    print("\n--- Test 2: Verify trace ---")
    tp = Path(result["trace_file"])
    if tp.exists():
        lines = tp.read_text(encoding="utf-8").strip().split("\n")
        valid = sum(1 for l in lines if "step_id" in l and "outcome" in l)
        print(f"  {valid}/{len(lines)} valid JSONL records ✅" if valid == len(lines) else f"  {valid}/{len(lines)} ❌")
    else:
        print("  Trace file missing ❌")