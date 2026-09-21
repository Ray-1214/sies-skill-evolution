# A2 API Reference — Memory-Guided Planner

> 檔案路徑：`memory_planner.py`（專案根目錄）  
> 對應論文：Eq. 20-21 (Activation Score), Definition 5 (Working Memory Mw), A2 模組

---

## MemoryPlanner

### 初始化

```python
from memory_planner import MemoryPlanner
planner = MemoryPlanner("config.yaml")
```

初始化時載入：
- `EmbeddingEngine`（nvidia/llama-embed-nemotron-8b，CPU，~30 秒，~16GB RAM）
- `VectorStore`（LanceDB，serverless）
- `parse_graph_index`（NetworkX DiGraph + centrality）
- `LLMClient`（Tier A config: `config.yaml → llm`）

### plan(tstruct) → dict

**A2 主入口。** 從 Tstruct 生成帶來源標注的執行計畫。

```python
plan_result = planner.plan(tstruct)
```

**輸入：** A1 `task_decomposer.decompose()` 的回傳值（Tstruct v2 dict）

**輸出：**
```python
{
    "task_id": "T-xxx",
    "selected_skills": [              # top-k 技能（含 Activation Score）
        {
            "name": "code-execution",
            "path": "skills/active/code-execution/SKILL.md",
            "activation_score": 0.5432,
            "sim": 0.6123,
            "utility": 0.5,
            "centrality": 0.0556,
            "l2_distance": 0.8801,
        },
        ...
    ],
    "working_memory": "## 任務摘要\n...",  # 組裝後的 Mw 文字
    "execution_plan": "{...}",             # LLM 生成的 JSON string
    "metadata": {
        "query_text": "...",
        "top_k": 6,
        "trace_count": 0,
    },
}
```

**execution_plan JSON 格式：**
```json
{
    "plan_id": "P-T-xxx",
    "steps": [
        {
            "step_id": 1,
            "subtask_ref": "ST-xxx-1",
            "action": "具體動作描述",
            "skill_used": "code-execution",
            "skill_source": "skills/active/code-execution/SKILL.md",
            "tool_hint": "code_execution",
            "risk_level": "low",
            "fallback": "備用方案"
        }
    ],
    "execution_order": "sequential / parallel description",
    "estimated_total_steps": 3,
    "notes": "補充說明"
}
```

### select_skills(tstruct) → list[dict]

只做技能選擇，不呼叫 LLM（測試用）。

```python
skills = planner.select_skills(tstruct)
```

**回傳：** 同 `plan()` 中的 `selected_skills` 格式。

### Activation Score 公式

```
A(σ) = λ1·sim + λ2·U + λ3·centrality
```

- `sim`：cosine similarity（from L2 distance: `1 - L2²/2`）
- `U`：效用值（from `GRAPH_INDEX.md` frontmatter）
- `centrality`：in-degree centrality（NetworkX）

config.yaml 參數：
```yaml
planner:
  lambda1: 0.5    # 語義相似度權重
  lambda2: 0.3    # 效用值權重
  lambda3: 0.2    # 中心度權重
  top_k: 6        # 選擇數量
```

---

## Executor

> 檔案路徑：`executor.py`（專案根目錄）  
> W7 新增，最小可跑版  
> 模式：docker_exec（透過 `docker exec` 在 Agent-Zero 容器內跑）或 local（本機 subprocess）

### 初始化

```python
from executor import Executor
exe = Executor("config.yaml")
```

讀取 `config.yaml → agent_zero` 區塊。  
`docker_enabled: true` → docker_exec 模式，`false` → local 模式。

### execute(plan_result) → dict

接收 `planner.plan()` 的輸出，逐步在 Agent-Zero 容器（或本機）內執行。

```python
result = exe.execute(plan_result)
```

**輸出：**
```python
{
    "task_id": "T-xxx",
    "success": True,
    "total_steps": 3,
    "completed_steps": 3,
    "failed_steps": 0,
    "trace_file": "memory/episodic/T-xxx_20260410_143022.jsonl",
    "trace": [...],                  # list of step records
    "elapsed_seconds": 45.2,
}
```

**Trace JSONL 格式（每行）：**
```json
{
    "task_id": "T-xxx",
    "step_id": 1,
    "subtask_ref": "ST-xxx-1",
    "action": "...",
    "skill_used": "code-execution",
    "skill_source": "skills/active/code-execution/SKILL.md",
    "command": "ls -la /tmp",
    "stdout": "...",
    "stderr": "",
    "exit_code": 0,
    "outcome": "success",
    "error": null,
    "elapsed_seconds": 0.52,
    "timestamp": "2026-04-10T14:30:22+08:00",
    "exec_mode": "docker_exec"
}
```

### health_check() → bool

```python
if exe.health_check():
    print("Executor is ready")
```

### 執行模式

- **docker_exec**（預設）：`docker exec sies-agent-zero bash -c "command"`
  - 沙盒隔離，容器內有完整 Python/bash 環境
  - 安全模式：只允許唯讀指令直接執行（ls, cat, date 等），其他 step 只做 echo 記錄
- **local**：直接在本機 `subprocess.run(["bash", "-c", command])`
  - Agent-Zero 容器不可用時的降級方案

config.yaml 設定：
```yaml
agent_zero:
  docker_enabled: true              # true=docker_exec, false=local
  container_name: "sies-agent-zero" # Docker container 名稱
  timeout: 300                      # 指令超時（秒）
```

---

## 完整 Pipeline 呼叫範例

```python
from agents.task_decomposer import TaskDecomposer
from memory_planner import MemoryPlanner
from executor import Executor

td = TaskDecomposer()
planner = MemoryPlanner("config.yaml")
exe = Executor("config.yaml")

# A1: 自然語言 → Tstruct
tstruct = td.decompose("Write a Python script to clean CSV data")

# A2: Tstruct → 帶來源標注的計畫
plan_result = planner.plan(tstruct)

# Execute: 計畫 → Agent-Zero → trace JSONL
exec_result = exe.execute(plan_result)

print(f"Trace file: {exec_result['trace_file']}")
```

---

## config.yaml 相關參數速查

| 區塊 | 參數 | 預設值 | 說明 |
|------|------|--------|------|
| `planner.lambda1` | 0.5 | 語義相似度權重 |
| `planner.lambda2` | 0.3 | 效用值權重 |
| `planner.lambda3` | 0.2 | 中心度權重 |
| `planner.top_k` | 6 | 技能選擇數量 |
| `planner.max_tokens_for_skills` | 2000 | SKILL.md 讀取字元上限 |
| `planner.recent_traces` | 3 | 載入最近 trace 數量 |
| `agent_zero.port` | 50001 | Agent-Zero Docker 映射 port |
| `agent_zero.api_key` | "" | Agent-Zero API key |
| `agent_zero.timeout` | 300 | HTTP 請求超時（秒） |
| `agent_zero.lifetime_hours` | 1 | Agent-Zero context 存活時間 |

---

*v3.8 ｜ W7 ｜ 2026-04-10*