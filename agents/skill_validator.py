"""
skill_validator.py — A3 候選技能三重驗證 (W10)
================================================
三重驗證 pipeline：Schema Check → Dedup → Quality Check

對應計畫書 W10 任務 1-2：
  - schema check：必填欄位、domain 白名單、kebab-case
  - 去重：embedding cosine similarity > θdup=0.85 拒絕
  - 品質檢查：靜態分析（字串長度、同義偵測、步驟重複）

依賴：
  agents/base_extractor.py (CandidateSkill, DOMAIN_WHITELIST)
  embedding_engine.py (可選，去重用)
  vector_store.py (可選，去重用)
  config.yaml

用法：
    from agents.skill_validator import SkillValidator
    v = SkillValidator("config.yaml")
    result = v.validate(candidate_skill)
    print(result.passed, result.rejection_reason)

    # 批次驗證（含內部互查去重）
    results = v.validate_batch(candidates)
"""

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yaml
import numpy as np

from agents.base_extractor import CandidateSkill, DOMAIN_WHITELIST

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """單一候選技能的驗證結果。"""
    candidate_name: str
    passed: bool
    checks: dict                        # {"schema": True, "dedup": True, "quality": True}
    rejection_reason: Optional[str] = None
    dedup_closest_skill: Optional[str] = None
    dedup_similarity: Optional[float] = None


@dataclass
class BatchValidationReport:
    """批次驗證報告。"""
    total: int
    passed: int
    rejected: int
    results: list[ValidationResult]
    intra_batch_duplicates: list[tuple[str, str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SkillValidator
# ---------------------------------------------------------------------------

class SkillValidator:
    """
    A3 候選技能三重驗證器。

    Pipeline: Schema Check → Dedup (embedding) → Quality Check
    任一層失敗即拒絕，後續層不執行（fail-fast）。
    """

    # Schema 常數
    MIN_DESCRIPTION_LEN = 20
    MIN_STEP_LEN = 10
    MIN_STRATEGY_STEPS = 1
    MIN_NAME_LEN = 3

    # Quality 常數
    MAX_TEXT_OVERLAP = 0.80   # SequenceMatcher ratio
    GENERIC_NAMES = {
        "skill", "task", "general", "lesson", "unnamed",
        "unnamed-skill", "new-skill", "my-skill",
    }

    def __init__(
        self,
        config_path: str = "config.yaml",
        embedding_engine=None,
        vector_store=None,
    ):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # θdup from config (default 0.85)
        self.theta_dup = config.get("planner", {}).get(
            "theta_dup",
            config.get("skill_validator", {}).get("theta_dup", 0.85)
        )

        self.config_path = config_path

        # Embedding engine & vector store（lazy load for dedup）
        self._engine = embedding_engine
        self._store = vector_store
        self._engine_init_attempted = False

        logger.info(
            f"[SkillValidator] initialized, θdup={self.theta_dup}, "
            f"engine={'provided' if embedding_engine else 'lazy'}"
        )

    # ── 公開 API ──────────────────────────────────────────

    def validate(self, candidate: CandidateSkill) -> ValidationResult:
        """
        對單一候選技能執行三重驗證。
        Fail-fast：schema → dedup → quality，任一失敗即停。
        """
        checks = {"schema": False, "dedup": False, "quality": False}

        # --- Layer 1: Schema Check ---
        ok, reason = self._check_schema(candidate)
        checks["schema"] = ok
        if not ok:
            return ValidationResult(
                candidate_name=candidate.name,
                passed=False,
                checks=checks,
                rejection_reason=f"schema: {reason}",
            )

        # --- Layer 2: Dedup Check ---
        ok, reason, closest, sim = self._check_dedup(candidate)
        checks["dedup"] = ok
        if not ok:
            return ValidationResult(
                candidate_name=candidate.name,
                passed=False,
                checks=checks,
                rejection_reason=f"dedup: {reason}",
                dedup_closest_skill=closest,
                dedup_similarity=sim,
            )

        # --- Layer 3: Quality Check ---
        ok, reason = self._check_quality(candidate)
        checks["quality"] = ok
        if not ok:
            return ValidationResult(
                candidate_name=candidate.name,
                passed=False,
                checks=checks,
                rejection_reason=f"quality: {reason}",
            )

        return ValidationResult(
            candidate_name=candidate.name,
            passed=True,
            checks=checks,
            dedup_closest_skill=closest,
            dedup_similarity=sim,
        )

    def validate_batch(
        self, candidates: list[CandidateSkill]
    ) -> BatchValidationReport:
        """
        批次驗證，含內部互查去重。
        先跑每個 candidate 的三重驗證，再檢查通過者之間的相似度。
        """
        results = []
        intra_dups = []

        # Phase 1: Individual validation
        for c in candidates:
            r = self.validate(c)
            results.append(r)

        # Phase 2: Intra-batch dedup among passed candidates
        passed_indices = [i for i, r in enumerate(results) if r.passed]

        if len(passed_indices) > 1:
            self._ensure_engine()
            if self._engine is not None:
                # Embed all passed candidates
                vectors = {}
                for idx in passed_indices:
                    c = candidates[idx]
                    text = self._candidate_to_embed_text(c)
                    try:
                        vec = self._engine.embed_text(text)
                        vectors[idx] = vec
                    except Exception as e:
                        logger.warning(
                            f"[SkillValidator] Embed failed for {c.name}: {e}"
                        )

                # Pairwise comparison
                checked = set()
                for i in passed_indices:
                    for j in passed_indices:
                        if i >= j or (i, j) in checked:
                            continue
                        checked.add((i, j))
                        if i not in vectors or j not in vectors:
                            continue

                        sim = self._cosine_similarity(vectors[i], vectors[j])
                        if sim > self.theta_dup:
                            # Mark the later one as rejected
                            c_i = candidates[i]
                            c_j = candidates[j]
                            intra_dups.append((c_i.name, c_j.name, round(sim, 4)))

                            # Keep higher confidence, reject the other
                            reject_idx = j if c_i.confidence >= c_j.confidence else i
                            keep_idx = i if reject_idx == j else j
                            results[reject_idx] = ValidationResult(
                                candidate_name=candidates[reject_idx].name,
                                passed=False,
                                checks=results[reject_idx].checks,
                                rejection_reason=(
                                    f"intra-batch dedup: sim={sim:.4f} "
                                    f"with '{candidates[keep_idx].name}'"
                                ),
                                dedup_closest_skill=candidates[keep_idx].name,
                                dedup_similarity=round(sim, 4),
                            )

        passed_count = sum(1 for r in results if r.passed)
        return BatchValidationReport(
            total=len(candidates),
            passed=passed_count,
            rejected=len(candidates) - passed_count,
            results=results,
            intra_batch_duplicates=intra_dups,
        )

    # ── Layer 1: Schema Check ─────────────────────────────

    def _check_schema(self, c: CandidateSkill) -> tuple[bool, str]:
        """驗證必填欄位、格式、白名單。"""

        # name: kebab-case, min length
        if not c.name or len(c.name) < self.MIN_NAME_LEN:
            return False, f"name too short: '{c.name}' (min {self.MIN_NAME_LEN})"
        if not re.match(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$", c.name) and len(c.name) > 2:
            return False, f"name not kebab-case: '{c.name}'"

        # description
        if not c.description or len(c.description.strip()) < self.MIN_DESCRIPTION_LEN:
            return False, (
                f"description too short: {len(c.description.strip() if c.description else '')} chars "
                f"(min {self.MIN_DESCRIPTION_LEN})"
            )

        # type
        if c.type not in ("general", "task_specific"):
            return False, f"invalid type: '{c.type}' (must be general|task_specific)"

        # domain
        if not c.domain or not isinstance(c.domain, list):
            return False, "domain must be a non-empty list"
        for d in c.domain:
            if d not in DOMAIN_WHITELIST:
                return False, f"invalid domain '{d}', valid: {DOMAIN_WHITELIST}"

        # invocation_condition
        if not c.invocation_condition or not c.invocation_condition.strip():
            return False, "invocation_condition is empty"

        # termination_condition
        if not c.termination_condition or not c.termination_condition.strip():
            return False, "termination_condition is empty"

        # strategy_steps
        if (not c.strategy_steps
                or not isinstance(c.strategy_steps, list)
                or len(c.strategy_steps) < self.MIN_STRATEGY_STEPS):
            return False, (
                f"strategy_steps needs ≥{self.MIN_STRATEGY_STEPS} steps, "
                f"got {len(c.strategy_steps) if c.strategy_steps else 0}"
            )
        for i, step in enumerate(c.strategy_steps):
            if not step or len(step.strip()) < self.MIN_STEP_LEN:
                return False, (
                    f"strategy_step[{i}] too short: "
                    f"'{step[:30] if step else ''}' (min {self.MIN_STEP_LEN} chars)"
                )

        # confidence
        if not (0.0 <= c.confidence <= 1.0):
            return False, f"confidence out of range: {c.confidence}"

        return True, ""

    # ── Layer 2: Dedup Check ──────────────────────────────

    def _check_dedup(
        self, c: CandidateSkill
    ) -> tuple[bool, str, Optional[str], Optional[float]]:
        """
        Embedding 去重：候選 vs skills/active/ 既有技能。
        回傳 (passed, reason, closest_name, similarity)。
        """
        self._ensure_engine()

        if self._engine is None or self._store is None:
            logger.info(
                "[SkillValidator] Embedding engine not available, "
                "skipping dedup check"
            )
            return True, "", None, None

        try:
            text = self._candidate_to_embed_text(c)
            vec = self._engine.embed_text(text)

            # Query existing skills in LanceDB
            results = self._store.query(vec, top_k=1)

            if not results:
                return True, "", None, None

            closest = results[0]
            l2_dist = closest.get("score", closest.get("_distance", 999.0))

            # [P2-2] LanceDB 的 `_distance` 在 l2 metric 下回傳的**已經是**
            # 平方距離 d = 2 - 2·cos（向量已正規化）。原本的 `1 - d²/2` 又平方
            # 一次，使 `sim > 0.80` 實際等價於真 cos > 0.684 —— 所有 log 與
            # checkpoint 裡的 θdup 數字都被膨脹過。正確式是 1 - d/2。
            # 實測：d=0.121436 → 真 cos=0.9395，舊式回報 0.9926。
            sim = 1.0 - l2_dist / 2.0
            sim = max(0.0, min(1.0, sim))  # clamp

            closest_name = closest.get("name", "unknown")

            if sim > self.theta_dup:
                return (
                    False,
                    f"too similar to existing skill '{closest_name}' "
                    f"(sim={sim:.4f} > θdup={self.theta_dup})",
                    closest_name,
                    round(sim, 4),
                )

            return True, "", closest_name, round(sim, 4)

        except Exception as e:
            logger.warning(f"[SkillValidator] Dedup check error: {e}")
            # Fail-open: if dedup check errors, pass the candidate
            return True, "", None, None

    # ── Layer 3: Quality Check ────────────────────────────

    def _check_quality(self, c: CandidateSkill) -> tuple[bool, str]:
        """靜態品質分析。"""

        # Q1: Name not generic
        if c.name.lower() in self.GENERIC_NAMES:
            return False, f"name too generic: '{c.name}'"

        # Q2: invocation_condition ≉ description
        ratio_ic = SequenceMatcher(
            None,
            c.invocation_condition.lower().strip(),
            c.description.lower().strip(),
        ).ratio()
        if ratio_ic > self.MAX_TEXT_OVERLAP:
            return False, (
                f"invocation_condition too similar to description "
                f"(overlap={ratio_ic:.2f} > {self.MAX_TEXT_OVERLAP})"
            )

        # Q3: termination_condition ≉ description
        ratio_tc = SequenceMatcher(
            None,
            c.termination_condition.lower().strip(),
            c.description.lower().strip(),
        ).ratio()
        if ratio_tc > self.MAX_TEXT_OVERLAP:
            return False, (
                f"termination_condition too similar to description "
                f"(overlap={ratio_tc:.2f} > {self.MAX_TEXT_OVERLAP})"
            )

        # Q4: Strategy steps not all identical
        if len(c.strategy_steps) > 1:
            unique = set(s.strip().lower() for s in c.strategy_steps)
            if len(unique) == 1:
                return False, "all strategy_steps are identical"

        # Q5: invocation_condition ≉ termination_condition
        ratio_it = SequenceMatcher(
            None,
            c.invocation_condition.lower().strip(),
            c.termination_condition.lower().strip(),
        ).ratio()
        if ratio_it > self.MAX_TEXT_OVERLAP:
            return False, (
                f"invocation_condition ≈ termination_condition "
                f"(overlap={ratio_it:.2f} > {self.MAX_TEXT_OVERLAP})"
            )

        return True, ""

    # ── 內部工具 ──────────────────────────────────────────

    def _ensure_engine(self):
        """Lazy-load EmbeddingEngine 和 VectorStore。"""
        if self._engine_init_attempted:
            return
        self._engine_init_attempted = True

        if self._engine is None:
            try:
                from embedding_engine import EmbeddingEngine
                self._engine = EmbeddingEngine(self.config_path)
                logger.info("[SkillValidator] EmbeddingEngine loaded")
            except Exception as e:
                logger.warning(f"[SkillValidator] EmbeddingEngine load failed: {e}")
                self._engine = None

        if self._store is None:
            try:
                from vector_store import VectorStore
                self._store = VectorStore(self.config_path)
                logger.info("[SkillValidator] VectorStore loaded")
            except Exception as e:
                logger.warning(f"[SkillValidator] VectorStore load failed: {e}")
                self._store = None

    @staticmethod
    def _candidate_to_embed_text(c: CandidateSkill) -> str:
        """
        將候選技能轉為可 embed 的文字。
        對齊 embedding_engine.py 的擷取策略：
        name + description + strategy 前 200 字。
        """
        strategy_text = " ".join(c.strategy_steps)[:200]
        return f"{c.name} {c.description} {strategy_text}"

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """計算兩個（已正規化）向量的 cosine similarity。"""
        dot = float(np.dot(a, b))
        # Vectors should already be normalized, but clamp just in case
        return max(0.0, min(1.0, dot))