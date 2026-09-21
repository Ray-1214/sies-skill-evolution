"""
memory_planner.py — A2 Memory-Guided Planner

功能：
  1. Activation Score 計算：A(σ) = λ1·sim + λ2·U + λ3·centrality
  2. Top-k 技能選擇（k=6）
  3. 技能目錄深度讀取：SKILL.md + examples/ + lessons/
  4. Working Memory 組裝：top-k 技能 + 最近 N 條相關 trace
  5. 呼叫 LLM 生成帶來源標注的結構化執行計畫

對應論文：
  - Eq. 20-21: Activation Score
  - Definition 5: Working Memory Mw
  - A2 模組：Memory-Guided Planner

依賴：
  embedding_engine.py, vector_store.py, parse_graph_index.py, llm_client.py

用法：
  from memory_planner import MemoryPlanner
  planner = MemoryPlanner("config.yaml")
  plan = planner.plan(tstruct)
"""

import json
import yaml
import glob
import numpy as np
from pathlib import Path
from typing import Optional

from parse_graph_index import parse_graph_index, build_graph, compute_centrality
from embedding_engine import EmbeddingEngine
from vector_store import VectorStore


class MemoryPlanner:
    """
    A2 Memory-Guided Planner。

    流程：
      Tstruct → 語義查詢 → Activation Score 排序 → top-k 選擇
      → 讀取技能詳情 → 組裝 Working Memory → LLM 生成計畫
    """

    # 改之後
    def __init__(self, config_path: str = "config.yaml", embedding_engine=None,
                 vector_store=None, no_skills: bool = False):
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.no_skills = no_skills
        self.project_root = Path(self.config.get("system", {}).get("project_root", "."))

        print("[memory_planner] Initializing A2 Memory-Guided Planner...")
        if embedding_engine is not None:
            self.engine = embedding_engine
        else:
            self.engine = EmbeddingEngine(config_path)

        if vector_store is not None:
            self.store = vector_store
        else:
            self.store = VectorStore(config_path)
        self._init_graph()
        self._init_llm()
        print("[memory_planner] A2 ready.")

    def _load_config(self, config_path: str) -> dict:
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _init_graph(self):
        """載入技能圖譜並計算 centrality"""
        parsed = parse_graph_index(str(self.project_root / "skills/GRAPH_INDEX.md"))
        self.graph = build_graph(parsed)
        self.centrality = compute_centrality(self.graph)

    def reload_graph(self):
        """重讀 GRAPH_INDEX.md → 重建 self.graph + self.centrality。

        Φ 演化後呼叫，讓 A2 的 utility/centrality 評分看得到新插入的 skill。
        _init_graph 是 idempotent，安全重呼。
        """
        self._init_graph()

    def _init_llm(self):
        """初始化 LLM client（用 Tier A config）"""
        from agents.llm_client import LLMClient
        self.llm = LLMClient(self.config.get("llm", {}))

    # ── 核心 API ──────────────────────────────────────────────

    def plan(self, tstruct: dict) -> dict:
        """
        A2 主入口：從 Tstruct 生成帶來源標注的執行計畫。

        Args:
            tstruct: A1 task_decomposer 的輸出

        Returns:
            {
                "task_id": str,
                "selected_skills": [...],      # top-k 技能（含 Activation Score）
                "working_memory": str,         # 組裝後的 Mw 文字
                "execution_plan": str,         # LLM 生成的結構化計畫
                "metadata": {
                    "query_text": str,
                    "top_k": int,
                    "trace_count": int,
                }
            }
        """
        # Step 1: 從 Tstruct 組合查詢文字
        query_text = self._build_query_text(tstruct)

        # Step 2: 語義檢索 + Activation Score 排序 → top-k
        selected = [] if self.no_skills else self._select_top_k(query_text)

        # Step 3: 讀取每個技能的完整詳情（SKILL.md + examples + lessons）
        skill_details = [self._read_skill_detail(s) for s in selected]

        # Step 4: 載入最近相關 trace
        traces = self._load_recent_traces(tstruct)

        # Step 5: 組裝 Working Memory
        working_memory = self._assemble_working_memory(
            tstruct, skill_details, traces
        )

        # Step 6: 呼叫 LLM 生成執行計畫
        execution_plan = self._generate_plan(tstruct, working_memory)

        return {
            "task_id": tstruct.get("task_id", "unknown"),
            "selected_skills": selected,
            "working_memory": working_memory,
            "execution_plan": execution_plan,
            "metadata": {
                "query_text": query_text,
                "top_k": len(selected),
                "trace_count": len(traces),
            },
        }

    def select_skills(self, tstruct: dict) -> list[dict]:
        """
        只做技能選擇，不生成計畫（測試用）。

        Returns: top-k 技能列表，每個含 activation_score
        """
        query_text = self._build_query_text(tstruct)
        return [] if self.no_skills else self._select_top_k(query_text)

    # ── Step 1: 查詢文字建構 ─────────────────────────────────

    def _build_query_text(self, tstruct: dict) -> str:
        """
        從 Tstruct 擷取最有語義辨識度的部分，拼成查詢文字。

        策略：requirements_restatement + 所有 subtask description + domain
        這比原始任務文字更精確，因為 A1 已經做過結構化分析。
        """
        parts = []

        # requirements_restatement 是 A1 對任務的理解摘要
        restatement = tstruct.get("requirements_restatement", "")
        if restatement:
            parts.append(restatement)

        # subtask descriptions 提供具體子任務的語義
        for st in tstruct.get("subtasks", []):
            desc = st.get("description", "")
            if desc:
                parts.append(desc)

        # domain tags 補充領域語義
        domains = tstruct.get("domain", [])
        if domains:
            parts.append(" ".join(domains))

        return " | ".join(parts)

    # ── Step 2: Activation Score + top-k ─────────────────────

    def _select_top_k(self, query_text: str) -> list[dict]:
        """
        計算 Activation Score 並選擇 top-k 技能。

        Activation Score (Eq. 20-21):
          A(σ) = λ1·sim + λ2·U + λ3·centrality

        其中：
          sim = 1 - d/2（LanceDB 的 _distance 在 l2 metric 下已經是平方距離
                          d = 2-2·cos；[P2-2] 修正前這裡又平方一次）
          U = 技能效用值（from GRAPH_INDEX.md）
          centrality = in-degree centrality（from NetworkX）
        """
        planner_cfg = self.config.get("planner", {})
        lambda1 = planner_cfg.get("lambda1", 0.5)
        lambda2 = planner_cfg.get("lambda2", 0.3)
        lambda3 = planner_cfg.get("lambda3", 0.2)
        top_k = planner_cfg.get("top_k", 6)
        if self.no_skills or top_k <= 0:
            return []

        # 語義查詢：從 LanceDB 取回候選（取多一點，之後用 Activation Score 重排）
        query_vec = self.engine.embed_text(query_text)
        candidates = self.store.query(query_vec, top_k=min(top_k * 2, 18))

        if not candidates:
            print("[memory_planner] WARN: no candidates from vector store")
            return []

        # 計算 Activation Score
        scored = []
        for c in candidates:
            name = c["name"]
            l2_dist = c["score"]

            # [P2-2] LanceDB 的 _distance 在 l2 metric 下回傳的**已經是**平方距離
            # d = 2 − 2·cos（向量已正規化），所以 cos = 1 − d/2。
            # 修正前寫成 1 − d²/2（又平方一次），相似度被膨脹，
            # 使 A(σ) 的 λ1·sim 項失真。見 skill_validator:337 的同一個修正。
            sim = 1.0 - l2_dist / 2.0
            sim = max(0.0, min(1.0, sim))  # clamp

            # U: 從圖譜取效用值
            u = 0.5  # default
            if name in self.graph.nodes:
                u = self.graph.nodes[name].get("utility", 0.5)

            # centrality: in-degree centrality
            cent = self.centrality.get(name, 0.0)

            # Activation Score
            activation = lambda1 * sim + lambda2 * u + lambda3 * cent

            scored.append({
                "name": name,
                "path": c["path"],
                "activation_score": round(activation, 4),
                "sim": round(sim, 4),
                "utility": round(u, 4),
                "centrality": round(cent, 4),
                "l2_distance": round(l2_dist, 4),
            })

        # 按 Activation Score 降序排序，取 top-k
        scored.sort(key=lambda x: x["activation_score"], reverse=True)
        selected = scored[:top_k]

        print(f"[memory_planner] Selected {len(selected)} skills:")
        for s in selected:
            print(f"  [{s['name']}] A={s['activation_score']} "
                  f"(sim={s['sim']}, U={s['utility']}, C={s['centrality']})")

        return selected

    # ── Step 3: 技能詳情讀取 ─────────────────────────────────

    def _read_skill_detail(self, skill: dict) -> dict:
        """
        「cd 進技能目錄」：讀取 SKILL.md 全文 + examples/ + lessons/

        回傳壓縮後的文字（尊重 max_tokens_for_skills 限制）。
        """
        skill_path = self.project_root / skill["path"]
        skill_dir = skill_path.parent
        max_tokens = self.config.get("planner", {}).get("max_tokens_for_skills", 2000)

        detail = {
            "name": skill["name"],
            "source_path": str(skill_path),
            "skill_md": "",
            "examples": [],
            "lessons": [],
        }

        # 讀 SKILL.md
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            # 截斷到合理長度（粗略按字元數估算 token）
            detail["skill_md"] = content[:max_tokens * 3]  # ~3 chars per token

        # 讀 examples/（成功 trace 範例）
        examples_dir = skill_dir / "examples"
        if examples_dir.exists():
            for f in sorted(examples_dir.glob("*.md"))[:3]:  # 最多 3 個
                detail["examples"].append({
                    "file": f.name,
                    "content": f.read_text(encoding="utf-8")[:500],
                })

        # 讀 lessons/（A3 提取的失敗教訓）
        lessons_dir = skill_dir / "lessons"
        if lessons_dir.exists():
            for f in sorted(lessons_dir.glob("*.md"))[:3]:  # 最多 3 個
                detail["lessons"].append({
                    "file": f.name,
                    "content": f.read_text(encoding="utf-8")[:500],
                })

        return detail

    # ── Step 4: 最近相關 trace ───────────────────────────────

    def _load_recent_traces(self, tstruct: dict) -> list[dict]:
        """
        載入最近 N 條相關 episodic trace（Me）。

        目前實作：按時間倒序取最近 N 條 JSONL 檔案的最後幾行。
        後期可加語義過濾（用 embedding 比對 tstruct 和 trace 的相似度）。
        """
        trace_dir = Path(self.config.get("system", {}).get("trace_dir", "./memory/episodic"))
        n = self.config.get("planner", {}).get("recent_traces", 3)

        if not trace_dir.exists():
            return []

        # 找所有 .jsonl trace 檔案，按修改時間降序
        trace_files = sorted(
            trace_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:n]

        traces = []
        for tf in trace_files:
            try:
                lines = tf.read_text(encoding="utf-8").strip().split("\n")
                # 取最後 5 行（通常是最關鍵的結果步驟）
                recent_lines = lines[-5:] if len(lines) > 5 else lines
                trace_data = []
                for line in recent_lines:
                    try:
                        trace_data.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                traces.append({
                    "file": tf.name,
                    "steps": trace_data,
                })
            except Exception:
                continue

        return traces

    # ── Step 5: Working Memory 組裝 ──────────────────────────

    def _assemble_working_memory(
        self,
        tstruct: dict,
        skill_details: list[dict],
        traces: list[dict],
    ) -> str:
        """
        組裝 Working Memory (Mw)：結構化文字，含來源路徑標注。

        格式設計原則：
        - 每段資訊都標注來源路徑（讓 LLM 和人類都能追溯）
        - 技能按 Activation Score 順序排列
        - Lessons 優先於 Examples（失敗教訓比成功範例更重要）
        """
        sections = []

        # Section 1: 任務摘要（來自 A1 Tstruct）
        sections.append("## 任務摘要\n")
        sections.append(f"**需求重述：** {tstruct.get('requirements_restatement', 'N/A')}")
        sections.append(f"**類型：** {tstruct.get('input_type', 'N/A')}")
        sections.append(f"**領域：** {', '.join(tstruct.get('domain', []))}")

        objectives = tstruct.get("objectives", [])
        if objectives:
            sections.append(f"**目標：** {'; '.join(objectives)}")

        constraints = tstruct.get("constraints", {})
        constraint_parts = []
        for k, v in constraints.items():
            if v:
                constraint_parts.append(f"{k}={v}")
        if constraint_parts:
            sections.append(f"**限制：** {', '.join(constraint_parts)}")

        # Section 2: 子任務清單
        sections.append("\n## 子任務清單\n")
        for st in tstruct.get("subtasks", []):
            sections.append(
                f"- [{st.get('subtask_id', '?')}] {st.get('description', '')} "
                f"(phase={st.get('phase', '?')}, risk={st.get('risk_level', '?')})"
            )

        # Section 3: 檢索到的技能
        if skill_details:
            sections.append("\n## 可用技能（按 Activation Score 排序）\n")
        for detail in skill_details:
            source = detail["source_path"]
            sections.append(f"### {detail['name']}")
            sections.append(f"[來源: {source}]\n")

            # 擷取 SKILL.md 中的 Description 和 Execution Policy
            md = detail["skill_md"]
            if md:
                # 擷取 Description section
                desc = self._extract_md_section(md, "Description")
                if desc:
                    sections.append(f"**描述：** {desc[:300]}")

                # [P2-1] 原本硬找 "Execution Policy"，但 A3 產的技能寫的是
                # "## Strategy Steps (πσ)" —— 結果每一個 A3 生的技能被檢索出來時，
                # 塞進 working memory 的執行策略都是空的（A2 的技能檢索近乎無效，
                # 這也是 TD-1「sim≈0」的真正成因之一）。改用共用 alias 表。
                from skill_md_sections import strategy_text
                policy, _src = strategy_text(md)
                if policy:
                    sections.append(f"**執行策略：** {policy[:400]}")

            # Lessons（失敗教訓優先）
            if detail["lessons"]:
                sections.append("**歷史教訓：**")
                for lesson in detail["lessons"]:
                    sections.append(f"  - [{lesson['file']}] {lesson['content'][:200]}")

            # Examples
            if detail["examples"]:
                sections.append("**成功範例：**")
                for ex in detail["examples"]:
                    sections.append(f"  - [{ex['file']}] {ex['content'][:200]}")

            sections.append("")  # blank line separator

        # Section 4: 最近 trace
        if traces:
            sections.append("## 最近相關執行記錄\n")
            for trace in traces:
                sections.append(f"### {trace['file']}")
                for step in trace["steps"][-3:]:  # 最後 3 步
                    action = step.get("action", "?")
                    outcome = step.get("outcome", "?")
                    sections.append(f"  - action: {str(action)[:100]} → outcome: {str(outcome)[:100]}")

        return "\n".join(sections)

    # ── Step 6: LLM 計畫生成 ─────────────────────────────────

    def _generate_plan(self, tstruct: dict, working_memory: str) -> str:
        """
        呼叫 LLM 生成結構化執行計畫。

        System prompt 要求 LLM：
        - 根據子任務 DAG 排序執行順序
        - 為每個步驟標注使用的技能（含來源路徑）
        - 標注風險等級和備用方案
        """
        system_prompt = """你是 SIES 系統的 A2 Memory-Guided Planner。

你的任務是根據「任務結構」和「可用技能」生成一份結構化執行計畫。

## 輸出格式（嚴格 JSON）

```json
{
  "plan_id": "P-{task_id}",
  "steps": [
    {
      "step_id": 1,
      "subtask_ref": "ST-xxx-1",
      "action": "具體要做什麼（一句話）",
      "skill_used": "skill-name",
      "skill_source": "skills/active/skill-name/SKILL.md",
      "tool_hint": "建議使用的工具（如 code_execution, knowledge 等）",
      "risk_level": "low|medium|high",
      "fallback": "如果失敗的備用方案"
    }
  ],
  "execution_order": "描述哪些步驟可平行、哪些必須序列",
  "estimated_total_steps": 3,
  "notes": "任何補充說明"
}
```

## 規則

1. 每個 step 必須標注 skill_used 和 skill_source（從可用技能中選擇）
2. 遵守子任務的 depends_on 依賴關係和 phase 分組
3. 同 phase 的子任務可以平行執行
4. 如果沒有合適的技能，skill_used 填 "none"，並在 notes 中說明
5. 只輸出 JSON，不要輸出其他文字
"""

        user_message = f"""## 任務結構（來自 A1）

```json
{json.dumps(tstruct, ensure_ascii=False, indent=2)}
```

## Working Memory（技能 + 歷史記錄）

{working_memory}

請根據以上資訊生成結構化執行計畫。"""

        try:
            response = self.llm.chat(system_prompt, user_message)
            return response.content
        except Exception as e:
            print(f"[memory_planner] LLM call failed: {e}")
            return json.dumps({
                "plan_id": f"P-{tstruct.get('task_id', 'unknown')}",
                "steps": [],
                "error": str(e),
                "notes": "LLM call failed, plan generation aborted",
            })

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _extract_md_section(content: str, section_name: str) -> str:
        """從 markdown 中擷取指定 section"""
        import re
        pattern = rf"^##\s+{re.escape(section_name)}.*?\n(.*?)(?=^##\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""


# ── 直接執行測試 ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import time

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    print("=" * 60)
    print("memory_planner.py — A2 測試")
    print("=" * 60)

    planner = MemoryPlanner(config_path)

    # 模擬一個 Tstruct（來自 A1 的輸出）
    mock_tstruct = {
        "task_id": "T-test001",
        "original_task": "Write a Python script that reads a CSV file, removes duplicate rows, and saves the result",
        "input_type": "code_task",
        "domain": ["programming", "python", "data-processing"],
        "requirements_restatement": "Create a Python script to load CSV, remove duplicate rows, save cleaned result.",
        "subtasks": [
            {
                "subtask_id": "ST-test001-1",
                "description": "Read CSV file with pandas",
                "why": "Must load data before processing",
                "depends_on": [],
                "input_type": "code_task",
                "expected_output": "DataFrame loaded",
                "risk_level": "low",
                "risk_note": "File encoding issues possible",
                "estimated_complexity": "low",
                "phase": 1,
            },
            {
                "subtask_id": "ST-test001-2",
                "description": "Remove duplicate rows",
                "why": "Core requirement of the task",
                "depends_on": ["ST-test001-1"],
                "input_type": "code_task",
                "expected_output": "Cleaned DataFrame",
                "risk_level": "low",
                "risk_note": "",
                "estimated_complexity": "low",
                "phase": 2,
            },
            {
                "subtask_id": "ST-test001-3",
                "description": "Write output CSV",
                "why": "Persist result for downstream use",
                "depends_on": ["ST-test001-2"],
                "input_type": "code_task",
                "expected_output": "CSV file saved",
                "risk_level": "low",
                "risk_note": "",
                "estimated_complexity": "low",
                "phase": 3,
            },
        ],
        "constraints": {"time": None, "resources": "Python", "format": "CSV"},
        "objectives": ["Remove duplicates from CSV", "Save cleaned file"],
        "risks_and_mitigations": [
            {"risk": "Large file memory issues", "mitigation": "Use chunked reading"}
        ],
        "clarification_needed": [],
        "metadata": {"model": "test", "decompose_time": 0},
    }

    # Test 1: 只做技能選擇（不呼叫 LLM）
    print("\n--- Test 1: select_skills (no LLM) ---")
    t0 = time.time()
    selected = planner.select_skills(mock_tstruct)
    print(f"Selection time: {time.time() - t0:.2f}s")
    print(f"Selected {len(selected)} skills")
    for s in selected:
        print(f"  [{s['name']}] A={s['activation_score']}")

    # Test 2: 完整計畫生成（需要 LLM server 運行中）
    print("\n--- Test 2: full plan (requires LLM server on :8080) ---")
    try:
        t0 = time.time()
        result = planner.plan(mock_tstruct)
        elapsed = time.time() - t0
        print(f"Plan time: {elapsed:.1f}s")
        print(f"Task: {result['task_id']}")
        print(f"Skills: {[s['name'] for s in result['selected_skills']]}")
        print(f"Working Memory length: {len(result['working_memory'])} chars")
        print(f"\n--- Execution Plan ---")
        print(result["execution_plan"][:2000])
    except Exception as e:
        print(f"LLM not available, skipping: {e}")
        print("(This is OK if your LLM server is not running)")
