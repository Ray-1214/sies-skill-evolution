"""
curriculum_loop.py — W15 curriculum-driven 自動閉環背景排程
============================================================
串起 W14 子系統成一個自動循環（同步單線程，非 asyncio）：

    curriculum_agent 出題 → task_queue → agent_runner 執行
        → (每 N 題) Φ 演化 + 刷新 A2 graph cache → 回頭再出題

loop 行為：
  1. queue 有 pending → mark_running → AgentRunner.run() → mark_done/failed
     completed_count 每滿 phi_every_n_tasks → EvolutionOperator.evolve(force=True)
     → 之後 planner.reload_graph()（讓 A2 utility/centrality 看得到 Φ 新 skill）
  2. queue 空 + 距上次出題 > idle_threshold → 刷新 ability_profile（best-effort）
     → curriculum 出題 enqueue；否則 sleep(poll_interval) 再輪詢
  3. cold start：run_summary 空 → ability_profiler 回 degenerate baseline（不 crash）

W16-ready 強化：
  - Φ 後 reload_graph：閉環在單一 process 內真閉合（vector 層每 query 自重開已驗證）
  - _refresh_profile except 三路收窄：AssertionError(W13 耦合) vs 其他真 bug(印 traceback)
  - busy-spin circuit breaker：連續出 0 題達門檻即停（防無人看管空轉狂打 LLM）
  - in-flight crash 恢復：啟動時 reset_stale_running（running 殭屍 → pending）
  - durable 日誌：data/logs/curriculum_loop_<ts>.log

⚠️ 已知限制（W13 耦合）：ability_profiler.build_profile() 對 run_summary 末 50 筆
   硬斷言與 TASKS_50 位置對齊。loop 把 curriculum 題寫進同一 run_summary 後，末段
   不再對齊 → build_profile 會 AssertionError。_refresh_profile() 視為已知耦合、沿用
   既有 profile（不中斷 loop）。task-agnostic profiler 列 future work。

CLI:
    python -m agents.curriculum_loop --max-tasks 12 [--idle-threshold 0]
"""

import argparse
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

from agents.agent_runner import AgentRunner
from agents.curriculum_agent import CurriculumAgent
from agents.llm_client import LLMClient
from agents.task_queue import TaskQueue
from agents import ability_profiler
from evolution.evolution_operator import EvolutionOperator
from evolution.evolution_triggers import EvolutionTriggers, evolution_decision

logger = logging.getLogger("curriculum_loop")

TZ_TPE = timezone(timedelta(hours=8))

PROFILE_SOURCE = "live"   # ability_profiler SOURCE_FILES key → memory/episodic/run_summary.jsonl
PROFILE_PATH = "data/ability_profile_live.json"


class CurriculumLoop:
    """W15 自動閉環：出題 → 佇列 → 執行 → (每 N 題) Φ + reload graph。"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        loop_cfg = cfg.get("curriculum_loop", {})
        self.idle_threshold = loop_cfg.get("idle_threshold_seconds", 300)
        self.poll_interval = loop_cfg.get("poll_interval_seconds", 5)
        self.phi_every_n = loop_cfg.get("phi_every_n_tasks", 10)
        if self.phi_every_n < 1:
            raise ValueError("phi_every_n_tasks must be positive")
        self.triggers = EvolutionTriggers(config_path)
        self.k_per_cluster = loop_cfg.get("k_per_cluster", 1)
        self.max_consecutive_empty = loop_cfg.get("max_consecutive_empty_generations", 3)

        self.runtime_root = Path(cfg.get("system", {}).get("project_root", "."))
        self.trace_dir = Path(cfg.get("system", {}).get("trace_dir", "./memory/episodic"))
        self.profile_path = self.runtime_root / PROFILE_PATH
        self.queue = TaskQueue(str(self.runtime_root / "data/queue.jsonl"))
        self.runner = AgentRunner(config_path)

        # curriculum 出題用稍高溫度增加多樣性（不改 config 預設）
        llm = LLMClient({**cfg.get("llm", {}), "temperature": 0.6})
        self.curriculum = CurriculumAgent(
            profile_path=str(self.profile_path),
            state_path=str(self.runtime_root / "data/curriculum_state.json"),
            llm_client=llm,
            queue=self.queue,
        )

        self.completed_count = 0
        self.last_curriculum_ts = 0.0
        self._consecutive_empty = 0

    # ── 可觀測輸出（console + durable log）──

    def _emit(self, msg: str) -> None:
        print(msg)
        logger.info(msg)

    # ── profile 刷新（best-effort，except 三路收窄）──

    def _refresh_profile(self) -> None:
        try:
            profile = ability_profiler.build_profile(
                PROFILE_SOURCE, path=str(self.trace_dir / "run_summary.jsonl"), write=False)
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
            self._emit("[LOOP] ability_profile 已刷新（run_summary 與 TASKS_50 對齊）")
        except AssertionError:
            # 已知 W13 耦合：run_summary 末段非 TASKS_50 對齊
            if self.profile_path.exists():
                self._emit("[LOOP] profile 刷新跳過（AssertionError：run_summary 末段非 "
                           f"TASKS_50 對齊，W13 已知耦合）→ 沿用既有 {PROFILE_PATH}")
            else:
                raise RuntimeError(
                    f"profile 刷新失敗且無既有 profile（{PROFILE_PATH}）。"
                    f"請先跑 ability_profiler.build_profile() 產生 seed profile。"
                )
        except Exception:
            # 非預期錯誤 — 不要靜默歸因 W13 耦合
            if self.profile_path.exists():
                logger.error(
                    "[LOOP] UNEXPECTED profile refresh failure, profile 可能 stale "
                    "（沿用既有 profile 續跑，但這不是 W13 耦合，請查）",
                    exc_info=True,
                )
                self._emit("[LOOP] ⚠️ UNEXPECTED profile refresh failure（非 W13 耦合）→ "
                           "沿用既有 profile，詳見 traceback")
            else:
                raise

    # ── 出題（queue 空時呼叫）──
    #   回傳：None = idle 未到（沒嘗試）；int = 實際出題數（可能 0）

    def _maybe_generate(self) -> Optional[int]:
        now = time.time()
        if now - self.last_curriculum_ts < self.idle_threshold:
            return None
        self._emit(f"\n[LOOP] queue 空閒 ≥ {self.idle_threshold}s → 刷新 profile + curriculum 出題")
        self._refresh_profile()
        tasks = self.curriculum.generate_tasks(k_per_cluster=self.k_per_cluster)
        self.last_curriculum_ts = now
        self._emit(f"[LOOP] curriculum 出 {len(tasks)} 題並 enqueue："
                   f"{[t['cluster'] + '/L' + str(t['level']) for t in tasks]}")
        return len(tasks)

    # ── Φ 觸發 + reload A2 graph cache ──

    def _trigger_phi(self, trigger_result=None) -> None:
        self._emit(f"\n[LOOP] 已完成 {self.completed_count} 題（每 {self.phi_every_n} 觸發 Φ）"
                   f"→ EvolutionOperator.evolve(force=True)")
        # 每次建新 operator 從 disk 載入最新 graph（鏡像 W13 subprocess 隔離意圖）
        phi = EvolutionOperator(self.config_path)
        report = phi.evolve(trigger_result=trigger_result, force=True)
        self._emit(f"[LOOP] Φ done: graph {report.graph_nodes_before} → {report.graph_nodes_after} "
                   f"(inserted={len(report.inserted_skills)}, rejected={len(report.rejected_skills)}, "
                   f"macros={len(report.macro_skills_created)}, triggered_by={report.triggered_by})")
        # Φ 後刷新 A2 的 graph cache，讓後續任務的 utility/centrality 看得到新 skill
        self.runner.planner.reload_graph()
        n_nodes = self.runner.planner.graph.number_of_nodes()
        self._emit(f"[LOOP] planner graph 已刷新: {n_nodes} nodes")

    # ── 主迴圈 ──

    def run(self, max_tasks: Optional[int] = None) -> None:
        """max_tasks=None → 無限（W16 long-run）；小整數 → 跑幾題即停（smoke）。"""
        # in-flight crash 恢復：把上次中斷殘留的 running 還原為 pending
        n_reset = self.queue.reset_stale_running()
        if n_reset:
            self._emit(f"[LOOP] 重置 {n_reset} 筆殘留 running → pending（前次中斷恢復）")

        self._emit(f"[LOOP] 啟動 curriculum 自動閉環 "
                   f"(max_tasks={max_tasks}, idle_threshold={self.idle_threshold}s, "
                   f"phi_every_n={self.phi_every_n}, k_per_cluster={self.k_per_cluster}, "
                   f"max_consecutive_empty={self.max_consecutive_empty})")

        while max_tasks is None or self.completed_count < max_tasks:
            item = self.queue.peek_next()

            if item is not None:
                qid = item["queue_id"]
                task = item["task_description"]
                self._emit(f"\n[LOOP] ── task {self.completed_count + 1}"
                           f"{'/' + str(max_tasks) if max_tasks else ''}: {qid} "
                           f"({item['source']}) ──")
                self._emit(f"[LOOP]   {task[:90]}")
                self.queue.mark_running(qid)

                result = None
                try:
                    result = self.runner.run(task, cluster=item.get("cluster"))
                    ok = result.execution_success
                    n_val = (len(result.evaluation.validated_candidates)
                             if result.evaluation is not None else 0)
                    summary = (f"success={ok}, steps={result.execution_steps}, "
                               f"a3_validated={n_val}")
                    if ok:
                        self.queue.mark_done(qid, summary)
                    else:
                        self.queue.mark_failed(qid, summary)
                    self._emit(f"[LOOP]   → {'done' if ok else 'failed'}: {summary}")
                except Exception as e:
                    self.queue.mark_failed(qid, f"runner exception: {e}")
                    self._emit(f"[LOOP]   → failed (exception): {e}")

                self.completed_count += 1
                decision = evolution_decision(
                    self.triggers, result, self.completed_count, self.phi_every_n)
                if decision.triggered:
                    self._trigger_phi(decision)

            else:
                generated = self._maybe_generate()
                if generated is None:
                    # idle 門檻未到，純等待
                    time.sleep(self.poll_interval)
                elif generated == 0:
                    # 嘗試出題但 0 題 → circuit breaker
                    self._consecutive_empty += 1
                    if self._consecutive_empty >= self.max_consecutive_empty:
                        self._emit(f"\n[LOOP] 連續 {self._consecutive_empty} 次出 0 題 "
                                   f"≥ max_consecutive_empty={self.max_consecutive_empty} → 停 loop"
                                   f"（curriculum 無法產題，避免空轉狂打 LLM）")
                        break
                    time.sleep(self.poll_interval)
                else:
                    # 有產出，重置 breaker，續跑消費
                    self._consecutive_empty = 0

        self._emit(f"\n[LOOP] 停止：completed_count={self.completed_count} "
                   f"(max_tasks={max_tasks})")
        pending = [i for i in self.queue.all_items() if i["status"] == "pending"]
        self._emit(f"[LOOP] queue 剩 pending: {len(pending)}")


def _setup_logging(project_root: Path = Path(".")) -> Path:
    """root 壓到 WARNING（吞深層 agent log）；curriculum_loop logger → INFO + FileHandler。"""
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

    log_dir = project_root / "data/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_TPE).strftime("%Y%m%dT%H%M%S")
    log_path = log_dir / f"curriculum_loop_{ts}.log"

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(fh)
    logger.propagate = False   # 不往 root 冒泡（避免 WARNING root handler 重複印）
    return log_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-tasks", type=int, default=None,
                    help="跑幾題即停（預設 None = 無限 long-run）")
    ap.add_argument("--idle-threshold", type=float, default=None,
                    help="覆寫 config 的 idle_threshold_seconds（smoke 設 0）")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    loop = CurriculumLoop(args.config)
    log_path = _setup_logging(loop.runtime_root)
    print(f"[LOOP] durable log → {log_path}")

    if args.idle_threshold is not None:
        loop.idle_threshold = args.idle_threshold
    loop.run(max_tasks=args.max_tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
