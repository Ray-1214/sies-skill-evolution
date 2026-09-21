"""
plot_growth.py — 「節點成長趨緩、邊持續上升、孤島率下降」的圖（取代前端）
==========================================================================
這是回答教授那句「這跟你把檔案存成 md 有什麼差別」的東西。

從一次長跑的 checkpoints/*.json 畫三張子圖：
  1. 節點變化拆成 stacked bar（inserted / merged-away / pruned）——**不是單一淨線**。
     淨線會把「系統自己壓縮」跟「什麼都沒發生」畫成一樣。
  2. 邊數依來源堆疊（bootstrap / composes_into / provenance / 統計語意學習）——
     composes_into 是 Φ-iii 機械產生的（== 2×收縮次數），把它算成學習成果會灌水。
  3. 孤島率曲線。

⚠️ 時間軸原點：P2 的一次性去重整併是 **t<0 的資料遷移**，不是系統學來的。
   曲線一律從「整併後、長跑第 1 題前」的那個 checkpoint(000) 開始，圖上用垂直
   虛線標出 manual consolidation 的位置。

    python scripts/plot_growth.py --run <run_id>
    python scripts/plot_growth.py --run <run_id> --out data/w16/figures/growth.png
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "data" / "w16" / "runs"


def load(run_id):
    d = RUNS / run_id
    cks = sorted((d / "checkpoints").glob("*.json"))
    if not cks:
        sys.exit(f"{d}/checkpoints 是空的 —— 長跑還沒跑，或 run_id 錯了")
    return d, [json.loads(p.read_text(encoding="utf-8")) for p in cks]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()

    d, cks = load(args.run)
    out = Path(args.out) if args.out else d / "report" / "figures" / "01_growth.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    # t=0 = 長跑第 1 題前的狀態。checkpoint 檔每 10 題才寫一次、沒有 000，
    # 少了這個點，圖就從 ckpt10 起跳、看不到 edges 10→216 的起點。
    x = [0] + [c["checkpoint"] for c in cks]
    aft = [cks[0]["graph_before_phi"]] + [c["graph_after_phi"] for c in cks]
    nodes = [a["nodes"] for a in aft]
    iso = [a["isolate_ratio"] * 100 for a in aft]

    # 節點變化拆成三類（Φ 報告有 inserted；merged/pruned 從節點數差回推）
    ins, mrg = [0], [0]           # t=0 還沒跑過 Φ
    prev = cks[0]["graph_before_phi"]["nodes"]
    for c in cks:
        p = (c.get("phi") or {})
        i = p.get("inserted", 0)
        delta = c["graph_after_phi"]["nodes"] - prev
        ins.append(i)
        mrg.append(max(0, i - delta))     # 插進來卻沒讓總數增加的 = 被合併/剪掉
        prev = c["graph_after_phi"]["nodes"]

    # 配色 = dataviz 規範的 categorical slot 1-4（固定順序，不循環）。
    # 舊的 #54A24B/#F58518 在紅色盲下 ΔE 3.4 —— 而它們在堆疊圖裡正好相鄰，
    # 等於對色盲讀者是同一塊。validate_palette.js 對這組四色全 PASS。
    SURFACE = "#fcfcfb"
    INK, INK2 = "#1a1a19", "#5f5f5a"          # 文字一律用墨色，不用序列色
    S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"

    # 四張子圖，一張一個量。**不用雙 y 軸** —— 節點總數(90-110) 和 Φ 插入數(0-7)
    # 疊在同一軸上會把後者壓成看不見，而「成長趨緩」正是靠那組數字。
    fig, axes = plt.subplots(4, 1, figsize=(9, 13), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(alpha=.25, lw=.6)                      # 網格退到背景
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color("#d8d8d2")
        ax.tick_params(colors=INK2, labelsize=9)

    # ① 技能總數（單序列 → 不需要圖例，ylabel 就是它的名字）
    ax = axes[0]
    ax.plot(x, nodes, "-o", color=S1, lw=1.8, ms=5.5)
    for xi, v in zip(x, nodes):
        ax.annotate(str(v), (xi, v), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color=INK2)
    ax.axvline(0, ls="--", c="#c9c9c3", lw=1)
    # 圖內一律英文 —— matplotlib 預設字體沒有 CJK，中文會變豆腐格
    ax.annotate("t=0: post-consolidation baseline\n(manual dedup merge is a t<0 migration)",
                xy=(0, 0), xycoords=("data", "axes fraction"),
                xytext=(6, 6), textcoords="offset points",
                fontsize=8, color=INK2, va="bottom")
    ax.set_title(f"Skill graph growth — {args.run}", color=INK, fontsize=12, pad=14)
    ax.set_ylabel("total skills", color=INK2, fontsize=9)
    ax.margins(y=.22)

    # ② Φ 每個 checkpoint 插入幾個技能 —— 「成長趨緩」的主張就是這條
    ax = axes[1]
    ax.bar(x, ins, color=S1, width=3.2)
    ax.bar(x, [-m for m in mrg], color=S2, width=3.2)
    for xi, v in zip(x, ins):
        if v:
            ax.annotate(str(v), (xi, v), textcoords="offset points", xytext=(0, 4),
                        ha="center", fontsize=8, color=INK2)
    ax.set_ylabel("skills inserted by Φ\nper checkpoint", color=INK2, fontsize=9)
    ax.margins(y=.28)

    # ③ 邊依來源堆疊。四類必須分開畫，否則「learned = 總數 − 6」會把機械產生的
    #    邊算成學習成果。段之間留 surface 色的縫（規範要求的 2px gap）。
    ax = axes[2]
    keys = [("bootstrap", S1, "bootstrap seeds (hand-written)"),
            ("composes_into", S2, "composes_into (Φ-iii, mechanical = 2×contractions)"),
            ("provenance", S3, "provenance (curriculum path)"),
            ("learned", S4, "statistical / semantic (learned)")]
    bottom = [0] * len(x)
    for k, col, lab in keys:
        if k == "learned":
            v = [a["edges"] - a["bootstrap"] - a["composes_into"] - a["provenance"]
                 for a in aft]
            # 這一段全程是 0，圖上不會出現任何黃色。讀者不該靠「注意到某個顏色
            # 沒出現」才發現這件事 —— 把它寫進圖例標籤，資訊跟色塊待在一起。
            if not any(v):
                lab += " — 0 at every checkpoint"
        else:
            v = [a.get(k, 0) for a in aft]
        ax.bar(x, v, bottom=bottom, label=lab, color=col, width=3.2,
               edgecolor=SURFACE, linewidth=1.2)
        bottom = [b + q for b, q in zip(bottom, v)]
    # contrast 檢查是 WARN（兩色低於 3:1）→ 規範要求補可見標籤，這裡直接標總數
    for xi, v in zip(x, bottom):
        ax.annotate(str(int(v)), (xi, v), textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=8, color=INK2)
    ax.set_ylabel("edges by origin", color=INK2, fontsize=9)
    ax.legend(fontsize=8, frameon=False, labelcolor=INK2, loc="upper left")
    ax.margins(y=.26)

    # ④ 孤島率（單序列）
    ax = axes[3]
    ax.plot(x, iso, "-o", color=S1, lw=1.8, ms=5.5)
    for xi, v in zip(x, iso):
        ax.annotate(f"{v:.1f}%", (xi, v), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8, color=INK2)
    ax.set_ylabel("isolate ratio (%)", color=INK2, fontsize=9)
    ax.set_xlabel("attempt", color=INK2, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_xticks(x)

    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  → {out}")

    print("\n  數據摘要（首 → 末 checkpoint）:")
    a0, a1 = aft[0], aft[-1]
    for k, lab in [("nodes", "節點"), ("edges", "邊"), ("isolates", "孤島"),
                   ("macros", "macro"), ("composes_into", "composes_into 邊"),
                   ("provenance", "provenance 邊")]:
        print(f"    {lab:18s} {a0.get(k,0):5} → {a1.get(k,0):5}")
    print(f"    {'孤島率':18s} {a0['isolate_ratio']:.1%} → {a1['isolate_ratio']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
