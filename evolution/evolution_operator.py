"""
evolution_operator.py — Φ 演化算子 (W11: Φ-i + Φ-ii)
======================================================
論文 Definition 8: Φ = (Φ-i, Φ-ii, Φ-iii, Φ-iv)

  Φ-i:   效用評估 + 時間衰減     → W11 ✓
  Φ-ii:  技能插入（驗證 + 搬移）  → W11 ✓
  Φ-iii: 子圖收縮                → W12 (stub)
  Φ-iv:  記憶分層更新             → W12 (stub)

依賴：
  evolution/utility_engine.py
  evolution/evolution_triggers.py
  agents/skill_validator.py
  parse_graph_index.py
  embedding_engine.py
  vector_store.py

用法：
    from evolution.evolution_operator import EvolutionOperator
    phi = EvolutionOperator("config.yaml")
    report = phi.evolve(run_result)
"""

import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from pathlib import Path as _Path
from typing import Optional

import sys as _sys
import yaml
import networkx as nx

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from parse_graph_index import parse_graph_index, build_graph, graph_to_index_md
from evolution.utility_engine import UtilityEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class InsertionRecord:
    """Φ-ii 技能插入的結果。"""
    name: str
    source_path: str
    target_path: str
    validation_passed: bool
    rejection_reason: Optional[str] = None


@dataclass
class EvolutionReport:
    """一次 Φ 演化的完整報告。"""
    timestamp: str
    triggered_by: list[str] = field(default_factory=list)

    # Φ-i
    utility_updates: list = field(default_factory=list)
    decay_results: list = field(default_factory=list)

    # Φ-ii
    candidates_found: int = 0
    inserted_skills: list[InsertionRecord] = field(default_factory=list)
    rejected_skills: list[InsertionRecord] = field(default_factory=list)

    # Φ-iii (W12)
    macro_skills_created: list = field(default_factory=list)

    # Φ-iv (W12)
    tier_migrations: list = field(default_factory=list)

    # Meta
    elapsed_seconds: float = 0.0
    graph_nodes_before: int = 0
    graph_nodes_after: int = 0


# ---------------------------------------------------------------------------
# EvolutionOperator
# ---------------------------------------------------------------------------

class EvolutionOperator:
    """
    Φ 演化算子 — 論文 Definition 8。

    W11: Φ-i（效用評估）+ Φ-ii（技能插入）
    W12: Φ-iii（子圖收縮）+ Φ-iv（記憶分層）
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        embedding_engine=None,
        vector_store=None,
    ):
        self.config_path = config_path

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # 路徑
        project_root = Path(self.config.get("system", {}).get("project_root", "."))
        self.graph_index_path = str(project_root / "skills/GRAPH_INDEX.md")
        self.candidates_dir = project_root / "skills/candidates"
        self.active_dir = project_root / "skills/active"
        self.trace_dir = Path(
            self.config.get("system", {}).get("trace_dir", "./memory/episodic")
        )

        # 子模組
        self.utility_engine = UtilityEngine(config_path)

        # 共享 embedding/vector store
        self._engine = embedding_engine
        self._store = vector_store

        logger.info("[EvolutionOperator] initialized")

    # ── 公開 API ──────────────────────────────────────────

    def evolve(
        self,
        run_result=None,
        trigger_result=None,
        force: bool = False,
    ) -> EvolutionReport:
        """
        執行一次完整演化循環：Φ-i → Φ-ii → Φ-iii → Φ-iv。
        """
        t0 = time.time()
        tz = timezone(timedelta(hours=8))
        report = EvolutionReport(
            timestamp=datetime.now(tz).isoformat(),
            triggered_by=(
                trigger_result.reasons if trigger_result else
                (["force"] if force else [])
            ),
        )

        # 載入圖譜
        graph = self._load_graph()
        report.graph_nodes_before = graph.number_of_nodes()

        # ── Φ-i: 效用評估 ──
        logger.info("[Φ] === Step i: Utility Evaluation ===")
        updates, decays = self._step_i_utility_evaluation(graph, run_result)
        report.utility_updates = updates
        report.decay_results = decays

        # ── Φ-ii: 技能插入 ──
        logger.info("[Φ] === Step ii: Skill Insertion ===")
        inserted, rejected = self._step_ii_skill_insertion(graph)
        report.candidates_found = len(inserted) + len(rejected)
        report.inserted_skills = inserted
        report.rejected_skills = rejected

        # ── Φ-iii: 子圖收縮（W12 stub）──
        report.macro_skills_created = self._step_iii_subgraph_contraction(graph)

        # ── Φ-iv: 記憶分層更新（W12 stub）──
        report.tier_migrations = self._step_iv_tier_migration(graph)

        # 回寫
        report.graph_nodes_after = graph.number_of_nodes()
        self._save_graph(graph)

        report.elapsed_seconds = round(time.time() - t0, 2)

        logger.info(
            f"[Φ] === Evolution Complete === "
            f"nodes: {report.graph_nodes_before} → {report.graph_nodes_after}, "
            f"inserted: {len(inserted)}, rejected: {len(rejected)}, "
            f"utility updates: {len(updates)}, "
            f"elapsed: {report.elapsed_seconds}s"
        )

        # 持久化報告
        self._save_report(report)

        return report

    # ── Φ-i: 效用評估 ────────────────────────────────────

    def _step_i_utility_evaluation(
        self,
        graph: nx.DiGraph,
        run_result=None,
    ) -> tuple[list, list]:
        """
        Φ-i：更新效用值 + 時間衰減。

        順序：先 update（從 run_summary 算靜態 U），再 decay。
        """
        # 1. 更新靜態效用
        updates = self.utility_engine.update_all_utilities(graph)

        # 2. 判斷本輪被強化的技能（有使用且成功）
        reinforced = set()
        if run_result is not None:
            skills_used = getattr(run_result, "skills_used", [])
            success = getattr(run_result, "execution_success", False)
            if success and skills_used:
                reinforced = set(skills_used)

        # 3. 時間衰減
        decays = self.utility_engine.apply_decay(graph, reinforced)

        logger.info(
            f"[Φ-i] {len(updates)} utility updates, "
            f"{len(decays)} skills decayed, "
            f"{len(reinforced)} reinforced"
        )

        return updates, decays

    # ── Φ-ii: 技能插入 ───────────────────────────────────

    def _step_ii_skill_insertion(
        self,
        graph: nx.DiGraph,
    ) -> tuple[list[InsertionRecord], list[InsertionRecord]]:
        """
        Φ-ii：從 candidates/ 驗證並插入新技能到 active/。
        """
        if not self.candidates_dir.exists():
            logger.info("[Φ-ii] No candidates/ directory, skipping")
            return [], []

        # 掃描候選
        candidate_dirs = [
            d for d in sorted(self.candidates_dir.iterdir())
            if d.is_dir() and (d / "SKILL.md").exists()
        ]

        if not candidate_dirs:
            logger.info("[Φ-ii] No candidates found")
            return [], []

        logger.info(f"[Φ-ii] Found {len(candidate_dirs)} candidates")

        # 解析候選
        from agents.base_extractor import CandidateSkill
        candidates = []
        candidate_map = {}  # CandidateSkill → dir path

        for cdir in candidate_dirs:
            cs = self._parse_candidate_from_skill_md(cdir / "SKILL.md")
            if cs is not None:
                candidates.append(cs)
                candidate_map[cs.name] = cdir
            else:
                logger.warning(f"[Φ-ii] Failed to parse {cdir.name}")

        if not candidates:
            return [], []

        # 批次驗證
        from agents.skill_validator import SkillValidator
        validator = SkillValidator(
            self.config_path,
            embedding_engine=self._engine,
            vector_store=self._store,
        )
        batch_report = validator.validate_batch(candidates)

        inserted = []
        rejected = []

        for i, vr in enumerate(batch_report.results):
            cs = candidates[i]
            cdir = candidate_map.get(cs.name)
            if cdir is None:
                continue

            target = self.active_dir / cs.name

            if not vr.passed:
                rejected.append(InsertionRecord(
                    name=cs.name,
                    source_path=str(cdir),
                    target_path=str(target),
                    validation_passed=False,
                    rejection_reason=vr.rejection_reason,
                ))
                logger.info(f"[Φ-ii] ✗ {cs.name}: {vr.rejection_reason}")
                continue

            # 檢查 active/ 是否已存在
            if target.exists():
                logger.warning(f"[Φ-ii] {cs.name} already in active/, skipping")
                continue

            # 搬移
            shutil.copytree(cdir, target)
            shutil.rmtree(cdir)

            # 加入圖譜
            domain = cs.domain if isinstance(cs.domain, list) else [cs.domain]
            graph.add_node(
                cs.name,
                tier="active",
                utility=0.5,
                frequency=0,
                domain=domain,
                type=cs.type,
                version=1,
                path=f"skills/active/{cs.name}/SKILL.md",
            )

            # 更新 LanceDB
            self._insert_skill_to_lancedb(cs.name, str(target / "SKILL.md"))

            inserted.append(InsertionRecord(
                name=cs.name,
                source_path=str(cdir),
                target_path=str(target),
                validation_passed=True,
            ))
            logger.info(f"[Φ-ii] ✓ {cs.name} inserted into active/")

        logger.info(
            f"[Φ-ii] Done: {len(inserted)} inserted, {len(rejected)} rejected"
        )
        return inserted, rejected

    # Section header aliases: A3 generates Chinese headers,
    # but we also support English for future compatibility.
    _SECTION_ALIASES = {
        "invocation": [
            "使用條件",           # A3 current output: ## 使用條件 (Iσ)
            "Invocation Condition",
        ],
        "termination": [
            "終止條件",           # A3 current output: ## 終止條件 (βσ)
            "Termination Condition",
        ],
        "strategy": [
            "執行策略",           # A3 current output: ## 執行策略 (πσ)
            "Strategy Steps",
            "Execution Policy",
        ],
    }

    def _parse_candidate_from_skill_md(self, skill_md_path: Path):
        """
        Parse a SKILL.md into a CandidateSkill object.

        Supports both Chinese section headers (A3 output) and English headers.
        """
        try:
            from agents.base_extractor import CandidateSkill
        except ImportError:
            logger.error("[Φ-ii] Cannot import CandidateSkill")
            return None

        if not skill_md_path.exists():
            return None

        content = skill_md_path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            return None

        try:
            fm = yaml.safe_load(fm_match.group(1))
        except yaml.YAMLError:
            return None

        if not fm or not isinstance(fm, dict):
            return None

        name = fm.get("name", skill_md_path.parent.name)
        description = fm.get("description", "")
        domain = fm.get("domain", [])
        if isinstance(domain, str):
            domain = [domain]
        skill_type = fm.get("type", "general")

        # Extract sections using alias lookup (Chinese or English)
        invocation = self._extract_md_section_multi(content, self._SECTION_ALIASES["invocation"])
        termination = self._extract_md_section_multi(content, self._SECTION_ALIASES["termination"])
        strategy_text = self._extract_md_section_multi(content, self._SECTION_ALIASES["strategy"])

        # Parse strategy_steps from markdown list
        strategy_steps = self._parse_list_items(strategy_text, min_len=5)

        # Fallbacks
        if not invocation:
            invocation = f"When a task requires {name}"
        if not termination:
            termination = f"Task using {name} is complete"
        if not strategy_steps:
            strategy_steps = [description[:100] if description else f"Apply {name} skill"]

        confidence = fm.get("confidence", 0.7)

        try:
            return CandidateSkill(
                name=name,
                description=description,
                domain=domain,
                type=skill_type,
                invocation_condition=invocation,
                termination_condition=termination,
                strategy_steps=strategy_steps,
                confidence=confidence,
                source_task_id=fm.get("source_task_id", ""),
            )
        except Exception as e:
            logger.warning(f"[Φ-ii] CandidateSkill init failed for {name}: {e}")
            return None

    def _insert_skill_to_lancedb(self, skill_name: str, skill_path: str) -> bool:
        """將新技能的嵌入向量插入 LanceDB。"""
        if self._engine is None:
            try:
                from embedding_engine import EmbeddingEngine
                self._engine = EmbeddingEngine(self.config_path)
            except Exception as e:
                logger.warning(f"[Φ-ii] EmbeddingEngine not available: {e}")
                return False

        if self._store is None:
            try:
                from vector_store import VectorStore
                self._store = VectorStore(self.config_path)
            except Exception as e:
                logger.warning(f"[Φ-ii] VectorStore not available: {e}")
                return False

        try:
            result = self._engine.embed_skill(skill_path)
            if result is None:
                return False

            self._store.upsert_skills([result])
            return True
        except Exception as e:
            logger.warning(f"[Φ-ii] LanceDB insert failed for {skill_name}: {e}")
            return False

    @staticmethod
    def _extract_md_section_multi(content: str, aliases: list[str]) -> str:
        """
        Extract a markdown section by trying multiple header aliases.

        Matches headers like:
          ## 使用條件 (Iσ)
          ## Invocation Condition
          ### Strategy Steps
        """
        for alias in aliases:
            # Use {{2,3}} to produce literal {2,3} in the f-string regex
            pattern = rf"^#{{2,3}}\s+{re.escape(alias)}[^\n]*\n(.*?)(?=^#{{2,3}}\s|\Z)"
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                text = match.group(1).strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _extract_md_section(content: str, section_name: str) -> str:
        """Extract a markdown section by exact name (legacy, kept for compatibility)."""
        pattern = rf"^#{{2,3}}\s+{re.escape(section_name)}[^\n]*\n(.*?)(?=^#{{2,3}}\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_list_items(text: str, min_len: int = 5) -> list[str]:
        """
        Parse markdown list items from text.

        Handles:
          - Bullet item
          1. Numbered item
          * Star item
        """
        if not text:
            return []

        items = []
        for line in text.split("\n"):
            line = line.strip()
            # Strip list markers: "1. ", "- ", "* "
            cleaned = re.sub(r"^[\d]+\.\s*", "", line)
            cleaned = re.sub(r"^[-*]\s*", "", cleaned)
            cleaned = cleaned.strip()
            if cleaned and len(cleaned) >= min_len:
                items.append(cleaned)
        return items

    # ── Φ-iii: 子圖收縮（W12 stub）───────────────────────

    def _step_iii_subgraph_contraction(self, graph: nx.DiGraph) -> list:
        from evolution.graph_contractor import GraphContractor
        contractor = GraphContractor(self.config_path)
        records = contractor.contract(graph)
        
        # 新建立的 macro-skill 同步 embed 進 LanceDB
        for r in records:
            ok = self._insert_skill_to_lancedb(r.macro_name, r.skill_md_path)
            if ok:
                logger.info(f"[Φ-iii] Embedded {r.macro_name} into LanceDB")
            else:
                logger.warning(f"[Φ-iii] Failed to embed {r.macro_name}")
        
        if records:
            logger.info(f"[Φ-iii] {len(records)} macro-skill(s) created and embedded")
        return records

    # ── Φ-iv: 記憶分層更新（W12 stub）────────────────────

    def _step_iv_tier_migration(self, graph: nx.DiGraph) -> list:
        """Φ-iv: 記憶分層遷移。"""
        from evolution.memory_tier_manager import MemoryTierManager

        # Lazy load vector_store（Φ-ii 沒插入時 self._store 仍是 None）
        if self._store is None:
            try:
                from vector_store import VectorStore
                self._store = VectorStore(self.config_path)
                logger.info("[Φ-iv] VectorStore lazy-loaded for path sync")
            except Exception as e:
                logger.warning(
                    f"[Φ-iv] VectorStore unavailable, paths will be OUT OF SYNC: {e}"
                )

        manager = MemoryTierManager(self.config_path)
        migrations = manager.migrate_all(graph, vector_store=self._store)

        actual = [m for m in migrations if m.skipped_reason is None]
        logger.info(f"[Φ-iv] {len(actual)} actual tier migrations")
        return migrations

    # ── 圖譜 I/O ─────────────────────────────────────────

    def _load_graph(self) -> nx.DiGraph:
        """載入 GRAPH_INDEX.md。"""
        parsed = parse_graph_index(self.graph_index_path)
        return build_graph(parsed)

    def _save_graph(self, graph: nx.DiGraph):
        """回寫 GRAPH_INDEX.md。"""
        graph_to_index_md(graph, self.graph_index_path)

    # ── 報告持久化 ────────────────────────────────────────

    def _save_report(self, report: EvolutionReport):
        """
        將 EvolutionReport 追加到 evolution_log.jsonl。
        """
        log_path = self.trace_dir / "evolution_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "timestamp": report.timestamp,
            "triggered_by": report.triggered_by,
            "graph_nodes_before": report.graph_nodes_before,
            "graph_nodes_after": report.graph_nodes_after,
            "utility_updates_count": len(report.utility_updates),
            "decay_count": len(report.decay_results),
            "candidates_found": report.candidates_found,
            "inserted_count": len(report.inserted_skills),
            "rejected_count": len(report.rejected_skills),
            "inserted_names": [r.name for r in report.inserted_skills],
            "rejected_names": [
                f"{r.name}({r.rejection_reason})" for r in report.rejected_skills
            ],
            "macro_skills_created": len(report.macro_skills_created),
            "tier_migrations": len(report.tier_migrations),
            "elapsed_seconds": report.elapsed_seconds,
        }

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        logger.info(f"[Φ] Report saved to {log_path}")

    # ── Run summary 寫入（靜態，agent_runner 呼叫）────────

    @staticmethod
    def append_run_summary(
        trace_dir: str,
        task_id: str,
        task: str,
        skills_used: list[str],
        success: bool,
        total_steps: int,
    ):
        """
        將一次 run 的摘要追加到 run_summary.jsonl。
        由 agent_runner.run() 呼叫。
        """
        from datetime import datetime, timezone, timedelta

        trace_path = Path(trace_dir)
        trace_path.mkdir(parents=True, exist_ok=True)
        summary_path = trace_path / "run_summary.jsonl"

        tz = timezone(timedelta(hours=8))
        record = {
            "task_id": task_id,
            "task": task[:200],
            "skills_used": skills_used,
            "success": success,
            "total_steps": total_steps,
            "timestamp": datetime.now(tz).isoformat(),
        }

        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI — 手動觸發演化（debug 用）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    phi = EvolutionOperator(config_path)
    report = phi.evolve(force=True)

    print(f"\n{'='*60}")
    print(f"Evolution Report")
    print(f"{'='*60}")
    print(f"Triggered by: {report.triggered_by}")
    print(f"Graph: {report.graph_nodes_before} → {report.graph_nodes_after} nodes")
    print(f"Utility updates: {len(report.utility_updates)}")
    print(f"Decay applied: {len(report.decay_results)}")
    print(f"Candidates found: {report.candidates_found}")
    print(f"Inserted: {len(report.inserted_skills)}")
    for r in report.inserted_skills:
        print(f"  ✓ {r.name}")
    print(f"Rejected: {len(report.rejected_skills)}")
    for r in report.rejected_skills:
        print(f"  ✗ {r.name}: {r.rejection_reason}")
    print(f"Elapsed: {report.elapsed_seconds}s")
