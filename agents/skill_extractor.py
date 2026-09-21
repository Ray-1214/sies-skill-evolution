"""
skill_extractor.py — 從成功 trace 提取 General Skill (W9)
==========================================================
對應論文 A3 模組：τ → ΔΣ（候選技能）
參考 SkillRL 的 skill distillation prompt。

依賴：
  agents/base_extractor.py, agents/llm_client.py, agents/domain_registry.py

用法：
    from agents.skill_extractor import SkillExtractor
    ext = SkillExtractor("config.yaml")
    result = ext.extract(trace_records, task_description="Calculate factorial")
    for skill in result.candidates:
        print(skill.name, skill.confidence)
        ext.write_candidate(skill)
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

SYSTEM_PROMPT = """You are a Skill Extraction Agent. Your job is to analyze successful task execution traces and extract reusable "General Skills" — abstract strategies that can be applied to similar future tasks.

## Input
You will receive a task execution trace with these fields per step:
- step: step number
- thought: the agent's reasoning
- action: tool used (code_execution / bash_execution / finish)
- observation: tool output (may be truncated)
- success: whether the step succeeded (✓/✗)

## Output Format
Respond with a JSON object ONLY. No markdown fences, no extra text, no explanation outside the JSON:
{
  "skills": [
    {
      "name": "kebab-case-name",
      "description": "1-2 sentence description of the reusable skill",
      "domain": ["domain-label"],
      "invocation_condition": "When to use this skill",
      "termination_condition": "When this skill is complete",
      "strategy_steps": ["step 1", "step 2", "..."],
      "confidence": 0.0
    }
  ],
  "reasoning": "Brief explanation of why these skills are reusable"
}

## Domain Labels (use ONLY these exact values)
software-engineering, research, data-analysis, content-creation, web-automation, system-ops, planning

## Rules
1. Extract REUSABLE patterns, not task-specific steps.
   BAD:  "calculate-factorial" (too specific to one task)
   GOOD: "iterative-algorithm-with-validation" (reusable across tasks)
2. Each skill should be applicable to at least 3 different tasks.
3. Focus on the STRATEGY (how), not the CONTENT (what).
4. Output 0 skills if the trace is too simple or trivial (e.g., single-step finish).
5. Output at most 3 skills per trace.
6. domain values must be from the list above. Use 1-2 domains per skill.
7. **Active Suppression** (v2): You will receive a list of ACTIVE skill names in the user message (under "## Currently Active Skills"). If your candidate skill is a paraphrase of any active skill — same underlying strategy with different wording — DO NOT include it. Examples of paraphrase to suppress:
   - Active: "iterative-algorithm-with-validation" → Candidate "step-by-step-algorithm-implementation" (paraphrase, suppress)
   - Active: "test-driven-implementation-lifecycle" → Candidate "test-driven-debugging-cycle" (paraphrase, suppress)
   - Active: "regex-based-delimiter-parsing" → Candidate "regex-based-pattern-extraction" (paraphrase, suppress)
   When in doubt about whether a candidate paraphrases an active skill, prefer to suppress (output 0 skills for that pattern).
8. **Intra-response Suppression** (v2): If you output multiple skills in one response, each must be semantically distinct. If two of your candidates differ only in naming or wording but share the same strategy, output only ONE (the more general one).

## Examples

### Example 1: Multi-step code task

Input:
- Task: "Write a function to find all prime numbers up to N using Sieve of Eratosthenes"
- Trace:
  Step 1 [✓]: thought="I'll implement the sieve algorithm" action=code_execution → correct primes output
  Step 2 [✓]: thought="Test with N=30 and verify" action=code_execution → "2, 3, 5, 7, 11, 13..."
  Step 3 [✓]: thought="Add edge cases: N=0, N=1, N=2" action=code_execution → all pass
  Step 4 [✓]: action=finish → "Function works correctly for all test cases"

Output:
{
  "skills": [
    {
      "name": "iterative-algorithm-with-validation",
      "description": "Implement a known algorithm step-by-step: write core logic, test with small verifiable input, then handle edge cases before finishing.",
      "domain": ["software-engineering"],
      "invocation_condition": "Task requires implementing a well-known algorithm or data structure",
      "termination_condition": "Algorithm passes both standard and edge case tests",
      "strategy_steps": [
        "Identify the algorithm and implement the basic version",
        "Test with a small, manually verifiable input",
        "Add edge case handling (empty, boundary, negative values)",
        "Verify all cases pass before calling finish"
      ],
      "confidence": 0.85
    }
  ],
  "reasoning": "The trace shows a clear implement-test-edge_case-finish pattern that generalizes to any algorithm implementation task."
}

### Example 2: System analysis task

Input:
- Task: "Find the top 5 most frequent error types in /var/log/syslog"
- Trace:
  Step 1 [✓]: thought="Check file exists and size" action=bash_execution(ls -la /var/log/syslog) → "12MB"
  Step 2 [✓]: thought="Large file, use grep+sort+uniq pipeline" action=bash_execution(grep -i error ... | sort | uniq -c | sort -rn | head -5) → top 5 errors
  Step 3 [✓]: action=finish → formatted table

Output:
{
  "skills": [
    {
      "name": "large-file-analysis-pipeline",
      "description": "Analyze large text files by first checking properties, then using streaming shell pipelines for filtering and aggregation.",
      "domain": ["data-analysis", "system-ops"],
      "invocation_condition": "Task requires extracting patterns or statistics from text-based files",
      "termination_condition": "Relevant patterns extracted and presented in structured format",
      "strategy_steps": [
        "Check file existence, size, and format before processing",
        "For large files, use streaming shell tools (grep/awk/sed) instead of loading into memory",
        "Chain filters: grep for relevant lines, sort, uniq -c for counting",
        "Format and present results before finishing"
      ],
      "confidence": 0.80
    }
  ],
  "reasoning": "The check-first then stream-process pattern applies to any large file analysis."
}

### Example 3: Trivial task → 0 skills

Input:
- Task: "What is 2+2?"
- Trace:
  Step 1 [✓]: action=finish → "4"

Output:
{
  "skills": [],
  "reasoning": "Single-step trivial task has no extractable reusable pattern."
}

### Example 4: Active suppression (v2)

Input:
- Task: "Implement merge sort with edge case tests"
- Currently Active Skills:
  - algorithm-implementation-with-validation-suite
  - iterative-logic-implementation-with-verification
  - test-driven-implementation-lifecycle
- Trace:
  Step 1 [✓]: implement merge sort
  Step 2 [✓]: test with [3,1,4,1,5], [] empty, [1] single
  Step 3 [✓]: finish

Output:
{
  "skills": [],
  "reasoning": "The pattern (implement algorithm → test edge cases → verify → finish) is already captured by active skills 'algorithm-implementation-with-validation-suite' and 'test-driven-implementation-lifecycle'. Suppressed by Rule 7."
}"""


TEMPLATE_PROMPT = """Given this successful task trace, fill in ONLY the values for each field.
Do not output anything else. One skill per response.

Domain labels (use ONLY these): software-engineering, research, data-analysis, content-creation, web-automation, system-ops, planning

name: [kebab-case name for the reusable skill pattern]
description: [1-2 sentences describing the reusable strategy]
domain: [one or two from the list above, comma-separated]
invocation_condition: [when to use this skill]
termination_condition: [when the skill is complete]
strategy_step_1: [first step of the strategy]
strategy_step_2: [second step]
strategy_step_3: [third step]
confidence: [0.0 to 1.0]"""


# ---------------------------------------------------------------------------
# SkillExtractor
# ---------------------------------------------------------------------------

class SkillExtractor(BaseExtractor):
    """從成功 trace 提取 General Skill。"""

    def __init__(self, config_path: str = "config.yaml"):
        super().__init__(config_path)

    def _get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _get_template_prompt(self) -> str:
        return TEMPLATE_PROMPT

    def _build_user_message(self, trace_summary: str, task_description: str) -> str:
        parts = []
        if task_description:
            parts.append(f"## Task Description\n{task_description}")

        # v2 (W13 Day 3): inject active skills for suppression (Rule 7)
        active_skills = self._get_active_skill_names()
        if active_skills:
            skill_list = "\n".join(f"  - {name}" for name in active_skills)
            parts.append(f"## Currently Active Skills (apply Rule 7: do NOT paraphrase any of these)\n{skill_list}")

        parts.append(f"## Execution Trace (successful)\n{trace_summary}")
        parts.append("Extract reusable General Skills from this successful trace.\nApply Rules 7 (active suppression) and 8 (intra-response suppression).")
        return "\n\n".join(parts)

    def _parse_extraction_result(
        self, parsed_json: dict, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        """將 LLM JSON {"skills": [...]} 轉為 CandidateSkill 列表。"""
        raw_skills = parsed_json.get("skills", [])
        if not isinstance(raw_skills, list):
            logger.warning(f"[SkillExtractor] 'skills' is not a list for {task_id}")
            return []

        candidates = []
        for i, s in enumerate(raw_skills):
            if not isinstance(s, dict):
                continue

            # Validate required fields
            name = s.get("name")
            if not name or not isinstance(name, str):
                logger.warning(f"[SkillExtractor] Skill {i} missing name, skipping")
                continue

            strategy = s.get("strategy_steps", [])
            if not isinstance(strategy, list) or len(strategy) < 1:
                logger.warning(f"[SkillExtractor] Skill '{name}' has no strategy_steps, skipping")
                continue

            # Validate domain against domain_registry.py
            raw_domain = s.get("domain", [])
            if isinstance(raw_domain, str):
                raw_domain = [raw_domain]
            domain = self._validate_domain_list(raw_domain)

            candidates.append(CandidateSkill(
                name=self._to_kebab_case(name),
                description=s.get("description", name),
                type="general",
                domain=domain,
                invocation_condition=s.get("invocation_condition", ""),
                termination_condition=s.get("termination_condition", ""),
                strategy_steps=[str(step) for step in strategy],
                confidence=self._clamp_confidence(s.get("confidence", 0.5)),
                source_task_id=task_id,
            ))

        return candidates

    def _parse_template_result(
        self, raw_text: str, trace: list[dict], task_id: str
    ) -> list[CandidateSkill]:
        """解析降級模板的 key: value 輸出。"""
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

        # Parse domain
        raw_domain = [d.strip() for d in fields.get("domain", "").split(",") if d.strip()]
        domain = self._validate_domain_list(raw_domain)

        return [CandidateSkill(
            name=self._to_kebab_case(name),
            description=fields.get("description", name),
            type="general",
            domain=domain,
            invocation_condition=fields.get("invocation_condition", ""),
            termination_condition=fields.get("termination_condition", ""),
            strategy_steps=strategy_steps or ["(no steps extracted)"],
            confidence=self._clamp_confidence(fields.get("confidence", 0.5)),
            source_task_id=task_id,
        )]