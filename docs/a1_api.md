# A1 Task Decomposer — API Reference

> Module: `agents/task_decomposer.py`
> Version: W4 (constraint identification + goal clarification)
> Schema: `agents/tstruct_schema.json` (Tstruct v2)

## Overview

A1 converts natural language tasks into structured **Tstruct v2** JSON objects, enabling downstream modules (A2, executor, A3) to operate on well-defined task representations.

Four-step framework (ECC planner.md):
1. **Restate Requirements** — catch misunderstandings
2. **Identify Risks** — anticipate failure modes
3. **Phased Step Plan** — create a subtask DAG
4. **Success Criteria** — define verifiable objectives

W4 additions: constraint identification, goal clarification, domain alignment with SkillRL.

---

## Quick Start

```python
from agents.task_decomposer import TaskDecomposer

td = TaskDecomposer(config_path="config.yaml")
result = td.decompose("Build a REST API for user management")
```

---

## Class: `TaskDecomposer`

### Constructor

```python
TaskDecomposer(config_path: str | Path | None = None)
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `config_path` | `str \| Path \| None` | `project_root/config.yaml` | Path to YAML config with `llm` section |

Internally reads `config.yaml`, extracts the `llm` section, and passes it as a dict to `LLMClient(config={...})`.

Config keys used: `llm.base_url`, `llm.model`, `llm.api_format`, `llm.temperature`, `llm.max_tokens`, `llm.api_key`.

---

### `decompose(task, task_id=None) -> dict`

Main entry point. Full pipeline: LLM call → JSON parse → validation → post-processing.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `task` | `str` | (required) | Natural language task description |
| `task_id` | `str \| None` | auto `T-{uuid8}` | Task identifier |

**Returns:** Tstruct v2 dict.
**Raises:** `ValueError` if LLM output cannot be parsed.

---

### `constraint_identifier(task, tstruct=None) -> dict`

Extract structured constraints.

| Param | Type | Description |
|-------|------|-------------|
| `task` | `str` | Task description |
| `tstruct` | `dict \| None` | If provided, validates existing constraints. If None, runs focused LLM call. |

**Returns:** `{time: [...] | null, resources: [...] | null, format: [...] | null}`

---

### `goal_clarifier(task, tstruct=None) -> list[str]`

Generate clarifying questions for ambiguous tasks.

| Param | Type | Description |
|-------|------|-------------|
| `task` | `str` | Task description |
| `tstruct` | `dict \| None` | If provided, uses existing `clarification_needed`. If None, runs focused LLM call. |

**Returns:** List of 0–2 clarifying question strings.

---

## Output Schema: Tstruct v2

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `string` | Unique identifier |
| `original_task` | `string` | Raw input text |
| `input_type` | `enum` | `code_task \| research_task \| analysis_task \| creative_task \| web_task` |
| `domain` | `string[]` | 1–2 labels from Domain Registry |
| `requirements_restatement` | `string` | A1's understanding in its own words |
| `constraints` | `object` | `{time, resources, format}` — each null or list of constraint entries |
| `objectives` | `string[]` | Verifiable success criteria |
| `subtasks` | `object[]` | Subtask DAG |
| `risks_and_mitigations` | `object[]` | `{risk, mitigation}` pairs |
| `clarification_needed` | `string[]` | 0–2 clarifying questions |

### Constraint entry

| Field | Type | Description |
|-------|------|-------------|
| `constraint_id` | `string` | `"C1"`, `"C2"`, etc. |
| `description` | `string` | What the constraint is |
| `source` | `enum` | `"explicit"` or `"inferred"` |

### Subtask entry

| Field | Type | Description |
|-------|------|-------------|
| `subtask_id` | `string` | `"S1"`, `"S2"`, etc. |
| `description` | `string` | What to do |
| `why` | `string` | Why necessary |
| `depends_on` | `string[]` | DAG dependencies |
| `risk_level` | `enum` | `low \| medium \| high` |
| `phase` | `integer` | Execution phase (1-based, same phase = parallel) |
| `expected_output` | `string` | What this produces |
| `estimated_complexity` | `enum` | `simple \| moderate \| complex` |
| `risk_note` | `string \| null` | Risk description |

---

## Domain Registry

Defined in `agents/domain_registry.py`. Maps to SkillRL Task-Specific Skills.

| SIES Domain | SkillRL Category | Primary input_type |
|-------------|------------------|--------------------|
| `software-engineering` | CodeGeneration | code_task |
| `research` | InformationRetrieval | research_task |
| `data-analysis` | DataAnalysis | analysis_task |
| `content-creation` | TextGeneration | creative_task |
| `web-automation` | WebInteraction | web_task |
| `system-ops` | SystemOperation | code_task |
| `planning` | Planning | analysis_task, creative_task |

---

## Internal Architecture

```
TaskDecomposer.__init__(config_path)
  → _load_llm_config(config_path)    # reads YAML, extracts llm section
  → LLMClient(config={...})          # passes dict, NOT config_path

TaskDecomposer._llm_chat(system, user)
  → self.client.chat(system_prompt=..., user_message=...)
  → returns response.content (str)   # LLMResponse.content
```

---

## Testing

```bash
# Chess task live test (W4 specific)
bash tests/test_w4_chess.sh

# 20-task E2E report
python tests/test_e2e_decomposer.py --report

# Mock tests (no LLM)
pytest tests/test_e2e_decomposer.py -v -k Mock

# Full pytest E2E
pytest tests/test_e2e_decomposer.py -v
```

Target: > 80% pass rate (≥16/20).