"""
task_decomposer.py — A1 Task Decomposer (W4 完整版)

W3 → W4 changes:
  - Added constraint_identifier(): structured extraction of time/resource/format constraints
  - Added goal_clarifier(): generates ≤2 clarifying questions for ambiguous tasks
  - Enhanced system prompt with explicit constraint/clarification instructions
  - Domain labels aligned with SkillRL Task-Specific Skills (domain_registry.py)
  - Post-processing validates domain labels via domain_registry

Usage:
    from agents.task_decomposer import TaskDecomposer
    td = TaskDecomposer()          # reads config.yaml
    result = td.decompose("Build a REST API for user management")
    # result is a Tstruct v2 dict
"""

from __future__ import annotations

import json
import re
import uuid
import logging
from pathlib import Path
from typing import Any

import yaml

# ── project imports (run from project root) ──────────────────────────
from agents.llm_client import LLMClient
from agents.domain_registry import (
    validate_domains,
    classify_domain,
    VALID_DOMAINS,
)

logger = logging.getLogger(__name__)

# ── paths ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _ROOT / "agents" / "tstruct_schema.json"
_CONFIG_PATH = _ROOT / "config.yaml"


def _load_llm_config(config_path: str | Path | None = None) -> dict:
    """Load the 'llm' section from config.yaml and return as dict for LLMClient."""
    p = Path(config_path) if config_path else _CONFIG_PATH
    if not p.exists():
        logger.warning("config.yaml not found at %s, using defaults", p)
        return {}
    with open(p) as f:
        full = yaml.safe_load(f) or {}
    llm_cfg = full.get("llm", {})
    # Map config.yaml keys to LLMClient expected keys
    return {
        **llm_cfg,  # Preserve provider endpoints, credential references and request options.
        "base_url": llm_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta"
                                if llm_cfg.get("api_format") == "google" else "http://localhost:8080"),
        "api_key": llm_cfg.get("api_key", "not-needed"),
        "model": llm_cfg.get("model", "coder"),
        "api_format": llm_cfg.get("api_format", "anthropic"),
        "temperature": llm_cfg.get("temperature", 0.1),
        "max_tokens": llm_cfg.get("max_tokens", 8192),
    }


# =====================================================================
#  System Prompt — ECC planner.md 四步框架 + W4 constraint/clarify
# =====================================================================

SYSTEM_PROMPT = r"""You are A1, a task decomposer for the SIES agent system. Your job is to convert a natural language task into a structured Tstruct JSON object.

## Framework (ECC planner.md four-step)

### Step 1 — Restate Requirements
Restate the task in your own words under `requirements_restatement`. This catches misunderstandings early.

### Step 2 — Identify Risks
List 1-3 concrete risks under `risks_and_mitigations`. Each entry has `risk` and `mitigation`.

### Step 3 — Phased Step Plan
Break the task into subtasks. Each subtask belongs to a `phase` (integer, 1-based). Subtasks in the same phase can run in parallel; phases execute sequentially.

### Step 4 — Success Criteria
Define `objectives` — a list of concrete, verifiable success conditions.

## Constraint Identification (W4)
Examine the task for three categories of constraints:
- **time**: deadlines, time limits, urgency cues ("within 2 hours", "by Friday", "ASAP")
- **resources**: budget, tool restrictions, platform limits ("only use Python", "no external APIs", "under 100MB")
- **format**: output format requirements ("return as JSON", "write a markdown report", "CSV file")

For each constraint found, output it in the `constraints` object. If a category has no constraints, set it to `null`. Each constraint entry should have:
- `constraint_id`: short identifier like "C1", "C2"
- `description`: what the constraint is
- `source`: "explicit" (stated in task) or "inferred" (implied by context)

Example constraints:
```json
"constraints": {
  "time": [{"constraint_id": "C1", "description": "Complete within 30 minutes", "source": "explicit"}],
  "resources": [{"constraint_id": "C2", "description": "Python only, no external API calls", "source": "explicit"}],
  "format": null
}
```

## Goal Clarification (W4)
If the task is ambiguous — missing scope, unclear success criteria, or multiple valid interpretations — generate up to 2 clarifying questions under `clarification_needed`. Each question should:
- Target a specific ambiguity
- Suggest 2-3 concrete options when possible

If the task is clear enough to decompose without clarification, set `clarification_needed` to an empty list `[]`.

Examples of ambiguity that warrant clarification:
- "Build a website" → scope unclear (landing page? full SaaS?)
- "Analyze the data" → what data? what analysis?
- "Write tests" → unit tests? integration? what coverage target?

## Domain Classification
Classify the task's primary domain using EXACTLY these labels:
{valid_domains}

Assign 1-2 domain labels in the `domain` field as a list.

## Input Type
Classify into exactly one: code_task, research_task, analysis_task, creative_task, web_task.

## Subtask Fields
Each subtask MUST include:
- `subtask_id`: "S1", "S2", etc.
- `description`: what to do
- `why`: why this subtask is necessary (ECC planner requirement)
- `depends_on`: list of subtask_ids this depends on (must form a DAG — no cycles)
- `risk_level`: "low", "medium", or "high"
- `phase`: integer phase number (1-based)
- `expected_output`: what this subtask produces
- `estimated_complexity`: "simple", "moderate", or "complex"
- `risk_note`: brief risk description (or null if low risk)

## Output Format
Return ONLY a valid JSON object (no markdown fences, no preamble). The JSON must conform to the Tstruct v2 schema.

## Few-shot Example

Task: "Write a Python script that scrapes product prices from Amazon and saves them to a CSV file. Must complete in under 1 hour."

```json
{
  "task_id": "T-example-001",
  "original_task": "Write a Python script that scrapes product prices from Amazon and saves them to a CSV file. Must complete in under 1 hour.",
  "input_type": "code_task",
  "domain": ["web-automation", "software-engineering"],
  "requirements_restatement": "Create a Python web scraper targeting Amazon product listings, extracting price data and exporting to CSV format, within a 1-hour time constraint.",
  "constraints": {
    "time": [{"constraint_id": "C1", "description": "Must complete in under 1 hour", "source": "explicit"}],
    "resources": [{"constraint_id": "C2", "description": "Python language required", "source": "explicit"}],
    "format": [{"constraint_id": "C3", "description": "Output as CSV file", "source": "explicit"}]
  },
  "objectives": [
    "Script successfully extracts product prices from Amazon",
    "Output is a valid CSV with columns: product_name, price, url",
    "Script handles pagination and rate limiting gracefully"
  ],
  "subtasks": [
    {
      "subtask_id": "S1",
      "description": "Set up project structure with requests/beautifulsoup4 dependencies",
      "why": "Establish clean project foundation before implementing scraping logic",
      "depends_on": [],
      "risk_level": "low",
      "phase": 1,
      "expected_output": "Project directory with requirements.txt and main.py skeleton",
      "estimated_complexity": "simple",
      "risk_note": null
    },
    {
      "subtask_id": "S2",
      "description": "Implement Amazon product page parser with anti-bot headers",
      "why": "Core scraping logic; Amazon actively blocks automated requests",
      "depends_on": ["S1"],
      "risk_level": "high",
      "phase": 2,
      "expected_output": "Function that returns product name and price from a product URL",
      "estimated_complexity": "complex",
      "risk_note": "Amazon anti-scraping measures may block requests; need rotating headers"
    },
    {
      "subtask_id": "S3",
      "description": "Implement CSV export with proper encoding and headers",
      "why": "Fulfills the explicit CSV format constraint",
      "depends_on": ["S2"],
      "risk_level": "low",
      "phase": 3,
      "expected_output": "CSV file with product_name, price, url columns",
      "estimated_complexity": "simple",
      "risk_note": null
    },
    {
      "subtask_id": "S4",
      "description": "Add error handling, retry logic, and rate limiting",
      "why": "Production robustness; prevents IP bans and handles transient failures",
      "depends_on": ["S2"],
      "risk_level": "medium",
      "phase": 3,
      "expected_output": "Retry decorator and rate limiter integrated into scraper",
      "estimated_complexity": "moderate",
      "risk_note": "Rate limit values need empirical tuning"
    }
  ],
  "risks_and_mitigations": [
    {"risk": "Amazon blocks automated requests", "mitigation": "Use rotating User-Agent headers and request delays"},
    {"risk": "Page structure changes break parser", "mitigation": "Use multiple CSS selectors with fallback logic"}
  ],
  "clarification_needed": []
}
```

## Few-shot Example 2 (ambiguous task with clarification)

Task: "Analyze the data"

```json
{
  "task_id": "T-example-002",
  "original_task": "Analyze the data",
  "input_type": "analysis_task",
  "domain": ["data-analysis"],
  "requirements_restatement": "Perform data analysis on an unspecified dataset. The task lacks information about which data, what type of analysis, and desired output format.",
  "constraints": {
    "time": null,
    "resources": null,
    "format": null
  },
  "objectives": [
    "Identify the dataset to analyze",
    "Determine appropriate analysis methods",
    "Produce analysis results in a useful format"
  ],
  "subtasks": [
    {
      "subtask_id": "S1",
      "description": "Identify and load the target dataset",
      "why": "Cannot analyze data without knowing what data to analyze",
      "depends_on": [],
      "risk_level": "high",
      "phase": 1,
      "expected_output": "Loaded dataset with schema documentation",
      "estimated_complexity": "simple",
      "risk_note": "Dataset not specified — depends on clarification"
    },
    {
      "subtask_id": "S2",
      "description": "Perform exploratory data analysis (summary statistics, distributions, missing values)",
      "why": "EDA reveals data quality issues and guides analysis direction",
      "depends_on": ["S1"],
      "risk_level": "low",
      "phase": 2,
      "expected_output": "EDA report with key statistics and visualizations",
      "estimated_complexity": "moderate",
      "risk_note": null
    }
  ],
  "risks_and_mitigations": [
    {"risk": "Unknown dataset may require specialized tools", "mitigation": "Start with pandas; escalate to domain-specific libraries if needed"}
  ],
  "clarification_needed": [
    "Which dataset should be analyzed? (e.g., a specific CSV file, database table, or API endpoint)",
    "What type of analysis is needed? (e.g., descriptive statistics, trend analysis, predictive modeling)"
  ]
}
```

## Few-shot Example 3 (research task with inferred constraints)

Task: "Research the latest developments in quantum computing for our team meeting tomorrow"

```json
{
  "task_id": "T-example-003",
  "original_task": "Research the latest developments in quantum computing for our team meeting tomorrow",
  "input_type": "research_task",
  "domain": ["research"],
  "requirements_restatement": "Gather and summarize recent quantum computing developments, formatted for presentation at tomorrow's team meeting.",
  "constraints": {
    "time": [{"constraint_id": "C1", "description": "Must be ready by tomorrow (next day)", "source": "explicit"}],
    "resources": null,
    "format": [{"constraint_id": "C2", "description": "Suitable for team meeting presentation", "source": "inferred"}]
  },
  "objectives": [
    "Identify 3-5 key recent developments in quantum computing",
    "Summarize each development in 2-3 sentences",
    "Format as presentation-ready brief"
  ],
  "subtasks": [
    {
      "subtask_id": "S1",
      "description": "Search for quantum computing news and papers from the past 3 months",
      "why": "Need recent developments, not general background",
      "depends_on": [],
      "risk_level": "low",
      "phase": 1,
      "expected_output": "List of 10+ recent articles/papers with URLs",
      "estimated_complexity": "simple",
      "risk_note": null
    },
    {
      "subtask_id": "S2",
      "description": "Filter and rank findings by significance and relevance",
      "why": "Meeting time is limited; need to present only the most important items",
      "depends_on": ["S1"],
      "risk_level": "low",
      "phase": 2,
      "expected_output": "Ranked list of top 5 developments",
      "estimated_complexity": "simple",
      "risk_note": null
    },
    {
      "subtask_id": "S3",
      "description": "Write concise summaries for each selected development",
      "why": "Team members need digestible summaries, not raw papers",
      "depends_on": ["S2"],
      "risk_level": "low",
      "phase": 3,
      "expected_output": "Meeting brief document with 5 summarized developments",
      "estimated_complexity": "moderate",
      "risk_note": null
    }
  ],
  "risks_and_mitigations": [
    {"risk": "Information may be too technical for general audience", "mitigation": "Adjust language level to non-specialist team members"}
  ],
  "clarification_needed": []
}
```
""".replace("{valid_domains}", ", ".join(sorted(VALID_DOMAINS)))


# =====================================================================
#  Tstruct Validation Helpers
# =====================================================================

def _strip_think_blocks(text: str) -> str:
    """Remove Qwen3.5 <think>...</think> reasoning blocks from output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict | None:
    """
    Extract JSON from LLM output, tolerating markdown fences and preamble.
    Returns parsed dict or None.
    """
    text = _strip_think_blocks(text)

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding the outermost { ... }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_dag(subtasks: list[dict]) -> bool:
    """Check that subtask depends_on forms a valid DAG (no cycles)."""
    ids = {s["subtask_id"] for s in subtasks}
    for s in subtasks:
        for dep in s.get("depends_on", []):
            if dep not in ids:
                return False
    in_degree = {sid: 0 for sid in ids}
    adj: dict[str, list[str]] = {sid: [] for sid in ids}
    for s in subtasks:
        for dep in s.get("depends_on", []):
            adj[dep].append(s["subtask_id"])
            in_degree[s["subtask_id"]] += 1
    queue = [sid for sid, d in in_degree.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    return visited == len(ids)


def _validate_constraints(constraints: dict | None) -> dict:
    """Normalize constraints to {time: [..] | null, resources: [..] | null, format: [..] | null}."""
    if constraints is None:
        return {"time": None, "resources": None, "format": None}

    result = {}
    for cat in ("time", "resources", "format"):
        val = constraints.get(cat)
        if val is None or val == []:
            result[cat] = None
        elif isinstance(val, list):
            cleaned = []
            for item in val:
                if isinstance(item, dict) and "description" in item:
                    cleaned.append({
                        "constraint_id": item.get("constraint_id", f"C{len(cleaned)+1}"),
                        "description": item["description"],
                        "source": item.get("source", "inferred"),
                    })
            result[cat] = cleaned if cleaned else None
        elif isinstance(val, str):
            result[cat] = [{"constraint_id": "C1", "description": val, "source": "inferred"}]
        else:
            result[cat] = None
    return result


def _validate_clarification(clarifications: Any) -> list[str]:
    """Ensure clarification_needed is a list of ≤2 strings."""
    if not clarifications:
        return []
    if isinstance(clarifications, list):
        return [str(q) for q in clarifications[:2]]
    if isinstance(clarifications, str):
        return [clarifications]
    return []


def _fix_domain_labels(domains: Any, original_task: str) -> list[str]:
    """Validate domain labels; fall back to keyword classification if invalid."""
    if isinstance(domains, str):
        domains = [domains]
    if not isinstance(domains, list):
        return classify_domain(original_task)
    valid, invalid = validate_domains(domains)
    if valid:
        return valid[:2]
    return classify_domain(original_task)


# =====================================================================
#  TaskDecomposer
# =====================================================================

class TaskDecomposer:
    """
    A1 Task Decomposer — converts natural language tasks to Tstruct v2.

    Public API:
        decompose(task: str) -> dict
        constraint_identifier(task: str, tstruct: dict) -> dict
        goal_clarifier(task: str, tstruct: dict) -> list[str]

    Config: reads from config.yaml (llm section), passes dict to LLMClient.
    """

    def __init__(self, config_path: str | Path | None = None):
        """
        Initialize with config.yaml path.
        Reads the 'llm' section and passes it as a dict to LLMClient(config=...).
        """
        llm_config = _load_llm_config(config_path)
        self.client = LLMClient(config=llm_config)
        self._schema = self._load_schema()

    def _load_schema(self) -> dict | None:
        if _SCHEMA_PATH.exists():
            with open(_SCHEMA_PATH) as f:
                return json.load(f)
        logger.warning("tstruct_schema.json not found at %s", _SCHEMA_PATH)
        return None

    def _llm_chat(self, system: str, user: str) -> str:
        """Call LLM and return content string. Handles LLMResponse.content."""
        response = self.client.chat(system_prompt=system, user_message=user)
        return response.content

    # ── Main entry point ─────────────────────────────────────────────

    def decompose(self, task: str, task_id: str | None = None) -> dict:
        """
        Decompose a natural language task into a Tstruct v2 JSON object.

        Args:
            task: The natural language task description.
            task_id: Optional task ID. Auto-generated if not provided.

        Returns:
            Tstruct v2 dict with all required fields.

        Raises:
            ValueError: If LLM output cannot be parsed into valid JSON.
        """
        if task_id is None:
            task_id = f"T-{uuid.uuid4().hex[:8]}"

        raw_output = self._llm_chat(system=SYSTEM_PROMPT, user=task)

        tstruct = _extract_json(raw_output)
        if tstruct is None:
            raise ValueError(
                f"Failed to extract JSON from LLM output. "
                f"Raw (first 500 chars): {raw_output[:500]}"
            )

        # ── Post-processing & validation ─────────────────────────────
        tstruct["task_id"] = task_id
        tstruct["original_task"] = task

        tstruct["domain"] = _fix_domain_labels(tstruct.get("domain"), task)
        tstruct["constraints"] = _validate_constraints(tstruct.get("constraints"))
        tstruct["clarification_needed"] = _validate_clarification(tstruct.get("clarification_needed"))

        subtasks = tstruct.get("subtasks", [])
        if subtasks and not _validate_dag(subtasks):
            logger.warning("Task %s: DAG invalid, clearing depends_on.", task_id)
            for s in subtasks:
                s["depends_on"] = []

        tstruct.setdefault("input_type", "code_task")
        tstruct.setdefault("requirements_restatement", "")
        tstruct.setdefault("objectives", [])
        tstruct.setdefault("risks_and_mitigations", [])

        return tstruct

    # ── Standalone helpers ───────────────────────────────────────────

    def constraint_identifier(self, task: str, tstruct: dict | None = None) -> dict:
        """Extract structured constraints from a task description."""
        if tstruct is not None:
            return _validate_constraints(tstruct.get("constraints"))

        prompt = (
            "Extract constraints from this task. Return ONLY a JSON object with keys: "
            "time, resources, format. Each value is either null or a list of "
            "{constraint_id, description, source} objects.\n\n"
            f"Task: {task}"
        )
        raw = self._llm_chat(system="You extract task constraints as JSON.", user=prompt)
        parsed = _extract_json(raw)
        if parsed is None:
            return {"time": None, "resources": None, "format": None}
        return _validate_constraints(parsed)

    def goal_clarifier(self, task: str, tstruct: dict | None = None) -> list[str]:
        """Generate clarifying questions for ambiguous tasks."""
        if tstruct is not None:
            return _validate_clarification(tstruct.get("clarification_needed"))

        prompt = (
            "Analyze this task for ambiguity. If clear, return []. "
            "If ambiguous, return a JSON list of 1-2 clarifying questions.\n\n"
            f"Task: {task}"
        )
        raw = self._llm_chat(system="You identify ambiguities in task descriptions.", user=prompt)
        raw_clean = _strip_think_blocks(raw)
        try:
            result = json.loads(raw_clean)
        except (json.JSONDecodeError, TypeError):
            fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw_clean, re.DOTALL)
            if fence_match:
                try:
                    result = json.loads(fence_match.group(1).strip())
                except json.JSONDecodeError:
                    result = []
            else:
                result = []

        if isinstance(result, list):
            return [str(q) for q in result[:2]]
        return []


# =====================================================================
#  CLI entry point
# =====================================================================

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m agents.task_decomposer 'task description'")
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    td = TaskDecomposer()
    result = td.decompose(task)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
