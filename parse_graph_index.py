"""
parse_graph_index.py — GRAPH_INDEX.md 解析器

功能：
  1. 讀取 skills/GRAPH_INDEX.md
  2. 解析 YAML 區塊中的 nodes 和 edges
  3. 初始化 NetworkX 有向加權圖
  4. 提供基本圖譜查詢 API

對應論文：
  - Definition 3: Skill Graph G = (Σ, E, W)
  - Eq. 20-21: Activation Score 計算所需的 centrality

依賴：
  pip install networkx pyyaml --break-system-packages
"""

import re
import yaml
import json
import networkx as nx
from pathlib import Path
from typing import Optional


def extract_yaml_blocks(md_content: str) -> list[str]:
    """從 markdown 中提取所有 ```yaml ... ``` 區塊"""
    pattern = r"```yaml\s*\n(.*?)```"
    return re.findall(pattern, md_content, re.DOTALL)


def parse_graph_index(filepath: str = "skills/GRAPH_INDEX.md") -> dict:
    """
    解析 GRAPH_INDEX.md，回傳結構化字典。
    Returns: { "meta": {...}, "nodes": [...], "edges": [...] }
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"GRAPH_INDEX.md not found at {filepath}")
    
    content = path.read_text(encoding="utf-8")
    yaml_blocks = extract_yaml_blocks(content)
    
    if len(yaml_blocks) < 3:
        raise ValueError(
            f"Expected at least 3 YAML blocks (meta, nodes, edges), found {len(yaml_blocks)}"
        )
    
    meta = yaml.safe_load(yaml_blocks[0])
    nodes_data = yaml.safe_load(yaml_blocks[1])
    edges_data = yaml.safe_load(yaml_blocks[2])
    
    return {
        "meta": meta,
        "nodes": nodes_data.get("nodes", []),
        "edges": edges_data.get("edges", []),
    }


def build_graph(parsed: dict) -> nx.DiGraph:
    """
    從解析結果建立 NetworkX 有向加權圖。
    對應論文 Definition 3: G = (Σ, E, W)
    """
    G = nx.DiGraph()
    
    # [P2-0] 讀回來這一側原本也有同一個白名單 —— 序列化留住了，反序列化又丟掉。
    # 兩邊都要保留未知屬性，provenance / evidence_task_ids / parent_skills 才活得過
    # 一次 load→save 的來回。
    for node in parsed["nodes"]:
        attrs = {
            "tier": node.get("tier", "active"),
            "utility": node.get("utility", 0.5),
            "frequency": node.get("frequency", 0),
            "domain": node.get("domain", []),
            "type": node.get("type", "general"),
            "version": node.get("version", 1),
            "path": node.get("path", ""),
        }
        attrs.update({k: v for k, v in node.items()
                      if k not in attrs and k != "name"})
        G.add_node(node["name"], **attrs)

    for edge in parsed["edges"]:
        attrs = {
            "relation": edge.get("relation", "sequential"),
            "weight": edge.get("weight", 0.5),
        }
        attrs.update({k: v for k, v in edge.items()
                      if k not in attrs and k not in ("source", "target")})
        G.add_edge(edge["source"], edge["target"], **attrs)
    
    return G


def get_node_info(G: nx.DiGraph, name: str) -> Optional[dict]:
    """取得單一節點的完整資訊"""
    if name not in G.nodes:
        return None
    attrs = dict(G.nodes[name])
    attrs["name"] = name
    attrs["in_degree"] = G.in_degree(name)
    attrs["out_degree"] = G.out_degree(name)
    attrs["neighbors_out"] = list(G.successors(name))
    attrs["neighbors_in"] = list(G.predecessors(name))
    return attrs


def compute_centrality(G: nx.DiGraph) -> dict[str, float]:
    """
    計算 in-degree centrality（論文 Eq. 20-21 中 Activation Score 的 centrality 分量）
    """
    return nx.in_degree_centrality(G)


def get_active_skills(G: nx.DiGraph) -> list[dict]:
    """取得所有 active 層的技能，按效用值降序"""
    active = []
    for name, attrs in G.nodes(data=True):
        if attrs.get("tier") == "active":
            info = dict(attrs)
            info["name"] = name
            active.append(info)
    active.sort(key=lambda x: x.get("utility", 0), reverse=True)
    return active


def graph_summary(G: nx.DiGraph) -> dict:
    """圖譜摘要統計"""
    tiers = {}
    for _, attrs in G.nodes(data=True):
        t = attrs.get("tier", "unknown")
        tiers[t] = tiers.get(t, 0) + 1
    
    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "tier_distribution": tiers,
        "density": nx.density(G),
        "is_dag": nx.is_directed_acyclic_graph(G),
        "avg_in_degree": sum(d for _, d in G.in_degree()) / max(G.number_of_nodes(), 1),
    }


def graph_to_index_md(G: nx.DiGraph, output_path: str = "skills/GRAPH_INDEX.md"):
    """將 NetworkX 圖序列化回 GRAPH_INDEX.md 格式。由 evolution_operator.py 呼叫。"""
    from datetime import datetime, timezone, timedelta
    
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).isoformat()
    
    tiers = {}
    for _, attrs in G.nodes(data=True):
        t = attrs.get("tier", "active")
        tiers[t] = tiers.get(t, 0) + 1
    
    meta = {
        "last_updated": now,
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "graph_version": 1,
        "tier_distribution": tiers,
    }
    
    # [P2-0] 這裡原本是 8 個 key 的白名單，**任何其他 node 屬性每次 Φ 存檔都會
    # 被靜默丟掉** —— P2-4 的 evidence_task_ids、P3-3 的 parent_skills、
    # P3-5 的 provenance 欄位寫進去都留不住。改成保留未知屬性。
    _NODE_CORE = ("tier", "utility", "frequency", "domain", "type", "version", "path")
    nodes = []
    for name, attrs in G.nodes(data=True):
        rec = {
            "name": name, "tier": attrs.get("tier", "active"),
            "utility": round(attrs.get("utility", 0.5), 4),
            "frequency": attrs.get("frequency", 0),
            "domain": attrs.get("domain", []),
            "type": attrs.get("type", "general"),
            "version": attrs.get("version", 1),
            "path": attrs.get("path", f"skills/{attrs.get('tier', 'active')}/{name}/SKILL.md"),
        }
        for k, v in attrs.items():          # 保留未知屬性
            if k not in _NODE_CORE and k != "name":
                rec[k] = v
        nodes.append(rec)

    _EDGE_CORE = ("relation", "weight")
    edges = []
    for src, tgt, attrs in G.edges(data=True):
        rec = {
            "source": src, "target": tgt,
            "relation": attrs.get("relation", "sequential"),
            "weight": round(attrs.get("weight", 0.5), 4),
        }
        for k, v in attrs.items():          # 邊也一樣：provenance/path_id 要留得住
            if k not in _EDGE_CORE:
                rec[k] = v
        edges.append(rec)
    
    md = f"""# GRAPH_INDEX — 技能圖譜根節點索引

<!-- 此檔案由 graph_manager.py / evolution_operator.py 自動生成 -->

## Meta

```yaml
{yaml.dump(meta, allow_unicode=True, default_flow_style=False).strip()}
```

## Nodes

```yaml
{yaml.dump({"nodes": nodes}, allow_unicode=True, default_flow_style=False).strip()}
```

## Edges

```yaml
{yaml.dump({"edges": edges}, allow_unicode=True, default_flow_style=False).strip()}
```
"""
    Path(output_path).write_text(md, encoding="utf-8")
    print(f"[graph_manager] GRAPH_INDEX.md updated: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


if __name__ == "__main__":
    import sys
    filepath = sys.argv[1] if len(sys.argv) > 1 else "skills/GRAPH_INDEX.md"
    
    print(f"=== Parsing {filepath} ===\n")
    parsed = parse_graph_index(filepath)
    print(f"Meta: {json.dumps(parsed['meta'], indent=2, ensure_ascii=False)}\n")
    
    G = build_graph(parsed)
    summary = graph_summary(G)
    print(f"Summary: {json.dumps(summary, indent=2, ensure_ascii=False)}\n")
    
    centrality = compute_centrality(G)
    print("In-degree Centrality:")
    for name, c in sorted(centrality.items(), key=lambda x: -x[1]):
        print(f"  {name}: {c:.4f}")
    
    print("\nActive Skills:")
    for skill in get_active_skills(G):
        print(f"  [{skill['name']}] U={skill['utility']}, freq={skill['frequency']}, domain={skill['domain']}")
