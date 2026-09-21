"""
provenance_edges.py — 從課程路徑落地成圖上的邊（P3-5）
======================================================
**這是 P3 的失敗保險。**

P3-2 的共現路線是一場有機制支撐的賭注：要子技能在多題裡反覆一起被檢索，統計量
才過得了門檻。但想要 #3 的語意（「簡報基礎 → 美化 → 依觀眾排序」那條鏈）需要的
是**先後／前置**關係，而共現產生的是**統計關聯**，兩者不是同一種東西 —— 就算
P3-2 全盤成功，也產不出那條鏈。

P5-a 的「方向 → 5-10 個由淺到深的子任務」**本身就是一條有序學習路徑**。把那個
順序直接落地成邊即可，不需要任何統計推論：

    子任務 k 產生的技能  --follows-->   子任務 k+1 產生的技能      （弱，weight 0.4）
    當 k+1 的 trace 真的檢索到 k 的技能 → 升級成 requires          （強，weight 0.7）

三個好處：
  1. **不依賴共現這場賭** —— P3-2 全盤失敗也保證有非 bootstrap 的邊
  2. 產生的正好是 demo 要講的那條鏈，點開就是「解析 → 驗證 → 聚合 → join → 報表」
  3. 論文上誠實：provenance-derived，不是統計推論，而且對得上論文 Definition 3
     的邊型 **(b) functional dependency**

資料來源：run_summary.jsonl 裡帶 `path_id` / `path_pos` / `produced_skills` /
`skills_used` 的紀錄（P5-a 出題時寫入、P1-a 的 schema 承載）。
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

W_FOLLOWS = 0.4
W_REQUIRES = 0.7


@dataclass
class ProvenanceEdge:
    source: str
    target: str
    relation: str            # "follows" | "requires"
    weight: float
    path_id: str
    from_pos: int
    to_pos: int
    provenance: str = "curriculum_path"


@dataclass
class ProvenanceReport:
    paths: int = 0
    steps: int = 0
    edges_added: int = 0
    edges_upgraded: int = 0
    skipped_missing_node: int = 0
    edges: list = field(default_factory=list)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def build_edges(records: list[dict]) -> list[ProvenanceEdge]:
    """把帶 path_id/path_pos 的紀錄轉成邊。不碰圖，純函式，好測。"""
    by_path: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("path_id") is not None and r.get("path_pos") is not None:
            by_path[r["path_id"]].append(r)

    edges: list[ProvenanceEdge] = []
    for pid, steps in by_path.items():
        steps.sort(key=lambda r: r["path_pos"])
        for a, b in zip(steps, steps[1:]):
            # 端點優先用「這一步產生的技能」；沒產出就退回「這一步檢索到的技能」，
            # 否則一條 5 題的路徑只要有一步沒抽出新技能，鏈就斷了。
            src = a.get("produced_skills") or a.get("skills_used") or []
            dst = b.get("produced_skills") or b.get("skills_used") or []
            retrieved_next = set(b.get("skills_used") or [])
            for s in src:
                for t in dst:
                    if s == t:
                        continue
                    # k+1 真的檢索到 k 的技能 → 這是實際的前置依賴，不只是順序
                    strong = s in retrieved_next
                    edges.append(ProvenanceEdge(
                        source=s, target=t,
                        relation="requires" if strong else "follows",
                        weight=W_REQUIRES if strong else W_FOLLOWS,
                        path_id=pid, from_pos=a["path_pos"], to_pos=b["path_pos"]))
    return edges


def apply_to_graph(graph, edges: list[ProvenanceEdge]) -> ProvenanceReport:
    """把邊寫進 NetworkX 圖。兩端都要已經在圖上（Φ-ii 插入過）才寫。"""
    rep = ProvenanceReport(edges_added=0)
    seen = set()
    for e in edges:
        if e.source not in graph.nodes or e.target not in graph.nodes:
            rep.skipped_missing_node += 1
            continue
        key = (e.source, e.target)
        if key in seen:
            # 同一對已經寫過：只有「弱 → 強」才覆蓋，不會把 requires 降回 follows
            if e.relation == "requires" and \
                    graph.edges[key].get("relation") == "follows":
                graph.edges[key].update(relation="requires", weight=W_REQUIRES)
                rep.edges_upgraded += 1
            continue
        seen.add(key)
        graph.add_edge(e.source, e.target, relation=e.relation, weight=e.weight,
                       provenance=e.provenance, path_id=e.path_id,
                       from_pos=e.from_pos, to_pos=e.to_pos)
        rep.edges_added += 1
        rep.edges.append(e)
    return rep


def run(graph, summary_path: str = "memory/episodic/run_summary.jsonl",
        records: Optional[list[dict]] = None) -> ProvenanceReport:
    """完整流程：讀紀錄 → 建邊 → 寫圖。回傳報告。"""
    recs = records if records is not None else _load(Path(summary_path))
    edges = build_edges(recs)
    rep = apply_to_graph(graph, edges)
    rep.paths = len({e.path_id for e in edges})
    rep.steps = len([r for r in recs if r.get("path_id") is not None])
    logger.info(f"[P3-5] {rep.paths} 條路徑 / {rep.steps} 步 → "
                f"新增 {rep.edges_added} 條邊（升級 {rep.edges_upgraded}），"
                f"因節點不在圖上跳過 {rep.skipped_missing_node}")
    return rep
