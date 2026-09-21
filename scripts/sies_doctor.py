"""
sies_doctor.py — SIES 現況體檢（唯讀，不改任何狀態）
=====================================================
一條指令印出「系統到底長成什麼樣」的所有關鍵數據，供動手前後對比。

    python scripts/sies_doctor.py            # 全部
    python scripts/sies_doctor.py --json     # 機器可讀（存 baseline 用）

七個區塊：
  1. 三方一致性   FS / GRAPH_INDEX / LanceDB 節點數是否相等
  2. 圖結構       nodes / edges / 孤立點 / macro / tier 分佈
  3. 執行紀錄     run_summary 筆數、cluster tag、success 分佈、steps
  4. 技能冗餘     近重複技能族（node 膨脹的真正來源）
  5. 共現與 Φ-iii 為什麼收縮算子不觸發（support/lift 對閾值的實際位置）
  6. 課程狀態     每 cluster 目前 level
  7. 判讀         紅旗清單

唯讀保證：只 open(...) 讀檔，不寫入、不呼叫 LLM、不動 LanceDB。
"""

import argparse
import collections
import functools
import json
import math
import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
GRAPH_INDEX = SKILLS / "GRAPH_INDEX.md"
RUN_SUMMARY = ROOT / "memory" / "episodic" / "run_summary.jsonl"
CURRICULUM_STATE = ROOT / "data" / "curriculum_state.json"
PROFILE = ROOT / "data" / "ability_profile_live.json"

TIERS = ("active", "cold", "archive")

# Φ-iii 實際生效的閾值（graph_contractor.py: delta from config, min_lift 硬編）
MIN_SUPPORT = 0.3
MIN_LIFT = 1.5

# 近重複族偵測用的「意義相同」詞根
DUP_MARKERS = (
    "implementation", "test", "testing", "verification", "validation",
    "suite", "harness", "driven", "verify",
)


# 當 --json 時，人看的報告全部走 stderr，stdout 只留純 JSON
_report = print


def _hr(title):
    _report(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _load_jsonl(path):
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


def _parse_graph_index():
    """從 GRAPH_INDEX.md 抽 meta / nodes / edges（純文字解析，不 import 專案模組）。"""
    if not GRAPH_INDEX.exists():
        return {}, [], []
    import yaml
    text = GRAPH_INDEX.read_text(encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    meta, nodes, edges = {}, [], []
    for b in blocks:
        try:
            d = yaml.safe_load(b)
        except yaml.YAMLError:
            continue
        if not isinstance(d, dict):
            continue
        if "nodes" in d:
            nodes = d["nodes"] or []
        elif "edges" in d:
            edges = d["edges"] or []
        else:
            meta.update(d)
    return meta, nodes, edges


def _lancedb_rows():
    """
    數 config 指定的 LanceDB 表列數。

    另外掃全 repo 找所有 *.lance 目錄 —— config.yaml 的 vector_store.path 是相對路徑
    ("./data/lancedb")，從不同 cwd 啟動會建立/查詢到不同的庫。已知磁碟上存在兩個
    分歧的庫，這個掃描讓分裂可見（UD-4c）。
    """
    primary = None
    try:
        import lancedb
        db = lancedb.connect(str(ROOT / "data" / "lancedb"))
        primary = db.open_table("skill_embeddings").count_rows()
    except Exception as e:  # noqa: BLE001 — 診斷工具，任何失敗都只降級
        primary = f"unavailable ({type(e).__name__})"

    stores = []
    for d in sorted(ROOT.glob("**/*.lance")):
        rel = d.relative_to(ROOT)
        # 跳過快照、.git，以及 table 內部的 data/*.lance 片段檔
        if "snapshots" in rel.parts or ".git" in rel.parts:
            continue
        if any(part.endswith(".lance") for part in rel.parts[:-1]):
            continue
        try:
            import lancedb
            conn = lancedb.connect(str(d.parent))
            n = conn.open_table(d.stem).count_rows()
        except Exception:  # noqa: BLE001
            n = "?"
        stores.append((str(rel), n))
    return primary, stores


# ── 1. 三方一致性 ────────────────────────────────────────────────

def section_consistency(nodes):
    _hr("1. 三方一致性（FS / GRAPH_INDEX / LanceDB）")
    # candidates/ 是還沒通過 Φ-ii 的候選，**不是圖節點** —— 數進去三方一致性
    # 會假性 MISMATCH（A3 一寫候選就爆）。實測 dry-run 就踩到。
    fs_files = sorted(p for p in SKILLS.glob("**/SKILL.md")
                      if p.relative_to(SKILLS).parts[0] in TIERS)
    fs_by_tier = collections.Counter(
        p.relative_to(SKILLS).parts[0] for p in fs_files
    )
    fs_n = len(fs_files)
    graph_n = len(nodes)
    lance_n, stores = _lancedb_rows()

    _report(f"  filesystem SKILL.md ... {fs_n}   {dict(fs_by_tier)}")
    _report(f"  GRAPH_INDEX nodes ..... {graph_n}")
    _report(f"  LanceDB rows .......... {lance_n}   (config 指定的庫)")

    ok = (fs_n == graph_n == lance_n)
    _report(f"  → {'PASS 三方相等' if ok else 'MISMATCH（三者應相等）'}")

    _report(f"\n  磁碟上所有 .lance 庫（vector_store.path 是相對路徑，cwd 不同會分裂）:")
    for path, n in stores:
        mark = "  ← config 指的這個" if path.startswith("data/lancedb/skill") else ""
        _report(f"      {n!s:>6} rows  {path}{mark}")
    if len(stores) > 1:
        _report(f"  ⚠ 找到 {len(stores)} 個庫。三方一致性只量到其中一個，"
                f"分歧的庫看不見（UD-4c）。")

    fs_names = {p.parent.name for p in fs_files}
    graph_names = {n.get("name") for n in nodes}
    only_fs = fs_names - graph_names
    only_graph = graph_names - fs_names
    if only_fs:
        _report(f"  只在 FS（圖上沒有）: {sorted(only_fs)[:8]}")
    if only_graph:
        _report(f"  只在圖（檔案不見）: {sorted(only_graph)[:8]}")
    return {"fs": fs_n, "graph": graph_n, "lance": lance_n, "consistent": ok,
            "lance_stores": stores, "split_brain": len(stores) > 1}


# ── 2. 圖結構 ────────────────────────────────────────────────────

def section_graph(meta, nodes, edges):
    _hr("2. 圖結構（連通度 = 專案最高風險項）")
    names = {n.get("name") for n in nodes}
    touched = set()
    for e in edges:
        touched.add(e.get("source"))
        touched.add(e.get("target"))
    isolates = names - touched
    macros = sorted(n for n in names if str(n).startswith("macro-"))
    macro_touched = [m for m in macros if m in touched]

    tier_dist = collections.Counter(n.get("tier") for n in nodes)
    n_nodes, n_edges = len(names), len(edges)
    density = n_edges / (n_nodes * (n_nodes - 1)) if n_nodes > 1 else 0

    _report(f"  nodes ................. {n_nodes}")
    _report(f"  edges ................. {n_edges}")
    _report(f"  孤立節點 .............. {len(isolates)}  ({len(isolates)/n_nodes:.1%} of nodes)")
    _report(f"  有邊節點 .............. {len(touched & names)}")
    _report(f"  density ............... {density:.5f}")
    _report(f"  tier .................. {dict(tier_dist)}")
    _report(f"  macro 技能 ............ {len(macros)}，其中有連回 parent 的: {len(macro_touched)}")
    for m in macros:
        _report(f"      - {m}  [edges={'yes' if m in touched else 'NO — 孤島'}]")
    _report(f"  last_updated .......... {meta.get('last_updated')}")

    _report("\n  現有的邊（全部）:")
    for e in edges:
        _report(f"      {e.get('source')} --{e.get('relation')}({e.get('weight')})--> {e.get('target')}")
    seeded = {"web-search", "data-analysis", "text-summary", "code-execution", "file-io"}
    # 邊要分三類報，否則「learned = 總數 − 6」會把機械產生的邊算成學習成果
    by_rel = collections.Counter(e.get("relation") for e in edges)
    # 互斥的單趟分類，順序即優先級。provenance 同時看 relation 和 provenance 屬性：
    # 只認 provenance=="curriculum_path" 的話，一旦序列化把屬性掉了（parse_graph_index
    # 的白名單就幹過這件事），206 條機械邊會整批掉進「學習來的」而變成假的成果。
    # learned 只能由明確列入允許清單的 provenance 值產生。
    # 目前該清單是空的 —— 誠實牆上「學習來的邊 = 0」因此是結構保證，
    # 不是碰巧正確。新增任何一類邊時，必須明確決定它屬於哪一格。
    LEARNED_PROVENANCE: frozenset = frozenset()
    bootstrap, composes, provenance, learned_edges, unclassified = [], [], [], [], []
    for e in edges:
        rel = e.get("relation")
        if e.get("source") in seeded and e.get("target") in seeded:
            bootstrap.append(e)
        elif rel == "composes_into":
            composes.append(e)
        elif rel in ("follows", "requires") or e.get("provenance") == "curriculum_path":
            provenance.append(e)
        elif e.get("provenance") in LEARNED_PROVENANCE:
            learned_edges.append(e)
        else:
            # 原本這裡是 else → learned_edges，任何不認得的邊都會被算成學習成果。
            unclassified.append(e)
    _report(f"\n  邊的來源分類（relation: {dict(by_rel)}）:")
    _report(f"      bootstrap 手寫種子 .......... {len(bootstrap)}")
    _report(f"      composes_into（Φ-iii 機械產生，== 2×收縮次數，"
            f"是工程不變式不是學習成果）... {len(composes)}")
    _report(f"      provenance（課程路徑落地）... {len(provenance)}")
    _report(f"      **統計/語意學習來的** ....... {len(learned_edges)}")
    _report(f"      未分類（provenance 不在任何清單上）... {len(unclassified)}")
    if unclassified:
        _report("      ⚠️ 未分類 ≠ 學習成果。有新來源的邊進了圖卻沒人決定它算哪一類：")
        for e in unclassified[:5]:
            _report(f"         {e.get('source')} --{e.get('relation')}--> {e.get('target')}"
                    f"  provenance={e.get('provenance')!r}")
    return {"nodes": n_nodes, "edges": n_edges, "isolates": len(isolates),
            "macros": len(macros), "macros_connected": len(macro_touched),
            "learned_edges": len(learned_edges),
            "unclassified_edges": len(unclassified),
            "bootstrap_edges": len(bootstrap), "composes_into_edges": len(composes),
            "provenance_edges": len(provenance),
            "relations": dict(by_rel), "tiers": dict(tier_dist)}


# ── 3. 執行紀錄 ──────────────────────────────────────────────────

def section_runs(recs):
    _hr("3. 執行紀錄 run_summary.jsonl")
    n = len(recs)
    clusters = collections.Counter(r.get("cluster") for r in recs)
    succ = collections.Counter(r.get("success") for r in recs)
    # ── schema 世代（P1-a 落地當下必然是混合狀態）──
    # 舊版全域 OR 的寫法：只要有一筆新紀錄就當成「全部都是新的」，
    # 覆蓋率分母用 n（含舊紀錄），數字會被稀釋得看不出真相。
    # 改成逐筆判斷世代，覆蓋率只以新 schema 的紀錄為分母。
    new_recs = [r for r in recs if "execution_completed" in r]
    old_recs = [r for r in recs if "execution_completed" not in r]
    n_new, n_old = len(new_recs), len(old_recs)
    layers = {
        k: collections.Counter(r.get(k) for r in new_recs)
        for k in ("pipeline_success", "execution_completed",
                  "verified_success", "verification_status")
    }
    has_layers = n_new > 0
    mixed = n_new > 0 and n_old > 0
    steps = [r.get("total_steps", 0) for r in recs]
    _report(f"  records ............... {n}")
    _report(f"  cluster tag ........... {dict(clusters)}")
    _report(f"  success 欄位分佈 ...... {dict(succ)}")
    if n:
        rate = succ.get(True, 0) / n
        _report(f"  success rate .......... {rate:.1%}")
        _report(f"  steps avg/median/max .. {sum(steps)/n:.2f} / "
              f"{sorted(steps)[n//2]} / {max(steps)}")
        _report(f"  steps==0 的筆數 ....... {sum(1 for s in steps if s == 0)}")
    _report(f"  欄位 .................. {sorted(recs[-1].keys()) if recs else '—'}")

    _report(f"  schema 世代 ........... 新 {n_new} 筆 / 舊 {n_old} 筆"
            + ("   ⚠ 混合狀態" if mixed else ""))

    if has_layers:
        _report("\n  三層 success（P1-a，只統計新 schema 的 "
                f"{n_new} 筆）:")
        for k in ("pipeline_success", "execution_completed", "verified_success",
                  "verification_status"):
            _report(f"    {k:22s} {dict(layers[k])}")
        vs = layers["verified_success"]
        n_ver = vs.get(True, 0) + vs.get(False, 0)
        cov = n_ver / n_new if n_new else 0
        _report(f"    verified 覆蓋率 ....... {cov:.0%}"
                f"（{n_ver}/{n_new} 筆新 schema 有獨立驗證結果）")
        if n_ver:
            _report(f"    verified accuracy ..... {vs.get(True,0)/n_ver:.1%}"
                    f"  ← 只有這個能叫正確率")
        if mixed:
            _report(f"    ⚠ 另有 {n_old} 筆舊 schema 紀錄不在上面的統計裡。"
                    f"它們沒有 verified_success 欄位，")
            _report(f"      在 utility 計算裡被當成「r 未知」而非 r=0（B′，見 §9.1）。")
    elif n and succ.get(True, 0) == n:
        _report("\n  ⚠ 只有單一 success 欄且全為 True。這不是 accuracy，"
                "是 SimpleAgent 自報 finish（simple_agent.py:387）。")
        _report("    後果：frontier_signal 永遠 too_easy → curriculum level 單調 +1 無上限。")

    vs = layers["verified_success"]
    n_ver = vs.get(True, 0) + vs.get(False, 0)
    return {"records": n, "clusters": dict(clusters),
            "success_rate": (succ.get(True, 0) / n) if n else None,
            "schema_new": n_new, "schema_old": n_old, "schema_mixed": mixed,
            "has_three_layers": has_layers,
            "verified_coverage": (n_ver / n_new) if n_new else 0.0,
            "verified_accuracy": (vs.get(True, 0) / n_ver) if n_ver else None,
            "layers": {k: dict(v) for k, v in layers.items()} if has_layers else None}


# ── 4. 技能冗餘 ──────────────────────────────────────────────────

def _true_cosine_pairs():
    """
    對 LanceDB 裡的向量算真餘弦（不是 skill_validator 那條算錯的公式）。

    ⚠️ 目前的向量只編碼 name|description（embedding_engine.py:162-171 找的
    "Execution Policy" 標題 A3 從來不寫），所以這個數字量到的是「一句摘要有多像」，
    不是「行為有多像」。修好索引前不要拿它當語意重複的真值。
    """
    try:
        import lancedb
        import numpy as np
        db = lancedb.connect(str(ROOT / "data" / "lancedb"))
        df = db.open_table("skill_embeddings").to_pandas()
        V = np.stack(df["vector"].to_numpy())
        V = V / np.linalg.norm(V, axis=1, keepdims=True)
        S = V @ V.T
        n = len(df)
        iu = np.triu_indices(n, k=1)
        sims = S[iu]
        names = df["name"].tolist()
        top = sorted(
            ((float(S[i, j]), names[i], names[j]) for i, j in zip(*iu)),
            reverse=True,
        )[:5]
        # [P2-1] 聚類才是量同義族的正確方法 —— 單一配對門檻抓不到傳遞性重複
        # （A~B、B~C 但 A≁C），而且我自己手工標註族群時標錯過。
        clusters = []
        try:
            from sklearn.cluster import AgglomerativeClustering
            D = np.clip(1.0 - S, 0, None); np.fill_diagonal(D, 0)
            lab = AgglomerativeClustering(n_clusters=None, distance_threshold=0.25,
                                          metric="precomputed",
                                          linkage="average").fit_predict(D)
            for c in set(lab):
                members = sorted(np.array(names)[lab == c].tolist())
                if len(members) > 1:
                    clusters.append(members)
            clusters.sort(key=len, reverse=True)
        except Exception:  # noqa: BLE001 — sklearn 沒裝就降級，不讓體檢掛掉
            clusters = None

        return {
            "n_vectors": n,
            "n_pairs": int(len(sims)),
            "clusters_cos075": clusters,
            "ge_080": int((sims >= 0.80).sum()),
            "ge_085": int((sims >= 0.85).sum()),
            "ge_090": int((sims >= 0.90).sum()),
            "top5": top,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def section_redundancy(nodes):
    _hr("4. 技能冗餘")
    names = [str(n.get("name")) for n in nodes]
    dupish = [n for n in names if any(m in n for m in DUP_MARKERS)]
    _report(f"  [啟發式・非語意判定] 名稱含 {'/'.join(DUP_MARKERS[:5])}… 詞根的技能: "
            f"{len(dupish)} / {len(names)}  ({len(dupish)/len(names):.0%})")
    _report(f"  ⚠ 這是對「技能名稱」做字串比對（DUP_MARKERS），不是語意相似度。")
    _report(f"    命中的裡面有真的不同的技能（例如 synthetic-data-generation-for-testing、")
    _report(f"    exponentiation-by-squaring-implementation）。只當名稱衛生指標看，別當重複率。")

    # 以「去掉修飾詞後的骨幹」分群，看同義族有多大
    def stem(nm):
        toks = [t for t in nm.split("-") if t not in DUP_MARKERS and t not in
                ("with", "and", "for", "the", "of", "a", "macro")]
        return "-".join(sorted(toks)) or "(pure-test-skill)"

    fam = collections.Counter(stem(n) for n in dupish)
    _report("\n  最大的近重複族（骨幹去修飾後同名 = 語意幾乎相同）:")
    for k, v in fam.most_common(6):
        if v < 2:
            continue
        members = sorted(n for n in dupish if stem(n) == k)
        _report(f"      [{v} 個] {k}")
        for m in members:
            _report(f"          {m}")
    biggest = max(fam.values()) if fam else 0

    tc = _true_cosine_pairs()
    _report(f"\n  [實測] LanceDB 向量的真餘弦分布:")
    if "error" in tc:
        _report(f"      unavailable — {tc['error']}")
    else:
        _report(f"      {tc['n_vectors']} 個向量 / {tc['n_pairs']} 對")
        _report(f"      cos ≥ 0.90: {tc['ge_090']:4d}    "
                f"≥ 0.85: {tc['ge_085']:4d}    ≥ 0.80: {tc['ge_080']:4d}")
        _report(f"      最相似的 5 對:")
        for c, a, b in tc["top5"]:
            _report(f"        {c:.4f}  {a[:38]} | {b[:38]}")
        cl = tc.get("clusters_cos075")
        if cl is None:
            _report("  （sklearn 不可用，跳過聚類）")
        else:
            _report(f"\n      同義族（agglomerative, cosine, average, cutoff cos≥0.75）: "
                    f"{len(cl)} 群 / 涵蓋 {sum(len(g) for g in cl)} 個技能")
            for g in cl[:4]:
                _report(f"        [{len(g)}] {', '.join(x[:34] for x in g[:4])}"
                        + (" …" if len(g) > 4 else ""))

    return {"dupish_name_heuristic": len(dupish), "total": len(names),
            "largest_name_family": biggest, "true_cosine": tc}


# ── 5. 共現與 Φ-iii ──────────────────────────────────────────────

def section_cooccurrence(recs):
    _hr("5. 共現分析：Φ-iii（收縮/打包）為什麼不觸發")
    traces = [set(r.get("skills_used") or []) for r in recs]
    traces = [t for t in traces if t]
    n = len(traces)
    if n == 0:
        _report("  無 trace")
        return {}
    sc = collections.Counter()
    for t in traces:
        sc.update(t)
    pc = collections.Counter()
    for t in traces:
        for a, b in combinations(sorted(t), 2):
            pc[(a, b)] += 1

    rows = []
    for (a, b), c in pc.items():
        sup = c / n
        lift = sup / ((sc[a] / n) * (sc[b] / n))
        rows.append((sup, lift, c, a, b))
    rows.sort(reverse=True)

    passed = [r for r in rows if r[0] >= MIN_SUPPORT and r[1] > MIN_LIFT]
    sup_ok = sum(1 for r in rows if r[0] >= MIN_SUPPORT)
    lift_ok = sum(1 for r in rows if r[1] > MIN_LIFT)

    _report(f"  traces={n}  distinct skills={len(sc)}  distinct pairs={len(rows)}")
    _report(f"  閾值：support ≥ {MIN_SUPPORT}  AND  lift > {MIN_LIFT}")
    _report(f"    通過 support 的 pair ... {sup_ok}")
    _report(f"    通過 lift 的 pair ...... {lift_ok}")
    _report(f"    兩者都通過 ............. {len(passed)}   ← Φ-iii 的候選數")
    _report(f"\n  support 前 8 名（看它們卡在哪一關）:")
    _report(f"      {'support':>8} {'lift':>6} {'cnt':>4}  pair")
    for sup, lift, c, a, b in rows[:8]:
        flag = "PASS" if (sup >= MIN_SUPPORT and lift > MIN_LIFT) else \
               ("lift↓" if sup >= MIN_SUPPORT else "sup↓")
        _report(f"      {sup:8.3f} {lift:6.2f} {c:4d}  [{flag}] {a[:32]} | {b[:32]}")

    def _need(nn):
        # 門檻是 cnt/nn >= MIN_SUPPORT，取最小整數 cnt
        k = math.ceil(MIN_SUPPORT * nn)
        return k if k / nn >= MIN_SUPPORT else k + 1

    _report(f"\n  ⚠ support 對全部歷史計算（非滑動窗）：現在 n={n}，一對技能要共現 "
            f"≥ {_need(n)} 次才過關。")
    _report(f"    跑到 n=174 就要 ≥ {_need(174)} 次。→ 門檻隨歷史變長而變難，新領域訊號永遠被舊資料稀釋。")
    return {"traces": n, "pairs": len(rows), "passing": len(passed),
            "support_only": sup_ok, "lift_only": lift_ok}


# ── 6. 課程狀態 ──────────────────────────────────────────────────

def section_curriculum():
    _hr("6. 課程狀態")
    if CURRICULUM_STATE.exists():
        st = json.loads(CURRICULUM_STATE.read_text(encoding="utf-8"))
        _report(f"  curriculum_state.json: "
              f"{ {k: v.get('level') for k, v in st.items()} }")
    else:
        _report(f"  curriculum_state.json 不存在（尚未跑過 curriculum 出題）")
        st = {}
    if PROFILE.exists():
        pr = json.loads(PROFILE.read_text(encoding="utf-8"))
        _report(f"  ability_profile_live.json last_updated: {pr.get('last_updated')}")
        _report(f"  frontier_signal: {pr.get('frontier_signal')}")
        pc = pr.get("per_cluster", {})
        _report(f"  per_cluster success_rate: "
              f"{ {k: v.get('success_rate') for k, v in pc.items()} }")
    else:
        _report("  ability_profile_live.json 不存在")
        pr = {}
    return {"levels": {k: v.get("level") for k, v in st.items()},
            "frontier": pr.get("frontier_signal")}


# ── 7. 判讀 ──────────────────────────────────────────────────────

def section_verdict(c, g, r, d, co):
    _hr("7. 紅旗")
    flags = []
    if not c["consistent"]:
        flags.append("三方不一致 — 圖/檔案/向量庫節點數不等，任何實驗數據都不可信")
    if g["learned_edges"] == 0:
        # 舊措辭寫死成「全是 bootstrap 種子」，在 provenance 邊落地後直接是假的：
        # 216 條裡只有 6 條是種子。紅旗要報真實的組成，否則自己在騙自己。
        flags.append(
            f"沒有任何一條統計/語意學習來的邊（{g['edges']} 條 = "
            f"bootstrap {g['bootstrap_edges']} + composes_into {g['composes_into_edges']}"
            f" + provenance {g['provenance_edges']}，全是機械產生）")
    if g["isolates"] / max(g["nodes"], 1) > 0.5:
        flags.append(f"{g['isolates']}/{g['nodes']} 節點是孤島（{g['isolates']/g['nodes']:.0%}）")
    if g["macros"] and g["macros_connected"] == 0:
        flags.append(f"{g['macros']} 個 macro 全部沒連回 parent — 打包後仍是孤島")
    if not r.get("has_three_layers") and r.get("success_rate") == 1.0:
        flags.append("只有單層 success 且 100% → frontier 永遠 too_easy → level 單調上升失控")
    if c.get("split_brain"):
        flags.append(f"磁碟上有 {len(c['lance_stores'])} 個 .lance 庫，"
                     f"三方一致性只量到其中一個")
    tc = d.get("true_cosine") or {}
    if tc.get("ge_080"):
        flags.append(f"向量上有 {tc['ge_080']} 對 cos ≥ 0.80（{tc.get('ge_085',0)} 對 ≥ 0.85）"
                     f"— 但索引只含 name|description，真正的重複規模未知")
    if d["largest_name_family"] >= 3:
        flags.append(f"名稱啟發式：最大同名骨幹族 {d['largest_name_family']} 個 — "
                     f"{d['dupish_name_heuristic']}/{d['total']} 技能名含測試/實作詞根"
                     f"（字串比對，非語意判定）")
    if co.get("passing") == 0:
        flags.append("Φ-iii 候選 = 0 — 收縮算子從沒有東西可打包")
    for i, f in enumerate(flags, 1):
        _report(f"  {i}. {f}")
    if not flags:
        _report("  （無）")
    return flags


def main():
    global _report
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="stdout 只輸出純 JSON（人看的報告改走 stderr），存 baseline 用")
    args = ap.parse_args()

    # --json 時 stdout 必須是 valid JSON，人看的報告全部改走 stderr
    if args.json:
        _report = functools.partial(print, file=sys.stderr)

    meta, nodes, edges = _parse_graph_index()
    recs = _load_jsonl(RUN_SUMMARY)

    _report(f"SIES doctor — repo: {ROOT}")
    c = section_consistency(nodes)
    g = section_graph(meta, nodes, edges)
    r = section_runs(recs)
    d = section_redundancy(nodes)
    co = section_cooccurrence(recs)
    cu = section_curriculum()
    flags = section_verdict(c, g, r, d, co)

    if args.json:
        payload = {"consistency": c, "graph": g, "runs": r, "redundancy": d,
                   "cooccurrence": co, "curriculum": cu, "flags": flags}
        # cluster=None 等 non-str key 會讓 sort_keys 炸掉，先正規化成字串
        def _norm(o):
            if isinstance(o, dict):
                return {("null" if k is None else str(k)): _norm(v)
                        for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [_norm(x) for x in o]
            return o
        # stdout：只有這一段，且 sort_keys 讓兩次輸出可以直接 diff
        print(json.dumps(_norm(payload), ensure_ascii=False,
                         indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
