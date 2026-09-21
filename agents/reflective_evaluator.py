"""
reflective_evaluator.py — A3 反思評估器 (W10)
===============================================
A3 模組的 orchestrator，串通 W9 提取器 + W10 驗證器。

Pipeline:
  trace → classify → extract (skill or lesson) → validate → write ΔΣ

對應論文 A3 模組（Remark 1）：τ → 候選 ΔΣ

依賴：
  agents/skill_extractor.py, agents/lesson_extractor.py,
  agents/skill_validator.py, agents/base_extractor.py

用法：
    from agents.reflective_evaluator import ReflectiveEvaluator
    evaluator = ReflectiveEvaluator("config.yaml")
    result = evaluator.evaluate(trace_records, "Calculate factorial")
    print(f"Validated: {len(result.validated_candidates)}")
    print(f"Rejected:  {len(result.rejected_candidates)}")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.base_extractor import (
    CandidateSkill,
    ExtractionResult,
    classify_trace,
    summarize_trace,
)
from agents.skill_extractor import SkillExtractor
from agents.lesson_extractor import LessonExtractor
from agents.skill_validator import SkillValidator, ValidationResult, BatchValidationReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    """A3 完整評估結果。"""
    source_task_id: str
    trace_classification: str           # "success" | "failure"
    extraction_result: ExtractionResult # W9 提取器的原始輸出
    validation_report: BatchValidationReport  # W10 驗證報告

    # 便捷存取
    validated_candidates: list[CandidateSkill] = field(default_factory=list)
    rejected_candidates: list[CandidateSkill] = field(default_factory=list)
    candidates_written: list[str] = field(default_factory=list)  # 寫入的 SKILL.md 路徑

    elapsed_seconds: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# ReflectiveEvaluator
# ---------------------------------------------------------------------------

class ReflectiveEvaluator:
    """
    A3 反思評估器 — 串通提取 + 驗證的完整 pipeline。

    成功 trace → SkillExtractor → validator → ΔΣ (general skills)
    失敗 trace → LessonExtractor → validator → ΔΣ (task-specific lessons)
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        embedding_engine=None,
        vector_store=None,
    ):
        self.config_path = config_path

        # W9 提取器
        self.skill_extractor = SkillExtractor(config_path)
        self.lesson_extractor = LessonExtractor(config_path)

        # W10 驗證器（可共用 engine/store 避免重複載入）
        self.validator = SkillValidator(
            config_path,
            embedding_engine=embedding_engine,
            vector_store=vector_store,
        )

        logger.info("[ReflectiveEvaluator] initialized")

    # ── 公開 API ──────────────────────────────────────────

    def evaluate(
        self,
        trace: list[dict],
        task_description: str = "",
        write_candidates: bool = True,
    ) -> EvaluationResult:
        """
        從一條 trace 執行完整 A3 pipeline。

        Args:
            trace: Trace v2 records（來自 SimpleAgent）
            task_description: 原始任務描述（提升提取品質）
            write_candidates: 是否將通過驗證的候選寫入 skills/candidates/

        Returns:
            EvaluationResult 含驗證結果與寫入路徑
        """
        t0 = time.time()

        # Step 1: Classify trace
        classification = classify_trace(trace)
        task_id = trace[0].get("task_id", "unknown") if trace else "unknown"

        logger.info(
            f"[ReflectiveEvaluator] Evaluating trace {task_id}: "
            f"classification={classification}, steps={len(trace)}"
        )

        # Step 2: Extract candidates
        if classification == "success":
            extraction = self.skill_extractor.extract(trace, task_description)
        else:
            extraction = self.lesson_extractor.extract(trace, task_description)

        logger.info(
            f"[ReflectiveEvaluator] Extraction: "
            f"{len(extraction.candidates)} candidates, "
            f"parse_success={extraction.parse_success}, "
            f"template_mode={extraction.used_template_mode}"
        )

        if not extraction.candidates:
            elapsed = time.time() - t0
            return EvaluationResult(
                source_task_id=task_id,
                trace_classification=classification,
                extraction_result=extraction,
                validation_report=BatchValidationReport(
                    total=0, passed=0, rejected=0, results=[],
                ),
                elapsed_seconds=round(elapsed, 2),
                error=extraction.error,
            )

        # Step 3: Validate all candidates (batch with intra-dedup)
        report = self.validator.validate_batch(extraction.candidates)

        # Step 4: Separate validated vs rejected
        validated = []
        rejected = []
        written_paths = []

        for i, vr in enumerate(report.results):
            candidate = extraction.candidates[i]
            if vr.passed:
                validated.append(candidate)
                # Write to skills/candidates/
                if write_candidates:
                    extractor = (
                        self.skill_extractor
                        if classification == "success"
                        else self.lesson_extractor
                    )
                    try:
                        path = extractor.write_candidate(candidate)
                        written_paths.append(str(path))
                    except Exception as e:
                        logger.error(
                            f"[ReflectiveEvaluator] Write failed for "
                            f"{candidate.name}: {e}"
                        )
            else:
                rejected.append(candidate)
                logger.info(
                    f"[ReflectiveEvaluator] Rejected '{candidate.name}': "
                    f"{vr.rejection_reason}"
                )

        elapsed = time.time() - t0
        logger.info(
            f"[ReflectiveEvaluator] Done: "
            f"{len(validated)} validated, {len(rejected)} rejected, "
            f"{elapsed:.1f}s"
        )

        return EvaluationResult(
            source_task_id=task_id,
            trace_classification=classification,
            extraction_result=extraction,
            validation_report=report,
            validated_candidates=validated,
            rejected_candidates=rejected,
            candidates_written=written_paths,
            elapsed_seconds=round(elapsed, 2),
        )

    def evaluate_from_file(
        self,
        trace_path: str,
        task_description: str = "",
        write_candidates: bool = True,
    ) -> EvaluationResult:
        """從 JSONL trace 檔案執行完整 A3 pipeline。"""
        records = []
        path = Path(trace_path)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning(f"Skipping malformed line in {path.name}")

        if not records:
            return EvaluationResult(
                source_task_id="unknown",
                trace_classification="failure",
                extraction_result=ExtractionResult(
                    candidates=[], source_task_id="unknown",
                    trace_classification="failure", llm_calls=0,
                    parse_success=False, used_template_mode=False,
                    error=f"Empty trace file: {path.name}",
                ),
                validation_report=BatchValidationReport(
                    total=0, passed=0, rejected=0, results=[],
                ),
                error=f"Empty trace file: {path.name}",
            )

        # Filter to first task_id
        first_tid = records[0].get("task_id")
        trace = [r for r in records if r.get("task_id") == first_tid]

        return self.evaluate(trace, task_description, write_candidates)

    def evaluate_batch(
        self,
        traces: list[tuple[list[dict], str]],
        write_candidates: bool = True,
    ) -> list[EvaluationResult]:
        """
        批量評估多條 trace。

        Args:
            traces: list of (trace_records, task_description) tuples
        """
        results = []
        for i, (trace, desc) in enumerate(traces):
            logger.info(
                f"[ReflectiveEvaluator] Batch {i+1}/{len(traces)}"
            )
            try:
                r = self.evaluate(trace, desc, write_candidates)
                results.append(r)
            except Exception as e:
                logger.error(f"[ReflectiveEvaluator] Batch item {i} error: {e}")
                task_id = trace[0].get("task_id", "unknown") if trace else "unknown"
                results.append(EvaluationResult(
                    source_task_id=task_id,
                    trace_classification="failure",
                    extraction_result=ExtractionResult(
                        candidates=[], source_task_id=task_id,
                        trace_classification="failure", llm_calls=0,
                        parse_success=False, used_template_mode=False,
                        error=str(e),
                    ),
                    validation_report=BatchValidationReport(
                        total=0, passed=0, rejected=0, results=[],
                    ),
                    error=str(e),
                ))
        return results

    # ── 統計 ──────────────────────────────────────────────

    @property
    def extractor_stats(self) -> dict:
        """W9 提取器的降級統計（供 checkpoint 用）。"""
        return {
            "skill_extractor": {
                "error_rate": self.skill_extractor.error_rate,
                "template_mode": self.skill_extractor.is_template_mode,
            },
            "lesson_extractor": {
                "error_rate": self.lesson_extractor.error_rate,
                "template_mode": self.lesson_extractor.is_template_mode,
            },
        }