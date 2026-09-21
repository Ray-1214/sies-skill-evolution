"""
base_extractor.py — A3 提取器共用基底 (W9)
=============================================
SkillExtractor 和 LessonExtractor 的共用邏輯：
  - LLM 呼叫（Tier B config）
  - strip_think 過濾
  - JSON parse（三層容錯，同 simple_agent.py 策略）
  - Trace 摘要化（context window 保護 + 重複偵測）
  - SKILL.md 生成（§7.1 三方兼容格式）
  - 模板化降級（§6.3 fallback）
  - 候選技能寫入 skills/candidates/

W10 的 skill_validator / reflective_evaluator 可直接 import：
  from agents.base_extractor import classify_trace, strip_think, parse_json_output

依賴：
  agents/llm_client.py, agents/domain_registry.py, config.yaml (llm_tier_b)
"""

import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

from agents.llm_client import LLMClient
from agents.domain_registry import VALID_DOMAINS, validate_domain, classify_domain

logger = logging.getLogger(__name__)

TZ_TPE = timezone(timedelta(hours=8))

# Domain 白名單（來自 domain_registry.py，7 categories）
# software-engineering, research, data-analysis, content-creation,
# web-automation, system-ops, planning
DOMAIN_WHITELIST = sorted(VALID_DOMAINS)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CandidateSkill:
    """
    A3 產出的候選技能，尚未通過 W10 驗證。

    對應論文 Definition 2（σ = (Iσ, βσ, πσ, ...)）。
    type="general" 來自成功 trace（SkillExtractor），
    type="task_specific" 來自失敗 trace（LessonExtractor）。
    """
    name: str                           # kebab-case
    description: str                    # 1-2 句功能描述
    type: str                           # "general" | "task_specific"
    domain: list[str]                   # domain_registry 7 categories 子集
    invocation_condition: str           # Iσ
    termination_condition: str          # βσ
    strategy_steps: list[str]           # πσ
    confidence: float                   # LLM 自評 0.0-1.0
    source_task_id: str                 # 來源 trace 的 task_id
    source_trace_summary: str = ""      # 來源 trace 精簡摘要
    raw_llm_output: str = ""            # debug 用
    root_cause: Optional[str] = None    # 僅 lesson


@dataclass
class ExtractionResult:
    """單次提取操作的完整結果（含 metadata 供 checkpoint 量測）。"""
    candidates: list[CandidateSkill]
    source_task_id: str
    trace_classification: str       # "success" | "failure"
    llm_calls: int                  # 含 retry
    parse_success: bool             # JSON parse 最終是否成功
    used_template_mode: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Utility functions（可被 W10 模組直接 import）
# ---------------------------------------------------------------------------

def classify_trace(trace: list[dict]) -> str:
    """
    判斷一條 trace 成功或失敗。
    最後一步 action=="finish" 且 success==True → "success"，否則 "failure"。
    """
    if not trace:
        return "failure"
    last = trace[-1]
    if last.get("action") == "finish" and last.get("success"):
        return "success"
    return "failure"


def strip_think(text: str) -> str:
    """移除 Gemma 的 <think>...</think> reasoning blocks。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def parse_json_output(text: str) -> Optional[dict]:
    """
    三層容錯 JSON parse（與 simple_agent.py _parse_json 同策略）。
    Layer 1: 直接 json.loads
    Layer 2: 去 markdown fence
    Layer 3: 找第一個 { ... }
    """
    text = strip_think(text)

    # Layer 1
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Layer 2
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            pass

    # Layer 3
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def summarize_trace(trace: list[dict], max_chars: int = 3000) -> str:
    """
    將 Trace v2 records 壓縮成文字摘要。
    含重複偵測：連續相同 action+action_input 的步驟合併顯示。
    """
    if not trace:
        return "(empty trace)"

    lines = []
    prev_sig = None
    repeat_start = -1
    repeat_count = 0

    def _format_step(r: dict) -> str:
        status = "✓" if r.get("success") else "✗"
        thought_short = r.get("thought", "")[:150]
        ai_short = r.get("action_input", "")[:200]
        if len(r.get("action_input", "")) > 200:
            ai_short += "...[truncated]"
        obs_short = r.get("observation", "")[:200]
        if len(r.get("observation", "")) > 200:
            obs_short += "...[truncated]"
        return (
            f"Step {r.get('step', '?')} [{status}]: "
            f"thought=\"{thought_short}\" "
            f"action={r.get('action', '?')}({ai_short}) "
            f"→ {obs_short}"
        )

    def _flush_repeat():
        nonlocal repeat_count, repeat_start
        if repeat_count > 0:
            lines.append(
                f"  [Steps {repeat_start+1}-{repeat_start+repeat_count}: "
                f"same as above, repeated {repeat_count} times]"
            )
        repeat_count = 0
        repeat_start = -1

    for i, r in enumerate(trace):
        # Signature for repeat detection: action + first 100 chars of action_input
        sig = (r.get("action", ""), r.get("action_input", "")[:100])

        if sig == prev_sig:
            if repeat_count == 0:
                repeat_start = i
            repeat_count += 1
        else:
            _flush_repeat()
            lines.append(_format_step(r))
            prev_sig = sig

    _flush_repeat()

    summary = "\n".join(lines)

    # If still too long, keep first 2 + last 2 steps
    if len(summary) > max_chars and len(lines) > 4:
        keep_first = 2
        keep_last = 2
        mid = f"\n  ... [{len(lines) - keep_first - keep_last} steps omitted] ...\n"
        summary = "\n".join(lines[:keep_first]) + mid + "\n".join(lines[-keep_last:])

    return summary[:max_chars]


# ---------------------------------------------------------------------------
# BaseExtractor
# ---------------------------------------------------------------------------

class BaseExtractor:
    """
    SkillExtractor 和 LessonExtractor 的共用基底。

    子類別需實作：
      _get_system_prompt(), _get_template_prompt(),
      _build_user_message(), _parse_extraction_result(),
      _parse_template_result()
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Tier B LLM（fallback 到 llm）
        tier_b_cfg = config.get("llm_tier_b", config.get("llm", {}))
        self.llm = LLMClient(tier_b_cfg)

        # 候選技能輸出目錄
        project_root = Path(config.get("system", {}).get("project_root", "."))
        self.candidates_dir = project_root / "skills" / "candidates"
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

        # Trace 目錄
        self.trace_dir = Path(
            config.get("system", {}).get("trace_dir", "./memory/episodic")
        )

        # 降級追蹤
        self._fail_count = 0
        self._total_count = 0
        self._use_template_mode = False

        logger.info(
            f"[{self.__class__.__name__}] initialized, "
            f"candidates_dir={self.candidates_dir}, "
            f"template_mode={self._use_template_mode}"
        )

    # ── 子類別必須實作 ─────────────────────────────────────

    def _get_system_prompt(self) -> str:
        raise NotImplementedError

    def _get_template_prompt(self) -> str:
        raise NotImplementedError

    def _build_user_message(self, trace_summary: str, task_description: str) -> str:
        raise NotImplementedError

    def _get_active_skill_names(self) -> list[str]:
        """v2 (W13 Day 3 A3-v2 prompt): Return current active skill names for prompt suppression.

        從 fs scan skills/active/**/SKILL.md，取 parent dir name（kebab-case skill name）。
        用於 SYSTEM_PROMPT 新規則 7（Active Suppression）。
        """
        active_dir = self.candidates_dir.parent / "active"  # skills/active/
        if not active_dir.exists():
            return []
        names = sorted({p.parent.name for p in active_dir.glob("**/SKILL.md")})
        return names

    def _parse_extraction_result(
        self, parsed_json: dict, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        raise NotImplementedError

    def _parse_template_result(
        self, raw_text: str, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        raise NotImplementedError

    # ── 公開 API ──────────────────────────────────────────

    def extract(
        self,
        trace: list[dict],
        task_description: str = "",
    ) -> ExtractionResult:
        """從一條 trace 提取候選技能。"""
        task_id = trace[0].get("task_id", "unknown") if trace else "unknown"
        classification = classify_trace(trace)
        trace_summary = summarize_trace(trace)
        llm_calls = 0
        used_template = False

        # Determine mode
        use_template = self._use_template_mode

        if not use_template:
            # === Normal mode ===
            system_prompt = self._get_system_prompt()
            user_msg = self._build_user_message(trace_summary, task_description)

            raw, calls = self._call_llm_with_retry(system_prompt, user_msg)
            llm_calls += calls

            if raw is not None:
                parsed = parse_json_output(raw)
                if parsed is not None:
                    candidates = self._parse_extraction_result(parsed, trace, task_id)
                    for c in candidates:
                        c.source_trace_summary = trace_summary[:500]
                        c.raw_llm_output = raw[:1000]
                    self._total_count += 1
                    return ExtractionResult(
                        candidates=candidates,
                        source_task_id=task_id,
                        trace_classification=classification,
                        llm_calls=llm_calls,
                        parse_success=True,
                        used_template_mode=False,
                    )

            # Normal mode failed → try template as one-time fallback
            logger.warning(
                f"[{self.__class__.__name__}] Normal mode failed for {task_id}, "
                f"trying template fallback"
            )
            use_template = True
            self._fail_count += 1
            self._total_count += 1

            # Check if should permanently switch
            if self._total_count >= 5 and self.error_rate > 0.4:
                logger.warning(
                    f"[{self.__class__.__name__}] Error rate {self.error_rate:.0%} > 40%, "
                    f"permanently switching to template mode"
                )
                self._use_template_mode = True

        if use_template:
            # === Template mode ===
            used_template = True
            system_prompt = self._get_template_prompt()
            user_msg = self._build_user_message(trace_summary, task_description)

            raw, calls = self._call_llm_with_retry(system_prompt, user_msg)
            llm_calls += calls

            if raw is not None:
                candidates = self._parse_template_result(raw, trace, task_id)
                for c in candidates:
                    c.source_trace_summary = trace_summary[:500]
                    c.raw_llm_output = raw[:1000]
                if candidates:
                    return ExtractionResult(
                        candidates=candidates,
                        source_task_id=task_id,
                        trace_classification=classification,
                        llm_calls=llm_calls,
                        parse_success=True,
                        used_template_mode=True,
                    )

        # Both modes failed
        return ExtractionResult(
            candidates=[],
            source_task_id=task_id,
            trace_classification=classification,
            llm_calls=llm_calls,
            parse_success=False,
            used_template_mode=used_template,
            error="Both normal and template extraction failed",
        )

    def extract_from_file(self, trace_path: str) -> ExtractionResult:
        """從 JSONL 檔案讀取 trace 並提取。"""
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
            return ExtractionResult(
                candidates=[], source_task_id="unknown",
                trace_classification="failure", llm_calls=0,
                parse_success=False, used_template_mode=False,
                error=f"Empty or unreadable trace file: {path.name}",
            )

        # Filter to first task_id
        first_tid = records[0].get("task_id")
        trace = [r for r in records if r.get("task_id") == first_tid]

        # Try to get task description from trace context
        task_desc = ""
        # (task description isn't stored in Trace v2 records;
        #  caller can provide it via extract() directly if needed)

        return self.extract(trace, task_desc)

    def extract_batch(
        self, trace_dir: str = "", max_traces: int = 10
    ) -> list[ExtractionResult]:
        """批量處理目錄下的 trace 檔案。"""
        scan_dir = Path(trace_dir) if trace_dir else self.trace_dir
        files = sorted(
            scan_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_traces]

        results = []
        for f in files:
            logger.info(f"[{self.__class__.__name__}] Processing {f.name}")
            try:
                r = self.extract_from_file(str(f))
                results.append(r)
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] Error processing {f.name}: {e}")
                results.append(ExtractionResult(
                    candidates=[], source_task_id=f.stem,
                    trace_classification="failure", llm_calls=0,
                    parse_success=False, used_template_mode=False,
                    error=str(e),
                ))
        return results

    # ── SKILL.md 生成 ─────────────────────────────────────

    def to_skill_md(self, skill: CandidateSkill) -> str:
        """將 CandidateSkill 轉換為 §7.1 三方兼容 SKILL.md 字串。"""
        frontmatter = {
            # Agent-Zero 標準欄位
            "name": skill.name,
            "description": skill.description,
            "version": "1",
            "author": "SIES-A3",
            "tags": skill.domain,
            # 論文 Definition 2 擴展欄位
            "tier": "active",
            "utility": 0.5,
            "frequency": 0,
            "reinforcement": 0.0,
            "cost": 0.0,
            "domain": skill.domain,
            "type": skill.type,
            "linked_nodes": [],
            "skill_source": "a3_extraction",
            "source_task_id": skill.source_task_id,
        }

        fm_str = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # Build markdown body
        body_parts = [
            f"## Description\n\n{skill.description}\n",
            f"## Invocation Condition (Iσ)\n\n- {skill.invocation_condition}\n",
            f"## Termination Condition (βσ)\n\n- {skill.termination_condition}\n",
            "## Strategy Steps (πσ)\n",
        ]
        for i, step in enumerate(skill.strategy_steps, 1):
            body_parts.append(f"{i}. {step}")
        body_parts.append("")

        # Root cause section for lessons
        if skill.root_cause:
            body_parts.append(f"## Root Cause\n\n{skill.root_cause}\n")

        body_parts.append(
            f"## Source\n\n"
            f"- Extracted from trace: {skill.source_task_id}\n"
            f"- Extraction method: A3 {skill.type} extraction\n"
            f"- Confidence: {skill.confidence}\n"
        )

        body = "\n".join(body_parts)
        return f"---\n{fm_str}---\n\n{body}"

    def write_candidate(self, skill: CandidateSkill) -> Path:
        """寫入 skills/candidates/{name}/SKILL.md。"""
        skill_dir = self.candidates_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        filepath = skill_dir / "SKILL.md"

        content = self.to_skill_md(skill)
        filepath.write_text(content, encoding="utf-8")

        logger.info(f"[{self.__class__.__name__}] Wrote candidate: {filepath}")
        return filepath

    # ── 降級管理 ──────────────────────────────────────────

    @property
    def error_rate(self) -> float:
        if self._total_count == 0:
            return 0.0
        return self._fail_count / self._total_count

    @property
    def is_template_mode(self) -> bool:
        return self._use_template_mode

    def reset_stats(self) -> None:
        self._fail_count = 0
        self._total_count = 0
        self._use_template_mode = False

    # ── 內部 LLM 呼叫 ────────────────────────────────────

    def _call_llm_with_retry(
        self, system_prompt: str, user_message: str, max_retries: int = 2
    ) -> tuple[Optional[str], int]:
        """
        呼叫 LLM，失敗時 retry（附格式提示）。
        Returns: (stripped raw text or None, call count)
        """
        calls = 0

        for attempt in range(1, max_retries + 1):
            calls += 1
            try:
                response = self.llm.chat(system_prompt, user_message)
                raw = strip_think(response.content)
                if raw:
                    return raw, calls
                logger.warning(f"[{self.__class__.__name__}] Empty LLM response, attempt {attempt}")
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] LLM error attempt {attempt}: {e}")

            # Append format reminder for retry
            if attempt < max_retries:
                user_message = (
                    user_message
                    + "\n\nIMPORTANT: Your previous response was empty or malformed. "
                    "You MUST respond with a valid JSON object only. No extra text."
                )

        return None, calls

    # ── 共用驗證 ──────────────────────────────────────────

    @staticmethod
    def _validate_domain_list(domains: list) -> list[str]:
        """
        驗證 domain 列表，無效的移除，空則用 classify_domain fallback。
        使用 domain_registry.py 的白名單。
        """
        if not isinstance(domains, list):
            return ["software-engineering"]
        valid = [d for d in domains if validate_domain(d)]
        if not valid:
            return ["software-engineering"]
        return valid

    @staticmethod
    def _to_kebab_case(name: str) -> str:
        """確保 name 是 kebab-case。"""
        name = re.sub(r"[^a-zA-Z0-9\-]", "-", name.lower().strip())
        name = re.sub(r"-+", "-", name).strip("-")
        return name or "unnamed-skill"

    @staticmethod
    def _clamp_confidence(val) -> float:
        """Clamp confidence to 0.0-1.0。"""
        try:
            v = float(val)
            return max(0.0, min(1.0, v))
        except (TypeError, ValueError):
            return 0.5