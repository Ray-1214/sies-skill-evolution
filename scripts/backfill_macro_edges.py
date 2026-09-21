"""
backfill_macro_edges.py — 為既有 macro 回填 composes_into 邊（P3-3，一次性）
==========================================================================
既有 2 個 macro 是在 P3-3 之前收縮出來的，收縮那時只 add_node 不建邊，
兩個 parent 本身又是孤島，所以 macro 的 degree 都是 0（RF-1 的直接證據）。

從各自 SKILL.md 的 parent_skills 回填 parent --composes_into--> macro。

dry-run 預設；--apply 才寫檔。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import parse_graph_index as pgi                      # noqa: E402
from evolution.graph_contractor import backfill_existing_macros  # noqa: E402

GI = ROOT / "skills" / "GRAPH_INDEX.md"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="真的寫回 GRAPH_INDEX.md")
    args = ap.parse_args()

    g = pgi.build_graph(pgi.parse_graph_index(str(GI)))
    before_n, before_e = g.number_of_nodes(), g.number_of_edges()
    rep = backfill_existing_macros(g)

    macros = [n for n in g.nodes if str(n).startswith("macro-")]
    connected = [m for m in macros if g.degree(m) > 0]
    ci = [(u, v) for u, v, d in g.edges(data=True) if d.get("relation") == "composes_into"]

    print(f"  nodes {before_n} → {g.number_of_nodes()}   edges {before_e} → {g.number_of_edges()}")
    print(f"  回填 macro {len(rep['macros'])} 個，新增 composes_into 邊 {rep['edges_added']}")
    print(f"  macro 連回 parent: {len(connected)}/{len(macros)}")
    for u, v in ci:
        print(f"    {u[:44]:44s} --composes_into--> {v[:44]}")

    if args.apply:
        pgi.graph_to_index_md(g, str(GI))
        print(f"\n  ✓ 已寫回 {GI}")
    else:
        print(f"\n  (dry-run；加 --apply 才寫檔)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
