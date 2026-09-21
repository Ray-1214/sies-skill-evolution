# A3 API Reference — 反思評估器 + 技能驗證器

> 涵蓋 W9（提取器）+ W10（驗證器、評估器、閉環執行器）

---

## 模組總覽

| 模組 | 檔案路徑 | 週次 | 功能 |
|------|---------|------|------|
| BaseExtractor | `agents/base_extractor.py` | W9 | 提取器共用基底（LLM 呼叫、JSON parse、SKILL.md 生成） |
| SkillExtractor | `agents/skill_extractor.py` | W9 | 從成功 trace 提取 General Skill |
| LessonExtractor | `agents/lesson_extractor.py` | W9 | 從失敗 trace 提取 Task-Specific Lesson |
| PatternRecognizer | `agents/pattern_recognizer.py` | W9 | Action 子序列共現分析（純統計，供 W11 T3 用） |
| SkillValidator | `agents/skill_validator.py` | W10 | 三重驗證（schema + dedup + quality） |
| ReflectiveEvaluator | `agents/reflective_evaluator.py` | W10 | A3 orchestrator（提取 → 驗證 → 寫入 ΔΣ） |
| AgentRunner | `agents/agent_runner.py` | W10 | A1→A2→SimpleAgent→A3 完整閉環 |

---

## CandidateSkill（共用資料結構）

定義於 `agents/base_extractor.py`。對應論文 Definition 2（σ = (Iσ, βσ, πσ, ...)）。

```python
@dataclass
class CandidateSkill:
    name: str                        # kebab-case
    description: str                 # 1-2 句功能描述
    type: str                        # "general" | "task_specific"
    domain: list[str]                # domain_registry 7 categories 子集
    invocation_condition: str        # Iσ — 何時使用
    termination_condition: str       # βσ — 何時完成
    strategy_steps: list[str]        # πσ — 執行策略步驟
    confidence: float                # LLM 自評 0.0-1.0
    source_task_id: str              # 來源 trace 的 task_id
    source_trace_summary: str = ""   # 來源 trace 精簡摘要
    raw_llm_output: str = ""         # debug 用
    root_cause: Optional[str] = None # 僅 lesson
```

---

## SkillExtractor

從**成功** trace 提取 General Skill。

```python
from agents.skill_extractor import SkillExtractor

ext = SkillExtractor("config.yaml")
result = ext.extract(trace_records, task_description="Sort a list")
# result: ExtractionResult

for skill in result.candidates:
    print(skill.name, skill.confidence)
    ext.write_candidate(skill)  # → skills/candidates/{name}/SKILL.md
```

| 方法 | 輸入 | 輸出 |
|------|------|------|
| `extract(trace, task_description)` | trace: list[dict], task: str | `ExtractionResult` |
| `extract_from_file(path)` | JSONL 檔案路徑 | `ExtractionResult` |
| `extract_batch(dir, max)` | 目錄路徑, 最大數量 | `list[ExtractionResult]` |
| `write_candidate(skill)` | `CandidateSkill` | `Path`（寫入路徑） |

### ExtractionResult

```python
@dataclass
class ExtractionResult:
    candidates: list[CandidateSkill]
    source_task_id: str
    trace_classification: str    # "success" | "failure"
    llm_calls: int
    parse_success: bool
    used_template_mode: bool
    error: Optional[str] = None
```

---

## LessonExtractor

從**失敗** trace 提取 Task-Specific Lesson。API 與 SkillExtractor 相同。

```python
from agents.lesson_extractor import LessonExtractor

ext = LessonExtractor("config.yaml")
result = ext.extract(failed_trace, "Create and read file")
for lesson in result.candidates:
    print(lesson.name, lesson.root_cause)
```

差異：候選的 `type="task_specific"`，額外含 `root_cause` 欄位。

---

## PatternRecognizer

純統計 n-gram 共現分析（不需 LLM）。供 W11 T3 觸發條件使用。

```python
from agents.pattern_recognizer import PatternRecognizer

pr = PatternRecognizer()
traces = pr.load_traces_from_dir("memory/episodic/")
report = pr.analyze(traces, n_range=(2, 4), min_frequency=0.3)

for p in report.patterns:
    print(f"{' → '.join(p.sequence)}: freq={p.frequency:.0%}")

pr.export_patterns(report, "data/patterns.json")
```

| 方法 | 輸入 | 輸出 |
|------|------|------|
| `analyze(traces, n_range, min_frequency)` | 多條 trace | `PatternReport` |
| `load_traces_from_dir(dir, max)` | 目錄路徑 | `list[list[dict]]` |
| `export_patterns(report, path)` | 報告, 輸出路徑 | `Path` |

---

## SkillValidator

三重驗證 pipeline：Schema → Dedup → Quality。

```python
from agents.skill_validator import SkillValidator

v = SkillValidator("config.yaml")
result = v.validate(candidate_skill)
# result: ValidationResult

report = v.validate_batch(candidates)
# report: BatchValidationReport（含 intra-batch dedup）
```

### 三重驗證細節

**Layer 1 — Schema Check：**
- `name`：kebab-case，≥ 3 字元
- `description`：≥ 20 字元
- `type`：`general` 或 `task_specific`
- `domain`：非空 list，每個值在 7-domain 白名單內
- `invocation_condition`、`termination_condition`：非空
- `strategy_steps`：≥ 1 步，每步 ≥ 10 字元
- `confidence`：0.0–1.0

**Layer 2 — Dedup（embedding）：**
- 用 EmbeddingEngine embed 候選文字（name + description + strategy 前 200 字）
- 查 VectorStore（skills/active/）最近鄰
- cosine similarity > θdup (0.85) → 拒絕
- EmbeddingEngine 不可用時自動 skip（fail-open）

**Layer 3 — Quality Check（靜態分析）：**
- name 不能是 generic（"skill", "task", "unnamed-skill" 等）
- invocation_condition ≉ description（SequenceMatcher ratio < 0.80）
- termination_condition ≉ description
- invocation_condition ≉ termination_condition
- strategy_steps 不能全部相同

### ValidationResult

```python
@dataclass
class ValidationResult:
    candidate_name: str
    passed: bool
    checks: dict                     # {"schema": T/F, "dedup": T/F, "quality": T/F}
    rejection_reason: Optional[str]
    dedup_closest_skill: Optional[str]
    dedup_similarity: Optional[float]
```

### 設定（config.yaml）

```yaml
skill_validator:
  theta_dup: 0.85    # dedup cosine similarity 閾值
```

---

## ReflectiveEvaluator

A3 orchestrator：提取 → 驗證 → 寫入。

```python
from agents.reflective_evaluator import ReflectiveEvaluator

evaluator = ReflectiveEvaluator("config.yaml")
result = evaluator.evaluate(trace, "Calculate factorial")

print(f"Validated: {len(result.validated_candidates)}")
print(f"Rejected:  {len(result.rejected_candidates)}")
print(f"Written:   {result.candidates_written}")
```

### Pipeline

```
trace → classify_trace()
  ├─ "success" → SkillExtractor.extract() → candidates
  └─ "failure" → LessonExtractor.extract() → candidates
       ↓
  SkillValidator.validate_batch(candidates)
       ↓
  validated → write_candidate() → skills/candidates/{name}/SKILL.md
  rejected → logged
```

### EvaluationResult

```python
@dataclass
class EvaluationResult:
    source_task_id: str
    trace_classification: str
    extraction_result: ExtractionResult
    validation_report: BatchValidationReport
    validated_candidates: list[CandidateSkill]
    rejected_candidates: list[CandidateSkill]
    candidates_written: list[str]   # SKILL.md 路徑
    elapsed_seconds: float
    error: Optional[str]
```

---

## AgentRunner

A1→A2→SimpleAgent→A3 完整閉環。

```python
from agents.agent_runner import AgentRunner

runner = AgentRunner("config.yaml")
result = runner.run("Write a function to check if a string is a palindrome")

print(f"Execution: {'✓' if result.execution_success else '✗'}")
print(f"Candidates: {len(result.evaluation.validated_candidates)}")
```

### Pipeline

```
task (str)
  → A1: TaskDecomposer.decompose() → Tstruct
  → A2: MemoryPlanner.plan() → plan_result (selected_skills + execution_plan)
  → SimpleAgent.run(task, context=A2_output) → trace
  → A3: ReflectiveEvaluator.evaluate(trace) → ΔΣ
```

### RunResult

```python
@dataclass
class RunResult:
    task: str
    task_id: str
    tstruct: Optional[dict]          # A1 output
    plan_result: Optional[dict]      # A2 output
    execution_success: bool
    execution_trace: list            # Trace v2 records
    execution_steps: int
    evaluation: Optional[EvaluationResult]  # A3 output
    elapsed_seconds: float
    stage_timings: dict              # {"a1_decompose": 2.1, "a2_plan": 1.5, ...}
    error: Optional[str]
    error_stage: Optional[str]       # "a1_decompose" | "a2_plan" | "agent_execute" | "a3_evaluate"
```

### 批次與統計

```python
results = runner.run_batch(["task1", "task2", ...])
summary = AgentRunner.summarize_results(results)
# summary: {total_tasks, execution_success, execution_rate,
#            total_validated_candidates, errors_by_stage, ...}
```

### CLI

```bash
python agents/agent_runner.py "Write a function to reverse a list"
```

---

## 共用工具函數

定義於 `agents/base_extractor.py`，可直接 import：

```python
from agents.base_extractor import classify_trace, strip_think, parse_json_output, summarize_trace
```

| 函數 | 功能 |
|------|------|
| `classify_trace(trace)` | 判斷 trace 成功/失敗（最後一步 action=finish & success=True） |
| `strip_think(text)` | 移除 Gemma `<think>...</think>` blocks |
| `parse_json_output(text)` | 三層容錯 JSON parse |
| `summarize_trace(trace, max_chars)` | 壓縮 trace 為文字摘要（含重複偵測） |

---

## Domain 白名單

7 categories（對齊 SkillRL，定義於 `agents/domain_registry.py`）：

`software-engineering`, `research`, `data-analysis`, `content-creation`, `web-automation`, `system-ops`, `planning`