"""
demo_run.py — 終端 demo（給教授看的東西）
=========================================
一條指令跑完整故事，全部在終端 + PNG，沒有 web/3D：

  1. 打一句方向  →  系統拆出一條由淺到深、**每題自帶獨立驗證**的學習路徑
  2. （可選）真的跑幾題
  3. 圖上那條 requires 鏈印出來（箭頭鏈）
  4. 節點 / 邊 / 孤島率的數字 + 邊的來源分類
  5. 有長跑資料的話順便產成長曲線 PNG

    # 全套（會打 LLM 出題，約 3-5 分鐘）
    python scripts/demo_run.py --direction "learn to build a data processing pipeline"

    # 只看圖與鏈，不出題（秒級，彩排/離線用）
    python scripts/demo_run.py --graph-only

    # 用既有長跑的結果講故事
    python scripts/demo_run.py --run <run_id>
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import parse_graph_index as pgi  # noqa: E402

BOOT = {"web-search", "data-analysis", "text-summary", "code-execution", "file-io"}
GI = ROOT / "skills" / "GRAPH_INDEX.md"


def hr(t):
    print(f"\n{'═' * 68}\n  {t}\n{'═' * 68}")


def show_path(direction, domain, dry):
    hr(f"① 給一個方向：「{direction}」")
    import yaml
    from agents.llm_client import LLMClient
    from agents.path_generator import PathGenerator
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    gen = PathGenerator(LLMClient({**cfg.get("llm", {}), "temperature": 0.6}), domain=domain)
    quads = gen.generate(direction, path_id="demo", derive=not dry)
    print(f"\n  系統自己拆出 {len(quads)} 個由淺到深的子任務，每題自帶可執行的驗證：\n")
    for q in quads:
        print(f"   {q['path_pos']}. [L{q['level']} {q['cluster']}] {q['title']}")
        print(f"      {q['task_description'][:96]}")
        exp = q.get("expected") or {}
        for a, sp in exp.items():
            print(f"      驗證：{a} — {sp['kind']}"
                  + (f"（比對 {len(sp.get('values', sp.get('value', [])))} 個值）"
                     if sp["kind"] in ("csv_column", "json_equals") else ""))
    if quads:
        from verify_runner import compute_status
        sts = {compute_status(q.get("expected") or {}) for q in quads}
        print(f"\n  oracle 層級：{sts}")
        print("  （verified_independent = 出題器先產輸入、自己算正解，agent 捏造過不了）")
    return quads


def _is_prov(d):
    """跟 sies_doctor 同一個判準。只認 provenance 屬性的話，序列化一掉屬性
    （parse_graph_index 的白名單幹過這件事）整批機械邊就會被當成學習成果。"""
    return (d.get("relation") in ("follows", "requires")
            or d.get("provenance") == "curriculum_path")


def _walk_requires(edges):
    """找**最長**的一條圖上真實存在的 requires 鏈。

    每個 pos k→k+1 上有一整批邊（該級產出的技能 × 下一級的技能，交叉積 —— 206 條
    就是這樣來的）。把它們全印出來不是「一條鏈」是傾倒。

    貪婪走法會卡住（實測只走 3 個節點就死在 string-normalization…，它在下一級
    只有 follows 沒有 requires）。position 單調遞增 ⇒ (pos, node) 上無環 ⇒ 這是
    DAG 最長路徑，用 DP 解，回傳的每一步都是圖上真的有的那條邊。
    """
    adj = {}
    for e in edges:
        if e.get("relation") == "requires":
            adj.setdefault((e.get("from_pos", 0), e["source"]), []).append(e)
    if not adj:
        return []

    best = {}                     # (pos, node) -> 從這裡出發的最長鏈

    def longest(state):
        if state in best:
            return best[state]
        best[state] = []          # 先佔位，資料若有意外環也不會無限遞迴
        out = []
        for e in adj.get(state, []):
            tail = longest((e.get("to_pos", state[0] + 1), e["target"]))
            if len(tail) + 1 > len(out):
                out = [e] + tail
        best[state] = out
        return out

    return max((longest(s) for s in adj), key=len, default=[])


def show_chain():
    hr("③ 技能圖上長出來的鏈")
    d = pgi.parse_graph_index(str(GI))
    edges = d["edges"]
    prov = [e for e in edges if _is_prov(e)]
    comp = [e for e in edges if e.get("relation") == "composes_into"]

    if not prov:
        print("\n  （還沒有 provenance 邊 —— 跑一次長跑就會長出來：")
        print("     nohup python scripts/w16_run.py --tasks 50 --direction \"...\" &）")
    else:
        paths = {}
        for e in prov:
            paths.setdefault(e.get("path_id"), []).append(e)
        pid, pedges = max(paths.items(), key=lambda kv: len(kv[1]))

        print(f"\n  最長的一條學習路徑：{pid}（{len(pedges)} 條邊）")
        print("\n  ── 逐級（一級 = 課程路徑上的一個位置）──")
        levels = {}
        for e in pedges:
            levels.setdefault(e.get("from_pos", 0), set()).add(e["source"])
            levels.setdefault(e.get("to_pos", 1), set()).add(e["target"])
        for k in sorted(levels):
            names = sorted(levels[k])
            print(f"    pos {k}: " + f"\n{'':11}".join(n[:56] for n in names))
            if k != max(levels):
                print(f"{'':9}│ requires")

        chain = _walk_requires(pedges)
        if chain:
            print("\n  ── 其中一條可走通的 requires 鏈（相鄰兩點在圖上真的有邊）──\n")
            print(f"    {chain[0]['source']}")
            for e in chain:
                print(f"      ──requires({e['weight']})──▶ {e['target']}")

        others = {k: len(v) for k, v in paths.items() if k != pid}
        print(f"\n  另外 {len(others)} 條路徑：{sum(others.values())} 條邊"
              f"（合計 provenance {len(prov)} 條）")

    if comp:
        print("\n  macro 組合邊（Φ-iii 收縮，relation=composes_into）：")
        for e in comp:
            print(f"     {e['source'][:40]:40s} ──composes_into──▶ {e['target'][:46]}")


def show_numbers():
    hr("④ 數字：這跟把檔案存成 md 有什麼差別")
    d = pgi.parse_graph_index(str(GI))
    nodes, edges = d["nodes"], d["edges"]
    names = {n["name"] for n in nodes}
    touched = {e["source"] for e in edges} | {e["target"] for e in edges}
    iso = names - touched
    # 四類互斥、順序即優先級 —— 跟 sies_doctor 同一套判準，兩邊數字必須對得上
    boot, comp, prov, learned_e = [], [], [], []
    for e in edges:
        if e["source"] in BOOT and e["target"] in BOOT:
            boot.append(e)
        elif e.get("relation") == "composes_into":
            comp.append(e)
        elif _is_prov(e):
            prov.append(e)
        else:
            learned_e.append(e)
    learned = len(learned_e)
    macros = [n for n in names if str(n).startswith("macro-")]
    mconn = [m for m in macros if m in touched]

    print(f"\n  節點 .................. {len(nodes)}")
    print(f"  邊 .................... {len(edges)}")
    print(f"      bootstrap 手寫種子 .. {len(boot)}")
    print(f"      composes_into ....... {len(comp)}   (Φ-iii 機械產生 == 2×收縮次數)")
    print(f"      provenance .......... {len(prov)}   (課程路徑落地)")
    print(f"      統計/語意學習來的 ... {learned}")
    print(f"  孤島 .................. {len(iso)} / {len(nodes)}  ({len(iso)/max(len(nodes),1):.1%})")
    print(f"  macro ................. {len(macros)}，連回 parent 的 {len(mconn)}")
    tiers = {t: len([n for n in nodes if n.get("tier") == t])
             for t in ("active", "cold", "archive")}
    print(f"  tier .................. {tiers}")


def show_growth(run_id):
    hr("⑤ 成長曲線：三條主張各自的數字")
    cdir = ROOT / "data" / "w16" / "runs" / run_id / "checkpoints"
    cks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cdir.glob("*.json"))]
    if cks:
        a0 = cks[0]["graph_before_phi"]          # t=0：長跑第 1 題前
        a1 = cks[-1]["graph_after_phi"]
        ins = [(c["checkpoint"], (c.get("phi") or {}).get("inserted", 0)) for c in cks]

        print("\n  ① 節點成長趨緩 —— Φ 每個 checkpoint 插入的技能數")
        print("       " + "  ".join(f"ck{k}:{v}" for k, v in ins)
              + f"   （{a0['nodes']} → {a1['nodes']} 個節點）")
        print("\n  ② 邊持續上升 —— 但要看來源")
        print(f"       總邊數      {a0['edges']:>4} → {a1['edges']:<4}")
        print(f"       provenance  {a0.get('provenance',0):>4} → {a1.get('provenance',0):<4}"
              "   ← 課程路徑機械落地")
        mech = a1.get("bootstrap", 0) + a1.get("composes_into", 0) + a1.get("provenance", 0)
        print(f"       統計/語意學來的 {a1['edges'] - mech:>2}"
              "      ← 這場是 0，講法 B 尚未成立")
        print("\n  ③ 孤島率下降")
        print(f"       {a0['isolate_ratio']:.1%} → {a1['isolate_ratio']:.1%}"
              f"   （孤島 {a0['isolates']} → {a1['isolates']} / {a1['nodes']} 個節點）")

    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "plot_growth.py"),
                        "--run", run_id], capture_output=True, text=True)
    print("\n  PNG:")
    print(r.stdout or r.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--direction",
                    default="learn to build a data processing pipeline: "
                            "parse, validate, aggregate, join, report")
    ap.add_argument("--domain", default="pipeline")
    ap.add_argument("--graph-only", action="store_true", help="不出題，秒級（彩排用）")
    ap.add_argument("--dry", action="store_true", help="出題但不在沙箱推導 expected")
    ap.add_argument("--run", help="用這個 run_id 的長跑資料畫成長曲線")
    args = ap.parse_args()

    print("\n" + "─" * 68)
    print("  SIES —— 不改模型參數，靠技能的累積 / 合併 / 修剪 / 分層而成長")
    print("─" * 68)

    if not args.graph_only:
        show_path(args.direction, args.domain, args.dry)
        hr("② 執行")
        print("\n  （長跑是獨立步驟，實測 86-145 秒/題）")
        print("     python scripts/w16_preflight.py")
        print("     nohup python scripts/w16_run.py --tasks 50 \\")
        print(f"         --direction \"{args.direction}\" \\")
        print("         > data/logs/longrun_$(date +%Y%m%dT%H%M%S).log 2>&1 & disown")

    show_chain()
    show_numbers()
    if args.run:
        show_growth(args.run)
    else:
        runs = sorted((ROOT / "data" / "w16" / "runs").glob("*"))
        if runs:
            print(f"\n  （有長跑資料可畫圖：--run {runs[-1].name}）")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
