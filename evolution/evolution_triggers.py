"""
evolution_triggers.py — 演化觸發條件偵測 (W11)
================================================
論文 Section 4.3: Evolution Triggers T1/T2/T3

  T1：任務失敗              → W11 啟用
  T2：軌跡長度超過平均 + η  → W11 啟用（≥10 trace 後）
  T3：高共現 action 子序列   → PatternRecognizer（純統計）

依賴：
  config.yaml → evolution.triggers
  memory/episodic/run_summary.jsonl

用法：
    from evolution.evolution_triggers import EvolutionTriggers
    triggers = EvolutionTriggers("config.yaml")
    result = triggers.should_trigger(run_result)
    if result.triggered:
        print(f"Φ triggered by: {result.reasons}")
"""

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TriggerResult:
    """觸發判斷的結果。"""
    triggered: bool
    reasons: list[str] = field(default_factory=list)

    t1_fired: bool = False
    t2_fired: bool = False
    t3_fired: bool = False

    t2_trace_length: Optional[int] = None
    t2_moving_avg: Optional[float] = None
    t2_threshold: Optional[float] = None
    t2_window_size: Optional[int] = None


def evolution_decision(triggers, run_result, completed_count: int,
                       every_n: int) -> TriggerResult:
    """Combine automatic conditions with the periodic fallback at both callers."""
    if every_n < 1:
        raise ValueError("evolution interval must be positive")
    decision = (triggers.should_trigger(run_result) if run_result is not None
                else TriggerResult(triggered=False))
    if completed_count > 0 and completed_count % every_n == 0:
        decision.reasons.append(f"periodic: every {every_n} tasks")
        decision.triggered = True
    return decision


# ---------------------------------------------------------------------------
# EvolutionTriggers
# ---------------------------------------------------------------------------

class EvolutionTriggers:
    """
    演化觸發條件偵測器。

    每次任務完成後由 agent_runner 或 evolution_operator 呼叫，
    判斷是否需要啟動 Φ 演化流程。
    """

    DEFAULT_WINDOW = 10
    DEFAULT_ETA = 1.5

    def __init__(self, config_path: str = "config.yaml"):
        """
        從 config.yaml 載入觸發參數。
        """
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        triggers_cfg = config.get("evolution", {}).get("triggers", {})
        self.t1_enabled = triggers_cfg.get("t1_enabled", True)
        self.t2_eta = triggers_cfg.get("t2_eta", self.DEFAULT_ETA)
        self.t3_delta = triggers_cfg.get("t3_delta", 0.3)

        self.window = triggers_cfg.get("t2_window", self.DEFAULT_WINDOW)

        self.trace_dir = Path(
            config.get("system", {}).get("trace_dir", "./memory/episodic")
        )

        logger.info(
            f"[EvolutionTriggers] T1={'on' if self.t1_enabled else 'off'}, "
            f"T2 η={self.t2_eta} window={self.window}, "
            f"T3 δ={self.t3_delta}"
        )

    # ── 公開 API ──────────────────────────────────────────

    def should_trigger(self, run_result) -> TriggerResult:
        """
        綜合判斷：任一觸發條件滿足即回傳 triggered=True。

        Args:
            run_result: agent_runner.RunResult 實例
                需要：execution_success, execution_steps, task_id
        """
        result = TriggerResult(triggered=False)

        # T1: 任務失敗
        if self.t1_enabled:
            t1 = self.check_t1(run_result)
            result.t1_fired = t1
            if t1:
                result.reasons.append("T1: task failed")

        # T2: 軌跡過長
        t2, diag = self.check_t2(run_result)
        result.t2_fired = t2
        result.t2_trace_length = diag.get("trace_length")
        result.t2_moving_avg = diag.get("moving_avg")
        result.t2_threshold = diag.get("threshold")
        result.t2_window_size = diag.get("window_size")
        if t2:
            result.reasons.append(
                f"T2: steps={diag['trace_length']} > "
                f"threshold={diag['threshold']:.1f}"
            )

        # T3: recurring action subsequences, distinct from skill-pair contraction
        t3 = self.check_t3()
        result.t3_fired = t3
        if t3:
            result.reasons.append("T3: high co-occurrence")

        result.triggered = result.t1_fired or result.t2_fired or result.t3_fired

        if result.triggered:
            logger.info(
                f"[EvolutionTriggers] TRIGGERED: {result.reasons}"
            )
        else:
            logger.debug("[EvolutionTriggers] No trigger fired")

        return result

    def check_t1(self, run_result) -> bool:
        """T1：任務失敗觸發。"""
        success = getattr(run_result, "execution_success", True)
        return not success

    def check_t2(self, run_result) -> tuple[bool, dict]:
        """
        T2：軌跡長度超標觸發。

        步驟數 > moving_avg + η × σ 時觸發。
        不足 window 條 trace → 不觸發。
        """
        current_steps = getattr(run_result, "execution_steps", 0)

        diag = {
            "trace_length": current_steps,
            "moving_avg": None,
            "threshold": None,
            "window_size": 0,
        }

        recent = self._load_recent_step_counts(
            window=self.window, exclude_task_id=getattr(run_result, "task_id", None))
        diag["window_size"] = len(recent)

        if len(recent) < self.window:
            logger.debug(
                f"[T2] Insufficient data: {len(recent)}/{self.window} traces"
            )
            return False, diag

        # 計算 moving average 和標準差
        avg = sum(recent) / len(recent)
        variance = sum((x - avg) ** 2 for x in recent) / len(recent)
        sigma = math.sqrt(variance)

        threshold = avg + self.t2_eta * sigma

        diag["moving_avg"] = round(avg, 2)
        diag["threshold"] = round(threshold, 2)

        fired = current_steps > threshold

        logger.debug(
            f"[T2] steps={current_steps}, avg={avg:.1f}, "
            f"σ={sigma:.1f}, threshold={threshold:.1f}, fired={fired}"
        )

        return fired, diag

    def check_t3(self) -> bool:
        """T3: action n-gram frequency > δ; summary/log files are not traces.

        Reuse W9's 2–4 gram recognizer and its default 100-file horizon.
        Do not change Φ-iii's skill support/lift thresholds or its corpus.
        """
        from agents.pattern_recognizer import PatternRecognizer

        recognizer = PatternRecognizer()
        traces = recognizer.load_traces_from_dir(str(self.trace_dir))
        traces = [[r for r in trace if isinstance(r, dict)
                   and isinstance(r.get("action"), str) and r["action"].strip()]
                  for trace in traces]
        traces = [trace for trace in traces if trace]
        report = recognizer.analyze(traces, min_frequency=self.t3_delta)
        # The report rounds frequency for display. Test the raw fraction.
        return any(p.count / report.total_traces > self.t3_delta
                   for p in report.patterns)

    # ── 內部工具 ──────────────────────────────────────────

    def _load_recent_step_counts(
        self,
        window: int = 10,
        domain: Optional[str] = None,
        exclude_task_id: Optional[str] = None,
    ) -> list[int]:
        """
        從 run_summary.jsonl 讀取最近 N 次任務的步驟數。
        按 timestamp 降序，取最近 window 條。

        Args:
            window: 滑動窗口大小
            domain: 若非 None，只統計該 domain 的任務（W13 用）
        """
        summary_path = self.trace_dir / "run_summary.jsonl"
        if not summary_path.exists():
            return []

        records = []
        with open(summary_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue

        # 按 timestamp 降序排列
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

        # Both callers check after AgentRunner appended the current result.
        # Compare against preceding episodes, not a baseline containing itself.
        if records and exclude_task_id and records[0].get("task_id") == exclude_task_id:
            records = records[1:]

        # domain 過濾（W11 不用，預留 W13）
        if domain is not None:
            # 需要 run_summary 有 domain 欄位，目前沒有
            # W13 加 domain 欄位後啟用
            pass

        # 取最近 window 條的步驟數
        step_counts = []
        for r in records[:window]:
            steps = r.get("total_steps", 0)
            step_counts.append(steps)

        return step_counts
