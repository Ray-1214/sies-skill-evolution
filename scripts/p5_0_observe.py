"""
p5_0_observe.py — P5-0 步驟 ⑧：新生候選技能的餘弦觀察
=======================================================
回答一個具體問題：**新領域跑起來，會不會在 active 層生出同義碎片？**

背景（§2.2.1）：實測顯示全庫 4005 對裡相似度最高的 0.9686 那對，兩端都在
active；而新技能一律 `tier="active"` 進場（evolution_operator.py:308-317）+
`frequency==0` grace period，所以新碎片會堆在 3D 圖的正中央，P4 的視圖過濾
（過濾 tier）藏不掉。

這支腳本量兩組數字：
  (a) 用**現行的（壞掉的）** embedding —— 只編碼 name | description，因為
      embedding_engine.py:162 找的 "Execution Policy" 標題 A3 從不寫。
      這是 θdup **今天實際看到的**東西。
  (b) 用**修好的** embedding —— name | description | 執行策略（alias-aware）。
      這是 P2-1 之後 θdup 會看到的東西。

(a) 低而 (b) 高 = P2-1/P2-2 那 1 天有實據，值得放進地基。
兩者都低 = 這批新技能真的不重複，去重下限可以再議。

唯讀：只讀 skills/candidates/ 與 LanceDB，不寫任何檔、不動圖。

用法:
    python scripts/p5_0_observe.py
"""

import itertools
import re
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CAND_DIR = ROOT / "skills" / "candidates"
# 跟 evolution_operator._SECTION_ALIASES 同一組（P2-1 要抽成共用常數）
STRATEGY_ALIASES = ("Execution Policy", "Strategy Steps", "執行策略")


def parse_skill_md(p: Path):
    text = p.read_text(encoding="utf-8")
    fm = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            text = parts[2]
    return fm, text


def extract_section(body: str, aliases):
    """alias-aware 的段落抽取 —— 這正是 P2-1 要修的行為。"""
    for a in aliases:
        m = re.search(rf"^#+\s*{re.escape(a)}.*?$(.*?)(?=^#+\s|\Z)",
                      body, re.M | re.S)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def main():
    cands = sorted(CAND_DIR.glob("*/SKILL.md"))
    if not cands:
        print("skills/candidates/ 是空的 —— 這一輪 A3 沒抽出任何候選技能。")
        print("（這本身是一個結果：新領域沒有生出新節點，也就沒有新碎片。）")
        return 0

    print(f"=== 這一輪新生的候選技能：{len(cands)} 個 ===\n")
    names, cur_texts, fix_texts = [], [], []
    for p in cands:
        fm, body = parse_skill_md(p)
        name = fm.get("name") or p.parent.name
        desc = fm.get("description", "")
        strat = extract_section(body, STRATEGY_ALIASES)
        names.append(name)
        # (a) 現行：embedding_engine.py:162-171 找不到 "Execution Policy" → 只剩兩段
        cur_texts.append(f"{name} | {desc}")
        # (b) 修好：alias-aware 抓到策略段
        fix_texts.append(f"{name} | {desc}" + (f" | {strat[:200]}" if strat else ""))
        print(f"  {name}")
        print(f"      desc   : {desc[:96]}")
        print(f"      策略段 : {'有 ' + str(len(strat)) + ' 字' if strat else '✗ 抓不到'}")
    print()

    from embedding_engine import EmbeddingEngine
    eng = EmbeddingEngine()

    def cos_matrix(texts):
        V = np.array([eng.embed_text(t) for t in texts], dtype=float)
        V = V / np.linalg.norm(V, axis=1, keepdims=True)
        return V @ V.T, V

    print("載入 embedding 模型（nemotron-8b on CPU，會慢）…")
    Sa, Va = cos_matrix(cur_texts)
    Sb, Vb = cos_matrix(fix_texts)

    def report(S, label):
        n = len(names)
        if n < 2:
            print(f"\n--- {label} --- 只有 1 個候選，無法配對")
            return []
        pairs = sorted(((float(S[i, j]), names[i], names[j])
                        for i, j in itertools.combinations(range(n), 2)),
                       reverse=True)
        ge80 = sum(1 for c, _, _ in pairs if c >= 0.80)
        print(f"\n--- {label} ---")
        print(f"  {n} 個候選 / {len(pairs)} 對；cos ≥ 0.80: {ge80}")
        for c, a, b in pairs[:5]:
            mark = "  ← θdup 會擋" if c >= 0.80 else ""
            print(f"    {c:.4f}  {a[:34]:34s} | {b[:34]}{mark}")
        return pairs

    pa = report(Sa, "(a) 現行 embedding：只有 name | description（θdup 今天看到的）")
    pb = report(Sb, "(b) 修好 embedding：name | description | 執行策略（P2-1 之後）")

    # 新生 vs 既有 90 個
    print("\n--- 新生候選 vs 既有圖上的 90 個技能（用現行 embedding）---")
    try:
        import lancedb
        db = lancedb.connect(str(ROOT / "data" / "lancedb"))
        df = db.open_table("skill_embeddings").to_pandas()
        E = np.stack(df["vector"].to_numpy()).astype(float)
        E = E / np.linalg.norm(E, axis=1, keepdims=True)
        enames = df["name"].tolist()
        X = Va @ E.T
        for i, nm in enumerate(names):
            j = int(np.argmax(X[i]))
            c = float(X[i, j])
            mark = "  ← 會被判重複" if c > 0.80 else ""
            print(f"    {nm[:36]:36s} 最近鄰 {enames[j][:30]:30s} {c:.4f}{mark}")
    except Exception as e:  # noqa: BLE001
        print(f"    unavailable: {type(e).__name__}: {e}")

    # 判讀
    print("\n" + "=" * 68)
    print("判讀（§2.2.1 的 P2-1/P2-2 去重下限要不要坐實）")
    print("=" * 68)
    ma = max((c for c, _, _ in pa), default=0.0)
    mb = max((c for c, _, _ in pb), default=0.0)
    print(f"  新生候選之間的最高餘弦：現行 {ma:.4f}  →  修好後 {mb:.4f}")
    if mb - ma > 0.08 and mb >= 0.75:
        print("  → 修好 embedding 後相似度明顯上升且逼近門檻：**P2-1/P2-2 有實據，坐實 1 天**")
    elif ma >= 0.80:
        print("  → 現行 embedding 就已經抓得到：θdup 本來就會擋，但公式錯誤仍要修（P2-2）")
    elif mb < 0.60:
        print("  → 兩種算法下這批技能都不相似：這一輪沒有生出碎片。")
        print("     ⚠️ 但這不推翻 §2.2.1 —— 既有 active 層那對 0.9686 依然在畫面正中央。")
    else:
        print("  → 訊號不明確，樣本太小（9 題）。以既有 active 層的實測為準。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
