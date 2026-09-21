"""
agent_runner.py — A1→A2→SimpleAgent→A3 完整閉環 (W10, W11 patch)
=================================================================
論文核心 pipeline 的首次完整串接：
  A1 decompose → A2 plan → SimpleAgent execute → A3 evaluate → ΔΣ

W11 修改：
  - RunResult 新增 skills_used 欄位
  - Stage 2 後提取 A2 選中的技能名稱
  - A3 完成後寫 run_summary.jsonl（utility_engine 資料來源）
  - TD-6: 共享 EmbeddingEngine/VectorStore singleton 注入

對應計畫書 §3.8 Phase 2：
  「agent_runner.py 串通 A1→A2→SimpleAgent→A3 完整閉環」

依賴：
  agents/task_decomposer.py (A1)
  memory_planner.py (A2)
  agents/simple_agent.py (W8 SimpleAgent)
  agents/reflective_evaluator.py (A3, W10)

用法：
    from agents.agent_runner import AgentRunner
    runner = AgentRunner("config.yaml")
    result = runner.run("Write a Python function to sort a list using merge sort")
    print(f"Success: {result.execution_success}")
    print(f"Skills used: {result.skills_used}")
    print(f"Candidates: {len(result.evaluation.validated_candidates)}")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from agents.provider_support import with_run_budget, budget_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """一次完整閉環的結果。"""
    task: str
    task_id: str

    # A1 output
    tstruct: Optional[dict] = None

    # A2 output
    plan_result: Optional[dict] = None
    skills_used: list[str] = field(default_factory=list)   # [W11] A2 選中的技能名稱
    skills_referenced: Optional[list[str]] = None  # A2 計畫聲稱引用，非執行證據
    execution_plan: Optional[dict] = None
    plan_parse_success: Optional[bool] = None  # None: A2 未提供計畫
    memory_reads: list[dict] = field(default_factory=list)
    memory_metrics: dict = field(default_factory=dict)
    skills_read: list[str] = field(default_factory=list)

    # Execution output (SimpleAgent)
    execution_success: bool = False
    execution_trace: list = field(default_factory=list)
    execution_steps: int = 0

    # A3 output
    evaluation: Optional[object] = None  # EvaluationResult

    # Meta
    elapsed_seconds: float = 0.0
    stage_timings: dict = field(default_factory=dict)
    error: Optional[str] = None
    error_stage: Optional[str] = None

    # [P1-a] 三層 success —— 見 SIES_MASTER_TRACKER §7.1
    #   pipeline_success    四段都沒拋例外（工程穩定度，不是能力）
    #   execution_success   agent 呼叫了 finish（自報，P5-0 實測 33% 是捏造的）
    #   verified_success    獨立驗證判定正確；None = 沒驗過，**絕不能當 True**
    pipeline_success: bool = False
    verified_success: Optional[bool] = None
    verification_status: str = "not_available"   # verified_independent|verified_liveness|not_available
    verify_detail: Optional[str] = None

    # [P1-a] 成本與時間（事後補不回來，長跑跑完才發現就要重跑）
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------

class AgentRunner:
    """
    A1→A2→SimpleAgent→A3 完整閉環執行器。

    每次 run() 執行一個自然語言任務，走完整個論文 pipeline，
    回傳包含所有階段輸出的 RunResult。
    """

    def __init__(self, config_path: str = "config.yaml", *, no_skills: bool = False,
                 linked_memory: bool = False):
        self.config_path = config_path
        self.no_skills = no_skills

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.linked_memory = not no_skills and (linked_memory or
            self.config.get("memory_links", {}).get("enabled", False))

        # Lazy-load 各模組（避免不需要時的 import 開銷）
        self._decomposer = None
        self._planner = None
        self._agent = None
        self._evaluator = None

        # [W11 TD-6] 共享 EmbeddingEngine / VectorStore singleton
        self._shared_embedding_engine = None
        self._shared_vector_store = None

        logger.info("[AgentRunner] initialized")

    # ── [W11 TD-6] Shared singletons ─────────────────────

    @staticmethod
    def _record_plan(result: RunResult, raw) -> None:
        """Parse observational fields without making malformed LLM JSON fatal."""
        from agents.task_decomposer import _extract_json

        result.plan_parse_success = False
        result.execution_plan = None
        result.skills_referenced = None
        try:
            plan = _extract_json(raw) if isinstance(raw, str) else raw
            if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
                return
            references = []
            for step in plan["steps"]:
                if not isinstance(step, dict) or "skill_used" not in step:
                    return
                name = step["skill_used"]
                if name is None:
                    continue
                if not isinstance(name, str):
                    return
                name = name.strip()
                if name and name.lower() not in {"none", "null", "n/a"} and name not in references:
                    references.append(name)
            result.execution_plan = plan
            result.skills_referenced = references
            result.plan_parse_success = True
        except (ValueError, TypeError, RecursionError):
            logger.warning("[AgentRunner] A2 plan could not be parsed; references unavailable")

    @property
    def shared_engine(self):
        """共享的 EmbeddingEngine 實例（lazy-load，只載入一次）。"""
        if self._shared_embedding_engine is None:
            try:
                from embedding_engine import EmbeddingEngine
                self._shared_embedding_engine = EmbeddingEngine(self.config_path)
                logger.info("[AgentRunner] Shared EmbeddingEngine loaded")
            except Exception as e:
                logger.warning(f"[AgentRunner] EmbeddingEngine load failed: {e}")
        return self._shared_embedding_engine

    @property
    def shared_store(self):
        """共享的 VectorStore 實例（lazy-load，只載入一次）。"""
        if self._shared_vector_store is None:
            try:
                from vector_store import VectorStore
                self._shared_vector_store = VectorStore(self.config_path)
                logger.info("[AgentRunner] Shared VectorStore loaded")
            except Exception as e:
                logger.warning(f"[AgentRunner] VectorStore load failed: {e}")
        return self._shared_vector_store

    # ── Lazy module loading ───────────────────────────────

    @property
    def decomposer(self):
        """A1 Task Decomposer。"""
        if self._decomposer is None:
            from agents.task_decomposer import TaskDecomposer
            self._decomposer = TaskDecomposer(self.config_path)
            logger.info("[AgentRunner] A1 TaskDecomposer loaded")
        return self._decomposer

    @property
    def planner(self):
        """A2 Memory-Guided Planner（注入共享 engine）。"""
        if self._planner is None:
            from memory_planner import MemoryPlanner
            self._planner = MemoryPlanner(
                self.config_path,
                embedding_engine=self.shared_engine,
                vector_store=self.shared_store,
                no_skills=self.no_skills,
            )
            logger.info("[AgentRunner] A2 MemoryPlanner loaded (shared engine)")
        return self._planner

    @property
    def agent(self):
        """W8 SimpleAgent (ReAct loop)。"""
        if self._agent is None:
            from agents.simple_agent import SimpleAgent
            self._agent = SimpleAgent(self.config_path, memory_enabled=self.linked_memory)
            logger.info("[AgentRunner] SimpleAgent loaded")
        return self._agent

    @property
    def evaluator(self):
        """A3 ReflectiveEvaluator（注入共享 engine）。"""
        if self._evaluator is None:
            from agents.reflective_evaluator import ReflectiveEvaluator
            self._evaluator = ReflectiveEvaluator(
                self.config_path,
                embedding_engine=self.shared_engine,
                vector_store=self.shared_store,
            )
            logger.info("[AgentRunner] A3 ReflectiveEvaluator loaded (shared engine)")
        return self._evaluator

    # ── 公開 API ──────────────────────────────────────────

    @with_run_budget
    def run(
        self,
        task: str,
        skip_a3: bool = False,
        write_candidates: bool = True,
        cluster: Optional[str] = None,
        meta: Optional[dict] = None,
        verify=None,
    ) -> RunResult:
        """
        執行一次完整閉環：A1 → A2 → SimpleAgent → A3。

        Args:
            task: 自然語言任務描述
            skip_a3: True 則跳過 A3 反思（用於 debug 執行階段）
            write_candidates: 是否將驗證通過的候選寫入 skills/candidates/

        Returns:
            RunResult 含所有階段輸出
        """
        from agents.llm_client import usage_snapshot, usage_since
        _usage0 = usage_snapshot()
        t0 = time.time()
        result = RunResult(task=task, task_id="")
        timings = {}
        # [P6′] 單一出口：A1/A2/execution 失敗原本各自 `return result`，
        # **完全跳過 _write_run_summary** —— preflight 盤出 9 條出口路徑，其中 3 條
        # 不寫紀錄。長跑的不變式是「每次 dequeue 恰好一筆」，分母對不上就沒有
        # 可信的完成率。改成標記後落到共同收尾，RunResult 契約不變。
        _aborted = False

        # ═══ Stage 1: A1 Task Decomposition ═══
        logger.info(f"[AgentRunner] === Stage 1: A1 Decompose ===")
        logger.info(f"[AgentRunner] Task: {task[:100]}...")
        try:
            t1 = time.time()
            tstruct = self.decomposer.decompose(task)
            timings["a1_decompose"] = round(time.time() - t1, 2)

            result.tstruct = tstruct
            result.task_id = tstruct.get("task_id", "unknown")
            logger.info(
                f"[AgentRunner] A1 done: {len(tstruct.get('subtasks', []))} subtasks, "
                f"{timings['a1_decompose']}s"
            )
        except Exception as e:
            result.error = str(e)
            result.error_stage = "a1_decompose"
            _aborted = True
            result.elapsed_seconds = round(time.time() - t0, 2)
            result.stage_timings = timings
            logger.error(f"[AgentRunner] A1 failed: {e}")

        # [P6′] A1/A2/execution 任一失敗就跳過後續 stage，但**仍然落到共同收尾**把紀錄寫出來。
        # 原本靠三個 early return 跳過，代價是那三條路徑完全不寫 run_summary。
        if not _aborted:
            # ═══ Stage 2: A2 Memory-Guided Planning ═══
            # （原本 A1 失敗直接 return，現在改成守衛，才走得到共同收尾的寫紀錄）
            logger.info(f"[AgentRunner] === Stage 2: A2 Plan ===")
            try:
                t2 = time.time()
                plan_result = self.planner.plan(tstruct)
                timings["a2_plan"] = round(time.time() - t2, 2)

                result.plan_result = plan_result
                self._record_plan(result, plan_result.get("execution_plan"))
                n_skills = len(plan_result.get("selected_skills", []))
                logger.info(
                    f"[AgentRunner] A2 done: {n_skills} skills selected, "
                    f"{timings['a2_plan']}s"
                )
            except Exception as e:
                result.error = str(e)
                result.error_stage = "a2_plan"
                _aborted = True
                result.elapsed_seconds = round(time.time() - t0, 2)
                result.stage_timings = timings
                logger.error(f"[AgentRunner] A2 failed: {e}")

        if not _aborted:
            # [W11] 記錄 A2 選中的技能（供 utility_engine 計算 r/f）
            # 這兩行原本裸露在所有 try 之外（preflight 指出的第 4 條路徑）
            selected = plan_result.get("selected_skills", [])
            result.skills_used = [s["name"] for s in selected if isinstance(s, dict) and "name" in s]

            # ═══ Stage 3: SimpleAgent Execution ═══
            logger.info(f"[AgentRunner] === Stage 3: SimpleAgent Execute ===")
            try:
                t3 = time.time()

                # SimpleAgent.run(task, task_id) — no context kwarg.
                # We pre-pend A2's working memory + plan to the task string
                # so the skills and plan reach the ReAct system prompt naturally.
                context = self._build_agent_context(plan_result)
                if context:
                    augmented_task = (
                        f"{context}\n\n"
                        f"---\n\n"
                        f"## Task\n{task}"
                    )
                else:
                    augmented_task = task

                # Pass A1's task_id so trace ties back to the same run
                exec_result = self.agent.run(
                    task=augmented_task,
                    task_id=result.task_id,
                )
                timings["agent_execute"] = round(time.time() - t3, 2)

                # Extract trace from result
                # SimpleAgent.run() returns dict with trace, success, etc.
                if isinstance(exec_result, dict):
                    result.execution_success = exec_result.get("success", False)
                    result.execution_trace = exec_result.get("trace", [])
                    result.execution_steps = exec_result.get("total_steps", 0)
                    result.memory_reads = exec_result.get("memory_reads", [])
                    result.memory_metrics = exec_result.get("memory_metrics", {})
                    result.skills_read = list(dict.fromkeys(
                        event["id"].removeprefix("skill:") for event in result.memory_reads
                        if event.get("id", "").startswith("skill:")))
                    if not result.task_id or result.task_id == "unknown":
                        result.task_id = exec_result.get("task_id", result.task_id)
                else:
                    # Handle object-style result
                    result.execution_success = getattr(exec_result, "success", False)
                    result.execution_trace = getattr(exec_result, "trace", [])
                    result.execution_steps = getattr(exec_result, "total_steps", 0)

                logger.info(
                    f"[AgentRunner] Execution done: "
                    f"success={result.execution_success}, "
                    f"steps={result.execution_steps}, "
                    f"{timings['agent_execute']}s"
                )
            except Exception as e:
                result.error = str(e)
                result.error_stage = "agent_execute"
                _aborted = True
                result.elapsed_seconds = round(time.time() - t0, 2)
                result.stage_timings = timings
                logger.error(f"[AgentRunner] Execution failed: {e}")

            # ═══ Stage 4: A3 Reflective Evaluation ═══
            if skip_a3:
                logger.info("[AgentRunner] Skipping A3 (skip_a3=True)")
            elif not result.execution_trace:
                logger.warning("[AgentRunner] Skipping A3: empty trace")
            else:
                logger.info(f"[AgentRunner] === Stage 4: A3 Evaluate ===")
                try:
                    t4 = time.time()
                    eval_result = self.evaluator.evaluate(
                        trace=result.execution_trace,
                        task_description=task,
                        write_candidates=write_candidates,
                    )
                    timings["a3_evaluate"] = round(time.time() - t4, 2)

                    result.evaluation = eval_result
                    n_val = len(eval_result.validated_candidates)
                    n_rej = len(eval_result.rejected_candidates)
                    logger.info(
                        f"[AgentRunner] A3 done: "
                        f"{n_val} validated, {n_rej} rejected, "
                        f"{timings['a3_evaluate']}s"
                    )
                except Exception as e:
                    result.error = str(e)
                    result.error_stage = "a3_evaluate"
                    logger.error(f"[AgentRunner] A3 failed: {e}")

        # [P1-a] 獨立驗證：由呼叫端注入。run() 不自己接沙箱，因為 workdir 與
        # input_files 的佈置在執行**之前**就要做（見 scripts/verify_runner.py）。
        # verify(result) -> {verified_success, verification_status, verify_detail}
        if callable(verify):
            try:
                v = verify(result) or {}
                result.verified_success = v.get("verified_success")
                result.verification_status = v.get("verification_status", "not_available")
                result.verify_detail = v.get("verify_detail")
            except Exception as e:  # noqa: BLE001
                # 驗證失敗不能讓整個 run 掛掉，但也**絕不能當成通過**
                result.verified_success = None
                result.verification_status = "not_available"
                result.verify_detail = f"verifier error: {type(e).__name__}: {e}"
                logger.warning(f"[AgentRunner] verifier raised: {e}")

        # 計時必須在寫 run summary 之前完成 —— 原本這兩行在 write 之後，
        # 導致 result.elapsed_seconds 在寫入當下還是 dataclass 預設的 0.0。
        result.elapsed_seconds = round(time.time() - t0, 2)
        result.stage_timings = timings
        self._finalize_metrics(result, _usage0, usage_since)

        # [W11] 追加 run summary（utility_engine 資料來源）
        try:
            self._write_run_summary(result, cluster=cluster, meta=meta)
        except Exception as e:
            logger.warning(f"[AgentRunner] Failed to write run summary: {e}")

        logger.info(
            f"[AgentRunner] === Complete === "
            f"total={result.elapsed_seconds}s, timings={timings}"
        )
        return result

    def run_batch(
        self,
        tasks: list[str],
        skip_a3: bool = False,
        write_candidates: bool = True,
    ) -> list[RunResult]:
        """批次執行多個任務。"""
        results = []
        for i, task in enumerate(tasks):
            logger.info(
                f"\n[AgentRunner] ══════ Batch {i+1}/{len(tasks)} ══════"
            )
            try:
                r = self.run(task, skip_a3=skip_a3, write_candidates=write_candidates)
                results.append(r)
            except Exception as e:
                logger.error(f"[AgentRunner] Batch task {i} fatal: {e}")
                results.append(RunResult(
                    task=task, task_id=f"batch-{i}",
                    error=str(e), error_stage="fatal",
                ))
        return results

    # ── [W11] Run summary ─────────────────────────────────

    @staticmethod
    def _stage_status(result: RunResult) -> dict:
        """四段各自的狀態。error_stage 之前的算 success，之後的算 not_started。"""
        order = ["a1_decompose", "a2_plan", "agent_execute", "a3_evaluate"]
        st = {}
        failed_at = result.error_stage if result.error_stage in order else None
        hit = False
        for k in order:
            if failed_at and k == failed_at:
                st[k] = "error"; hit = True
            elif hit:
                st[k] = "not_started"
            else:
                st[k] = "success"
        if not failed_at and result.error_stage:
            st["_other_error"] = result.error_stage
        return st

    @staticmethod
    def _finalize_metrics(result: RunResult, usage0: dict, usage_since) -> None:
        """把三層 success 的 pipeline 層、以及成本欄位填進 result。"""
        # pipeline_success：四段都沒拋例外
        result.pipeline_success = result.error_stage is None
        # tool_calls：trace 裡非 finish 的步數
        try:
            result.tool_calls = sum(
                1 for r in (result.execution_trace or [])
                if isinstance(r, dict) and r.get("action") != "finish"
            )
        except Exception:  # noqa: BLE001 — 統計欄位不該讓 run 失敗
            result.tool_calls = 0
        u = usage_since(usage0)
        result.llm_calls = u["llm_calls"]
        result.prompt_tokens = u["prompt_tokens"]
        result.completion_tokens = u["completion_tokens"]

    def _write_run_summary(self, result: RunResult, cluster: Optional[str] = None,
                           meta: Optional[dict] = None):
        """
        將一次 run 的摘要追加到 run_summary.jsonl。

        這是 utility_engine.scan_run_summaries() 的唯一資料來源。

        ⚠️ 欄位名是有承載力的：utility_engine / skill_cooccurrence / ability_profiler
           / sies_doctor / build_w13_metrics 五個消費者依賴它們。加欄位安全（全部用
           .get() 加預設值），但**不要刪或改名**。
           `success` 是 `execution_completed` 的 alias，為了讓上述消費者與 74 筆
           歷史資料繼續相容而保留。
        """
        from datetime import datetime, timezone, timedelta

        trace_dir = Path(
            self.config.get("system", {}).get("trace_dir", "./memory/episodic")
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        summary_path = trace_dir / "run_summary.jsonl"

        tz = timezone(timedelta(hours=8))
        meta = meta or {}
        _stage_status = self._stage_status
        try:
            _produced = [c.name for c in result.evaluation.validated_candidates]
        except Exception:  # noqa: BLE001 — A3 沒跑或結構不同都不該讓寫入失敗
            _produced = []
        record = {
            "task_id": result.task_id,
            "task": result.task[:200],
            "cluster": cluster,
            # ── 題目來源標籤（P5-a 出題時帶進來）──
            "domain": meta.get("domain"),
            "level": meta.get("level"),
            "path_id": meta.get("path_id"),
            "path_pos": meta.get("path_pos"),
            # ── 三層 success（§7.1）──
            # [P6′] 每一段跑到哪 —— A1 就失敗的紀錄長什麼樣要看得出來
            "stage_status": _stage_status(result),
            "pipeline_success": result.pipeline_success,
            "execution_completed": result.execution_success,
            "verified_success": result.verified_success,
            "verification_status": result.verification_status,
            "verify_detail": result.verify_detail,
            # ── 相容層：五個消費者與 74 筆歷史資料仍讀這個名字 ──
            "success": result.execution_success,
            "skills_used": result.skills_used,          # A2 檢索到的（不是實際用的，RF-6）
            "no_skills": self.no_skills,
            "linked_memory": self.linked_memory,
            "memory_reads": result.memory_reads,
            "memory_metrics": result.memory_metrics,
            "provider_budget": budget_summary(),
            "skills_read": result.skills_read,
            "skills_referenced": result.skills_referenced,
            "plan_parse_success": result.plan_parse_success,
            "execution_plan": result.execution_plan,
            "execution_plan_raw": (result.plan_result or {}).get("execution_plan"),
            # [P3-5] 這一題讓 A3 產出了哪些通過驗證的候選技能 —— provenance 邊的端點
            "produced_skills": _produced,
            "total_steps": result.execution_steps,
            # ── 成本與時間 ──
            "elapsed_seconds": result.elapsed_seconds,
            "llm_calls": result.llm_calls,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "tool_calls": result.tool_calls,
            "error_stage": result.error_stage,
            "timestamp": datetime.now(tz).isoformat(),
        }

        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info(
            f"[AgentRunner] Run summary written: "
            f"task_id={result.task_id}, skills={len(result.skills_used)}, "
            f"success={result.execution_success}"
        )

    # ── Context assembly ──────────────────────────────────

    def _build_agent_context(self, plan_result: dict) -> str:
        """
        將 A2 的計畫結果組裝為 SimpleAgent 的 context。

        包含：
        - 選中技能的摘要（含 Invocation Condition）
        - 執行計畫步驟
        """
        parts = []

        # Working memory（含技能摘要與來源標注）
        wm = plan_result.get("working_memory", "")
        if wm:
            parts.append(f"## Available Skills & Knowledge\n{wm}")

        # Execution plan
        plan = plan_result.get("execution_plan", "")
        if plan:
            parts.append(f"## Execution Plan\n{plan}")

        if not parts:
            return ""

        return "\n\n".join(parts)

    # ── 報告生成 ──────────────────────────────────────────

    @staticmethod
    def summarize_results(results: list[RunResult]) -> dict:
        """生成批次執行的摘要統計。"""
        total = len(results)
        if total == 0:
            return {"total": 0}

        exec_success = sum(1 for r in results if r.execution_success)
        a3_ran = sum(1 for r in results if r.evaluation is not None)

        total_validated = 0
        total_rejected = 0
        for r in results:
            if r.evaluation is not None:
                total_validated += len(r.evaluation.validated_candidates)
                total_rejected += len(r.evaluation.rejected_candidates)

        errors_by_stage = {}
        for r in results:
            if r.error_stage:
                errors_by_stage[r.error_stage] = (
                    errors_by_stage.get(r.error_stage, 0) + 1
                )

        avg_time = sum(r.elapsed_seconds for r in results) / total
        parse_attempts = sum(r.plan_parse_success is not None for r in results)
        parse_successes = sum(r.plan_parse_success is True for r in results)

        return {
            "total_tasks": total,
            "execution_success": exec_success,
            "execution_rate": round(exec_success / total, 2),
            "a3_evaluations": a3_ran,
            "total_validated_candidates": total_validated,
            "total_rejected_candidates": total_rejected,
            "errors_by_stage": errors_by_stage,
            "avg_elapsed_seconds": round(avg_time, 2),
            "plan_parse_attempts": parse_attempts,
            "plan_parse_successes": parse_successes,
            "plan_parse_rate": parse_successes / parse_attempts if parse_attempts else None,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    ap = argparse.ArgumentParser(description="Run the A1→A2→Executor→A3 pipeline")
    ap.add_argument("task", nargs="*")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-skills", action="store_true")
    ap.add_argument("--linked-memory", action="store_true")
    args = ap.parse_args()
    task = " ".join(args.task) or "Write a Python function that checks if a string is a palindrome"
    runner = AgentRunner(args.config, no_skills=args.no_skills, linked_memory=args.linked_memory)
    result = runner.run(task)

    print(f"\n{'='*60}")
    print(f"Task: {result.task}")
    print(f"Task ID: {result.task_id}")
    print(f"Skills used: {result.skills_used}")
    print(f"Execution: {'✓' if result.execution_success else '✗'} ({result.execution_steps} steps)")
    print(f"Total time: {result.elapsed_seconds}s")
    print(f"Stage timings: {result.stage_timings}")

    if result.evaluation:
        ev = result.evaluation
        print(f"A3 classification: {ev.trace_classification}")
        print(f"Validated candidates: {len(ev.validated_candidates)}")
        for c in ev.validated_candidates:
            print(f"  ✓ {c.name} (confidence={c.confidence}, type={c.type})")
        print(f"Rejected candidates: {len(ev.rejected_candidates)}")
        for c in ev.rejected_candidates:
            print(f"  ✗ {c.name}")

    if result.error:
        print(f"Error at {result.error_stage}: {result.error}")
