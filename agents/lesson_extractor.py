"""
lesson_extractor.py — 從失敗 trace 提取 Task-Specific Skill (W9)
================================================================
對應論文 A3 模組的失敗路徑：τ(failed) → lessons → ΔΣ
參考 MetaClaw 的失敗攔截與反思機制。

依賴：
  agents/base_extractor.py, agents/llm_client.py, agents/domain_registry.py

用法：
    from agents.lesson_extractor import LessonExtractor
    ext = LessonExtractor("config.yaml")
    result = ext.extract(failed_trace, task_description="Create file and verify")
    for lesson in result.candidates:
        print(lesson.name, lesson.root_cause)
        ext.write_candidate(lesson)
"""

import logging
from typing import Optional

from agents.base_extractor import (
    BaseExtractor,
    CandidateSkill,
    ExtractionResult,
    DOMAIN_WHITELIST,
    classify_trace,
    summarize_trace,
)
from agents.domain_registry import classify_domain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt with few-shot examples
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Failure Analysis Agent. Your job is to analyze FAILED task execution traces and extract "Lessons" — strategies to avoid the same mistakes in future similar tasks.

## Input
A failed task trace. The task did NOT complete successfully. Common failure modes:
- max_steps: agent reached step limit without calling finish
- parse_error: LLM output could not be parsed
- error: tool execution error that was never recovered

## Output Format
Respond with a JSON object ONLY. No markdown fences, no extra text:
{
  "lessons": [
    {
      "name": "kebab-case-lesson-name",
      "description": "1-2 sentences: what to avoid and what to do instead",
      "domain": ["domain-label"],
      "root_cause": "What went wrong (1 sentence)",
      "invocation_condition": "When this lesson should be recalled",
      "termination_condition": "How to know the corrective strategy worked",
      "strategy_steps": ["corrective step 1", "corrective step 2", "..."],
      "confidence": 0.0
    }
  ],
  "reasoning": "Analysis of why the task failed"
}

## Domain Labels (use ONLY these exact values)
software-engineering, research, data-analysis, content-creation, web-automation, system-ops, planning

## Rules
1. Focus on ACTIONABLE lessons, not blame.
   BAD:  "the-model-was-bad" (not actionable)
   GOOD: "validate-output-before-proceeding" (actionable)
2. Identify the ROOT CAUSE, not just symptoms.
3. The lesson should prevent the SAME failure pattern in future tasks.
4. Output 0 lessons if the failure is random or not systematic.
5. Output at most 2 lessons per trace.
6. domain values must be from the list above.
7. **Active Suppression** (v2): You will receive active skill names in the user message. If your lesson is a paraphrase of an existing active skill, output 0 lessons.
8. **Intra-response Suppression** (v2): If outputting multiple lessons, each must address a distinct root cause. Suppress lessons that differ only in wording.

## Examples

### Example 1: Agent stuck in error loop (from real trace)

Input:
- Task: "Create a file /tmp/sies_test.txt with 'hello world', then read it back"
- Termination reason: max_steps
- Trace:
  Step 1 [✗]: thought="Create the file" action=bash_execution(echo 'hello world' > /tmp/sies_test.txt\\n\\n**Observation:**...) → STDERR: "**Observation:**: command not found"
  Step 2 [✗]: thought="There was a misunderstanding, try again" action=bash_execution(echo 'hello world' > /tmp/sies_test.txt\\n\\n**Observation:**...) → same error
  Step 3 [✗]: thought="Ensure only the command is in input" action=bash_execution(echo 'hello world' > /tmp/sies_test.txt\\n\\n**Observation:**...) → same error
  [Steps 4-10: same as above, repeated 7 times]
  [max_steps reached]

Output:
{
  "lessons": [
    {
      "name": "separate-action-input-from-protocol",
      "description": "Action input must contain ONLY the executable command. Never embed protocol elements (Thought/Action/Observation headers) inside the tool input.",
      "domain": ["software-engineering", "system-ops"],
      "root_cause": "LLM embedded the entire ReAct protocol response (markdown Thought/Action/Observation markup) inside action_input, causing bash to execute markup headers as commands",
      "invocation_condition": "Agent is using bash_execution or code_execution tools",
      "termination_condition": "Action input contains only the intended command with no protocol markup",
      "strategy_steps": [
        "Before executing, verify action_input contains ONLY the command, no **Thought:**, **Action:**, **Observation:** text",
        "If a tool returns errors about unknown commands that look like protocol headers, the action_input is contaminated",
        "On repeated identical failures, change approach completely instead of retrying the same input"
      ],
      "confidence": 0.95
    }
  ],
  "reasoning": "The agent repeated the same contaminated command 10 times without adapting. This is a systematic format-confusion bug, not a random error."
}

### Example 2: Permission error without strategy change

Input:
- Task: "Read /etc/secret_config.ini and extract the database host"
- Termination reason: max_steps
- Trace:
  Step 1 [✗]: thought="Read the file" action=bash_execution(cat /etc/secret_config.ini) → "Permission denied"
  Step 2 [✗]: thought="Try with sudo" action=bash_execution(sudo cat /etc/secret_config.ini) → "sudo: not found"
  Step 3 [✗]: thought="Try Python" action=code_execution(open('/etc/secret_config.ini').read()) → "PermissionError"
  [max_steps reached]

Output:
{
  "lessons": [
    {
      "name": "handle-permission-errors-gracefully",
      "description": "When file access is denied, diagnose permissions first and explore alternatives before exhausting retries with different tools that face the same OS restriction.",
      "domain": ["system-ops"],
      "root_cause": "Agent tried multiple tools against the same permission barrier without checking if the file is accessible at all",
      "invocation_condition": "A file or resource access fails with permission-related errors",
      "termination_condition": "Found an accessible alternative or confirmed the resource is inaccessible and reported via finish",
      "strategy_steps": [
        "On first permission error, run 'ls -la <path>' to check ownership and permissions",
        "Search for readable copies: find / -name <filename> -readable 2>/dev/null",
        "If no accessible copy exists, call finish to report the limitation clearly"
      ],
      "confidence": 0.85
    }
  ],
  "reasoning": "The agent wasted 3 steps trying different tools against the same permission barrier. The lesson teaches to diagnose first."
}"""


TEMPLATE_PROMPT = """Given this FAILED task trace, fill in ONLY the values for each field.
Do not output anything else. One lesson per response.

Domain labels (use ONLY these): software-engineering, research, data-analysis, content-creation, web-automation, system-ops, planning

name: [kebab-case lesson name]
description: [1-2 sentences: what to avoid and what to do instead]
domain: [one or two from the list above, comma-separated]
root_cause: [what went wrong, 1 sentence]
invocation_condition: [when to recall this lesson]
termination_condition: [how to know the fix worked]
strategy_step_1: [corrective step 1]
strategy_step_2: [corrective step 2]
strategy_step_3: [corrective step 3]
confidence: [0.0 to 1.0]"""


# ---------------------------------------------------------------------------
# LessonExtractor
# ---------------------------------------------------------------------------

class LessonExtractor(BaseExtractor):
    """從失敗 trace 提取 Task-Specific Skill（教訓）。"""

    def __init__(self, config_path: str = "config.yaml"):
        super().__init__(config_path)

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _get_template_prompt(self) -> str:
        return TEMPLATE_PROMPT

    def _build_user_message(self, trace_summary: str, task_description: str) -> str:
        # Infer termination reason from trace summary
        if "PARSE_ERROR" in trace_summary:
            reason = "parse_error"
        elif "LLM_ERROR" in trace_summary:
            reason = "error"
        else:
            reason = "max_steps"

        parts = []
        if task_description:
            parts.append(f"## Task Description\n{task_description}")

        # v2 (W13 Day 3): inject active skills for suppression (Rule 7)
        active_skills = self._get_active_skill_names()
        if active_skills:
            skill_list = "\n".join(f"  - {name}" for name in active_skills)
            parts.append(f"## Currently Active Skills (apply Rule 7: do NOT paraphrase)\n{skill_list}")

        parts.append(f"## Execution Trace (FAILED)\nTermination reason: {reason}")
        parts.append(trace_summary)
        parts.append("Analyze this failure and extract actionable Lessons. Apply Rules 7 and 8.")
        return "\n\n".join(parts)

    def _parse_extraction_result(
        self, parsed_json: dict, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        """將 LLM JSON {"lessons": [...]} 轉為 CandidateSkill 列表。"""
        raw_lessons = parsed_json.get("lessons", [])
        if not isinstance(raw_lessons, list):
            logger.warning(f"[LessonExtractor] 'lessons' is not a list for {task_id}")
            return []

        candidates = []
        for i, s in enumerate(raw_lessons):
            if not isinstance(s, dict):
                continue

            name = s.get("name")
            if not name or not isinstance(name, str):
                logger.warning(f"[LessonExtractor] Lesson {i} missing name, skipping")
                continue

            strategy = s.get("strategy_steps", [])
            if not isinstance(strategy, list) or len(strategy) < 1:
                logger.warning(f"[LessonExtractor] Lesson '{name}' has no strategy_steps, skipping")
                continue

            root_cause = s.get("root_cause", "")
            if not root_cause:
                logger.warning(f"[LessonExtractor] Lesson '{name}' missing root_cause")
                # Don't skip — still useful without root_cause

            raw_domain = s.get("domain", [])
            if isinstance(raw_domain, str):
                raw_domain = [raw_domain]
            domain = self._validate_domain_list(raw_domain)

            candidates.append(CandidateSkill(
                name=self._to_kebab_case(name),
                description=s.get("description", name),
                type="task_specific",
                domain=domain,
                invocation_condition=s.get("invocation_condition", ""),
                termination_condition=s.get("termination_condition", ""),
                strategy_steps=[str(step) for step in strategy],
                confidence=self._clamp_confidence(s.get("confidence", 0.5)),
                source_task_id=task_id,
                root_cause=root_cause or None,
            ))

        return candidates

    def _parse_template_result(
        self, raw_text: str, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        """解析降級模板的 key: value 輸出（含 root_cause）。"""
        fields = {}
        strategy_steps = []

        for line in raw_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip().strip("[]\"'")
                if key.startswith("strategy_step"):
                    if val:
                        strategy_steps.append(val)
                else:
                    fields[key] = val

        name = fields.get("name", "")
        if not name:
            return []

        raw_domain = [d.strip() for d in fields.get("domain", "").split(",") if d.strip()]
        domain = self._validate_domain_list(raw_domain)

        return [CandidateSkill(
            name=self._to_kebab_case(name),
            description=fields.get("description", name),
            type="task_specific",
            domain=domain,
            invocation_condition=fields.get("invocation_condition", ""),
            termination_condition=fields.get("termination_condition", ""),
            strategy_steps=strategy_steps or ["(no steps extracted)"],
            confidence=self._clamp_confidence(fields.get("confidence", 0.5)),
            source_task_id=task_id,
            root_cause=fields.get("root_cause") or None,
        )]