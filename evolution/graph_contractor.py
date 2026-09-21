"""
graph_contractor.py — Φ-iii 子圖收縮 (W12)
============================================
論文 Definition 8 step iii + Lemma 2（收縮保持可解性）。

職責：
  1. 讀 skill_cooccurrence 找出符合雙閾值的候選 pair
  2. 取 top-1（按 support 降序、lift 降序）
  3. 建立 macro-skill：
     - graph 加新節點 macro-{A}-{B}
     - utility = (U_A + U_B) / 2
     - 外部邊取 max(weight) 合併
     - 原 A、B tier 改 cold（純 graph 操作，物理搬移交給 Φ-iv）
  4. 寫 macro-skill SKILL.md（拼接合成，不用 LLM）

依賴：
  evolution/skill_cooccurrence.py
  parse_graph_index.py
  config.yaml
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml
import networkx as nx

from evolution.skill_cooccurrence import analyze_cooccurrence, CooccurrencePair

logger = logging.getLogger(__name__)

TZ_TPE = timezone(timedelta(hours=8))


@dataclass
class ContractionRecord:
    macro_name: str
    parent_a: str
    parent_b: str
    parent_a_old_tier: str
    parent_b_old_tier: str
    macro_utility: float
    edges_inherited: int
    skill_md_path: str
    pair_support: float
    pair_lift: float


def add_composes_into_edges(graph, macro_name: str, parents: list) -> int:
    """
    幫一個 macro 補上 parent --composes_into--> macro 的邊。

    收縮時呼叫；也用來為**既有**的 macro 從 frontmatter 的 parent_skills 回填。
    回傳實際新增的邊數（每個 macro 應該是 len(parents)）。
    """
    n = 0
    for pnode in parents:
        if pnode not in graph.nodes or pnode == macro_name:
            continue
        graph.add_edge(pnode, macro_name, relation="composes_into", weight=1.0,
                       provenance="phi_iii_contraction")
        n += 1
    # frontmatter 的 linked_nodes 原本一直是空 list，補上讓檔案自述也對得起來
    if macro_name in graph.nodes:
        graph.nodes[macro_name]["parent_skills"] = list(parents)
        graph.nodes[macro_name]["linked_nodes"] = list(parents)
    return n


def backfill_existing_macros(graph, skills_root="skills") -> dict:
    """
    為圖上既有的 macro 從各自 SKILL.md 的 parent_skills 回填 composes_into 邊。

    既有 2 個 macro 是在 P3-3 之前收縮出來的，degree 都是 0。
    """
    import yaml
    from pathlib import Path as _P
    added, done = 0, []
    for name, attrs in list(graph.nodes(data=True)):
        if not str(name).startswith("macro-"):
            continue
        if any(d.get("relation") == "composes_into"
               for _, _, d in graph.in_edges(name, data=True)):
            continue                      # 已經有了
        parents = attrs.get("parent_skills")
        if not parents:                   # 圖上沒有就去讀 SKILL.md
            md = _P(attrs.get("path", "")) if attrs.get("path") else None
            if md is None or not md.exists():
                cands = list(_P(skills_root).glob(f"*/{name}/SKILL.md"))
                md = cands[0] if cands else None
            if md and md.exists():
                txt = md.read_text(encoding="utf-8")
                try:
                    fm = yaml.safe_load(txt.split("---", 2)[1]) or {}
                except Exception:  # noqa: BLE001
                    fm = {}
                parents = fm.get("parent_skills") or []
        if parents:
            added += add_composes_into_edges(graph, name, parents)
            done.append(name)
    return {"macros": done, "edges_added": added}


class GraphContractor:
    """Φ-iii 子圖收縮器。"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        evo_cfg = self.config.get("evolution", {})
        self.delta = evo_cfg.get("delta", 0.3)  # min support
        self.min_lift = 1.5  # 守護機制（v4.7 規格，不在 config 中）

        project_root = Path(self.config.get("system", {}).get("project_root", "."))
        self.skills_root = project_root / "skills"
        self.active_dir = self.skills_root / "active"
        self.summary_path = (
            project_root /
            self.config.get("system", {}).get("trace_dir", "memory/episodic") /
            "run_summary.jsonl"
        )

        logger.info(
            f"[GraphContractor] thresholds: support≥{self.delta}, lift>{self.min_lift}"
        )

    # ── 公開 API ──────────────────────────────────────────

    def contract(self, graph: nx.DiGraph) -> list[ContractionRecord]:
        """
        執行一次 Φ-iii 收縮（每次最多一對，守護機制）。

        Returns:
            ContractionRecord list（成功收縮的 macro-skill），
            無候選或失敗時回傳空 list。
        """
        # 1. 找候選
        pairs = analyze_cooccurrence(
            str(self.summary_path),
            min_support=self.delta,
            min_lift=self.min_lift,
        )

        if not pairs:
            logger.info("[Φ-iii] No co-occurrence pairs pass thresholds")
            return []

        # 2. 找第一個雙親都還活著（在 graph 中且非 macro）的 pair
        chosen = None
        for p in pairs:
            if not self._can_contract(graph, p):
                continue
            chosen = p
            break

        if chosen is None:
            logger.info(
                f"[Φ-iii] {len(pairs)} candidate pairs but none contractable "
                f"(parents missing or already macro)"
            )
            return []

        # 3. 執行收縮
        record = self._do_contraction(graph, chosen)
        if record is None:
            return []

        logger.info(
            f"[Φ-iii] ✓ Contracted ({chosen.skill_a}, {chosen.skill_b}) "
            f"→ {record.macro_name} (U={record.macro_utility:.4f}, "
            f"support={chosen.support:.2f}, lift={chosen.lift:.2f})"
        )
        return [record]

    # ── 內部 ──────────────────────────────────────────────

    def _can_contract(self, graph: nx.DiGraph, p: CooccurrencePair) -> bool:
        """檢查 pair 是否可收縮：兩端都在 graph、都不是 macro、都不在 archive。"""
        for skill in (p.skill_a, p.skill_b):
            if skill not in graph.nodes:
                logger.debug(f"[Φ-iii] {skill} not in graph, skipping pair")
                return False
            if skill.startswith("macro-"):
                logger.debug(f"[Φ-iii] {skill} is already macro, skipping pair")
                return False
            tier = graph.nodes[skill].get("tier", "active")
            if tier == "archive":
                logger.debug(f"[Φ-iii] {skill} is archived, skipping pair")
                return False
        # macro 名稱不能與既有節點衝突
        macro_name = self._compose_macro_name(p.skill_a, p.skill_b)
        if macro_name in graph.nodes:
            logger.debug(f"[Φ-iii] {macro_name} already exists, skipping pair")
            return False
        return True

    @staticmethod
    def _compose_macro_name(a: str, b: str) -> str:
        """命名規則：macro-{較短的}-{較長的}（穩定排序）。"""
        # 按字母排序避免順序敏感
        s1, s2 = sorted([a, b])
        return f"macro-{s1}-{s2}"

    def _do_contraction(
        self, graph: nx.DiGraph, p: CooccurrencePair
    ) -> Optional[ContractionRecord]:
        """執行收縮：建 macro 節點 + 合併邊 + 原節點降 cold + 寫 SKILL.md。"""
        a, b = p.skill_a, p.skill_b
        attrs_a = dict(graph.nodes[a])
        attrs_b = dict(graph.nodes[b])
        old_tier_a = attrs_a.get("tier", "active")
        old_tier_b = attrs_b.get("tier", "active")

        macro_name = self._compose_macro_name(a, b)

        # Utility: (U_A + U_B) / 2
        macro_utility = round(
            (float(attrs_a.get("utility", 0.5)) +
             float(attrs_b.get("utility", 0.5))) / 2.0,
            4,
        )

        # Domain: 聯集
        domains_a = attrs_a.get("domain", [])
        domains_b = attrs_b.get("domain", [])
        if isinstance(domains_a, str):
            domains_a = [domains_a]
        if isinstance(domains_b, str):
            domains_b = [domains_b]
        macro_domain = sorted(set(domains_a) | set(domains_b))

        # 寫 SKILL.md（拼接）
        skill_md_path = self._write_macro_skill_md(
            macro_name, a, b, attrs_a, attrs_b, macro_domain, macro_utility, p
        )
        if skill_md_path is None:
            logger.error(f"[Φ-iii] Failed to write SKILL.md for {macro_name}")
            return None

        # 加 macro 節點
        graph.add_node(
            macro_name,
            tier="active",
            utility=macro_utility,
            frequency=0,
            domain=macro_domain,
            type="general",
            version=1,
            path=f"skills/active/{macro_name}/SKILL.md",
        )

        # 合併外部邊
        edges_inherited = self._merge_external_edges(graph, a, b, macro_name)

        # [P3-3] parent → macro 的組合邊。
        # 這是 RF-1 的直接修補：收縮原本只 add_node，兩個 parent 若本身是孤島，
        # 產出的 macro 也是孤島（實測既有 2 個 macro degree 都是 0）。
        # 論文 Definition 7 的語意是 (Σ \ {σi..σj}) ∪ {σ*} —— 也就是把 parent
        # 從圖上移除。§10-4 決定**不移除**（移除會同時毀掉這裡的 composes_into
        # 邊、macro 連通度驗收、以及 demo 上「點開 macro 看到它由誰組成」），
        # parent 留在圖上、tier 降 cold。這個偏離要在論文寫明。
        add_composes_into_edges(graph, macro_name, [a, b])

        # 原節點 tier 改 cold（純 graph 操作；物理搬移由 Φ-iv 處理）
        graph.nodes[a]["tier"] = "cold"
        graph.nodes[b]["tier"] = "cold"

        return ContractionRecord(
            macro_name=macro_name,
            parent_a=a,
            parent_b=b,
            parent_a_old_tier=old_tier_a,
            parent_b_old_tier=old_tier_b,
            macro_utility=macro_utility,
            edges_inherited=edges_inherited,
            skill_md_path=skill_md_path,
            pair_support=p.support,
            pair_lift=p.lift,
        )

    def _merge_external_edges(
        self, graph: nx.DiGraph, a: str, b: str, macro_name: str
    ) -> int:
        """
        合併 A、B 的外部邊到 macro。
        - A→B 和 B→A 邊變成 macro 內部，丟棄（不加到 graph）
        - 同向到第三方節點：取 max(weight)
        """
        # Outgoing
        out_edges = {}  # target -> (max_weight, relation)
        for src in (a, b):
            for _, tgt, attrs in graph.out_edges(src, data=True):
                if tgt in (a, b):
                    continue  # 內部邊，丟棄
                w = float(attrs.get("weight", 0.5))
                rel = attrs.get("relation", "sequential")
                if tgt in out_edges:
                    if w > out_edges[tgt][0]:
                        out_edges[tgt] = (w, rel)
                else:
                    out_edges[tgt] = (w, rel)

        # Incoming
        in_edges = {}  # source -> (max_weight, relation)
        for tgt in (a, b):
            for src, _, attrs in graph.in_edges(tgt, data=True):
                if src in (a, b):
                    continue
                w = float(attrs.get("weight", 0.5))
                rel = attrs.get("relation", "sequential")
                if src in in_edges:
                    if w > in_edges[src][0]:
                        in_edges[src] = (w, rel)
                else:
                    in_edges[src] = (w, rel)

        # 寫到 graph
        count = 0
        for tgt, (w, rel) in out_edges.items():
            graph.add_edge(macro_name, tgt, relation=rel, weight=round(w, 4))
            count += 1
        for src, (w, rel) in in_edges.items():
            graph.add_edge(src, macro_name, relation=rel, weight=round(w, 4))
            count += 1

        return count

    def _write_macro_skill_md(
        self,
        macro_name: str,
        parent_a: str,
        parent_b: str,
        attrs_a: dict,
        attrs_b: dict,
        macro_domain: list[str],
        macro_utility: float,
        p: CooccurrencePair,
    ) -> Optional[str]:
        """拼接 parent A、B 的 SKILL.md 內容生成 macro SKILL.md。"""
        path_a = self.skills_root.parent / attrs_a.get("path", "")
        path_b = self.skills_root.parent / attrs_b.get("path", "")

        # 處理路徑（path 可能是相對 project_root 的）
        if not path_a.is_absolute():
            path_a = Path(attrs_a.get("path", ""))
        if not path_b.is_absolute():
            path_b = Path(attrs_b.get("path", ""))

        if not path_a.exists() or not path_b.exists():
            logger.warning(
                f"[Φ-iii] Parent SKILL.md missing: "
                f"a={path_a.exists()}, b={path_b.exists()}"
            )
            return None

        # 讀 parent SKILL.md（去 frontmatter，只留 body）
        body_a = self._strip_frontmatter(path_a.read_text(encoding="utf-8"))
        body_b = self._strip_frontmatter(path_b.read_text(encoding="utf-8"))

        # 組 frontmatter
        frontmatter = {
            "name": macro_name,
            "description": (
                f"Macro-skill composed of '{parent_a}' and '{parent_b}'. "
                f"These two skills frequently co-occur in successful traces "
                f"(support={p.support:.2f}, lift={p.lift:.2f}) and are merged "
                f"into a single composite skill."
            ),
            "version": "1",
            "author": "SIES-Phi-iii",
            "tags": macro_domain,
            "tier": "active",
            "utility": macro_utility,
            "frequency": 0,
            "reinforcement": 0.0,
            "cost": 0.0,
            "domain": macro_domain,
            "type": "general",
            "linked_nodes": [],
            "skill_source": "phi_iii_contraction",
            "parent_skills": [parent_a, parent_b],
        }

        fm_str = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # 標注 + 拼接
        now = datetime.now(TZ_TPE).isoformat()
        body = (
            f"<!-- Generated from contraction of: [{parent_a}, {parent_b}] "
            f"on {now} (support={p.support:.2f}, lift={p.lift:.2f}) -->\n\n"
            f"## Description\n\n"
            f"This macro-skill combines '{parent_a}' and '{parent_b}'. "
            f"Use it when both component skills would naturally apply.\n\n"
            f"---\n\n"
            f"## Component Skill A: {parent_a}\n\n"
            f"{body_a}\n\n"
            f"---\n\n"
            f"## Component Skill B: {parent_b}\n\n"
            f"{body_b}\n"
        )

        content = f"---\n{fm_str}---\n\n{body}"

        # 寫入 active/{macro_name}/SKILL.md
        macro_dir = self.active_dir / macro_name
        macro_dir.mkdir(parents=True, exist_ok=True)
        skill_md_path = macro_dir / "SKILL.md"
        skill_md_path.write_text(content, encoding="utf-8")

        logger.info(f"[Φ-iii] Wrote macro SKILL.md to {skill_md_path}")
        return f"skills/active/{macro_name}/SKILL.md"

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """移除 YAML frontmatter，只保留 markdown body。"""
        m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", content, re.DOTALL)
        if m:
            return m.group(1).strip()
        return content.strip()