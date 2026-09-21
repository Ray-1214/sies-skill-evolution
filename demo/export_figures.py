#!/usr/bin/env python3
"""
demo/export_figures.py — headless 產出論文/書審用的四張圖到 docs/figures/
=======================================================================

不需要有人開瀏覽器。用 playwright 的 chromium 載入 `demo/index.html`
（`file://`，跟人工開的是同一個檔），按下頁面上原本就有的匯出按鈕，
把瀏覽器發出的下載接住寫檔。

  docs/figures/fig1_skill_graph.png      技能圖（標題＋圖例合成進圖片，3x）
  docs/figures/fig2_growth.png           成長曲線四宮格（3x）
  docs/figures/fig3_honest_table.png     誠實牆 12 列（3x）
  docs/figures/fig4_longrun_task1.png    長跑回放第 1 題（三層 success，3x 截圖）

**數字一律來自 `demo/data.json`**：index.html 是 build_html.py 把 data.json
內嵌進 template.html 的產物，頁面上的 `D` 就是那份 JSON。本腳本不自己算任何
統計值，只在開跑前把頁面的 `D.counts` 跟磁碟上的 `demo/data.json` 逐鍵比對，
不一致就中止（代表 index.html 沒重建）。

為什麼不用 firefox：這台機器的 firefox 是 snap wrapper，headless 連空白頁
都會卡住。chromium 由 playwright 自帶（`python -m playwright install chromium`）。

用法：
    python demo/export_figures.py                 # 產出四張圖 + 驗證
    python demo/export_figures.py --out DIR       # 改輸出目錄
    python demo/export_figures.py --keep-browser  # 除錯：不關瀏覽器
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INDEX = HERE / "index.html"
DATA_JSON = HERE / "data.json"
DEFAULT_OUT = ROOT / "docs" / "figures"

SCALE = 3          # 與頁面上匯出按鈕寫死的 3x 一致
VIEWPORT = {"width": 1440, "height": 900}

# cytoscape 的 cose layout 是迭代式的，animate:false 也要幾百毫秒才收斂。
# 這個值只影響佈局好不好看，不影響任何數字。
LAYOUT_SETTLE_MS = 2500


# --------------------------------------------------------------------------
# 頁面內執行的片段
# --------------------------------------------------------------------------

# 匯出按鈕走的是 `<a download>`。若瀏覽器擋掉 file:// 頁面的程式化下載，
# 改用這條備援：呼叫頁面上同一組合成函式，直接把 data URL 交回來。
JS_GRAPH_DATAURL = """
async (scale) => {
  const blob = cy.png({ scale, full:true, bg:'#ffffff', output:'blob' });
  const url = URL.createObjectURL(blob);
  const img = await new Promise((res, rej) => {
    const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url;
  });
  const { cv, ctx, W, HEAD } = graphHeaderCanvas(img.width, img.height, scale);
  ctx.drawImage(img, (W - img.width / scale) / 2, HEAD, img.width / scale, img.height / scale);
  URL.revokeObjectURL(url);
  return cv.toDataURL('image/png');
}
"""

JS_SVG_DATAURL = """
async (svg) => {
  const m = svg.match(/width="(\\d+)" height="(\\d+)"/);
  const w = +m[1], h = +m[2], S = 3;
  const blob = new Blob([svg], { type:'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const img = await new Promise((res, rej) => {
    const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url;
  });
  const cv = document.createElement('canvas');
  cv.width = w * S; cv.height = h * S;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.drawImage(img, 0, 0);
  URL.revokeObjectURL(url);
  return cv.toDataURL('image/png');
}
"""

# 匯出當下頁面實際用的標題／圖例文字與色票，全部從 DOM 讀回來做為證據。
JS_LEGEND_PROBE = """
() => ({
  counts: D.counts,
  generated_at: D.generated_at,
  edge_colors: EDGE_CLASSES.map(c => c.color),
  tier_colors: TIERS.map(t => t.color),
  legend_node: [...document.querySelectorAll('#legNode .lg')]
                 .map(e => e.textContent.trim().replace(/\\s+/g, ' ')),
  legend_edge: [...document.querySelectorAll('#legEdge .lg')]
                 .map(e => e.textContent.trim().replace(/\\s+/g, ' ')),
  show_iso: document.querySelector('#showIso').checked,
})
"""


def _data_url_to_bytes(data_url: str) -> bytes:
    head, _, payload = data_url.partition(",")
    if "base64" not in head:
        raise ValueError(f"非 base64 的 data URL: {head[:40]}")
    return base64.b64decode(payload)


def _save(path: Path, blob: bytes, how: str, log: list) -> None:
    path.write_bytes(blob)
    size = path.stat().st_size
    log.append((path.name, size, how))
    print(f"  ✓ {path.name:26s} {size:>9,} bytes   ({how})")


def _grab_download(page, click, dest: Path, log: list, fallback) -> None:
    """優先走真正的按鈕下載；被瀏覽器擋掉就退回 in-page data URL。"""
    try:
        with page.expect_download(timeout=20_000) as info:
            click()
        info.value.save_as(str(dest))
        _save(dest, dest.read_bytes(), "按鈕下載", log)
    except Exception as exc:                       # noqa: BLE001 — 任何失敗都退備援
        print(f"  … 按鈕下載未成功（{type(exc).__name__}），改用 in-page data URL")
        _save(dest, _data_url_to_bytes(fallback()), "in-page data URL", log)


# --------------------------------------------------------------------------
# 驗證
# --------------------------------------------------------------------------

def verify_counts_match(page_counts: dict, disk_counts: dict) -> None:
    """頁面上的數字必須就是 demo/data.json 的數字，否則 index.html 沒重建。"""
    if page_counts != disk_counts:
        diff = {k: (disk_counts.get(k), page_counts.get(k))
                for k in set(page_counts) | set(disk_counts)
                if page_counts.get(k) != disk_counts.get(k)}
        raise SystemExit(
            "[export_figures] index.html 內嵌的 counts 與 demo/data.json 不一致："
            f"\n  {diff}\n  先跑 `python demo/build_html.py` 重建。")


def trim_bottom_background(path: Path, margin_px: int) -> tuple[int, int]:
    """裁掉截圖下緣的空白。

    `#v-replay` 的高度由版面撐開，第 1 題的內容比容器短，底下會留一片純背景色。
    背景色不寫死：取最底一列的顏色當基準，往上找第一列不是它的。
    """
    from PIL import Image

    im = Image.open(path).convert("RGB")
    px = im.load()
    bg = px[0, im.height - 1]
    row = im.height - 1
    while row > 0 and all(px[x, row] == bg for x in range(0, im.width, 7)):
        row -= 1
    new_h = min(im.height, row + 1 + margin_px)
    if new_h >= im.height:
        return im.height, im.height
    im.crop((0, 0, im.width, new_h)).save(path)
    return im.height, new_h


def verify_fig1_legend(path: Path, colors: list[str], head_px: int) -> dict:
    """檢查合成出來的 fig1 頂端真的有圖例：四個 provenance 色票都要出現在標題帶裡。

    色碼是匯出當下從頁面的 EDGE_CLASSES 讀回來的，不是寫死在這支腳本裡。
    """
    from PIL import Image

    im = Image.open(path).convert("RGB")
    band = im.crop((0, 0, im.width, min(head_px, im.height)))
    present = set(band.getdata())

    def hit(hexcode: str) -> bool:
        rgb = tuple(int(hexcode.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return any(abs(p[0] - rgb[0]) + abs(p[1] - rgb[1]) + abs(p[2] - rgb[2]) <= 12
                   for p in present)

    found = {c: hit(c) for c in colors}
    return {"size": im.size, "band_px": band.size, "swatches": found,
            "band_nonwhite": sum(1 for p in present if p != (255, 255, 255))}


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--keep-browser", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[export_figures] 需要 playwright：\n"
              "    pip install playwright && python -m playwright install chromium",
              file=sys.stderr)
        return 2

    for p in (INDEX, DATA_JSON):
        if not p.exists():
            print(f"[export_figures] 缺少 {p}", file=sys.stderr)
            return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    disk = json.loads(DATA_JSON.read_text(encoding="utf-8"))

    log: list[tuple[str, int, str]] = []
    print(f"[export_figures] 來源 {INDEX}")
    print(f"[export_figures] 輸出 {out}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---- fig1 / fig2 / fig3：頁面自己產生 3x 點陣，瀏覽器不必放大 ----
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1,
                                  accept_downloads=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(INDEX.as_uri(), wait_until="load")
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0",
                               timeout=30_000)
        page.wait_for_timeout(LAYOUT_SETTLE_MS)

        probe: dict = page.evaluate(JS_LEGEND_PROBE)
        verify_counts_match(probe["counts"], disk["counts"])
        print("[export_figures] 頁面 D.counts == demo/data.json counts ✓")
        print(f"  節點圖例: {' | '.join(probe['legend_node'])}")
        print(f"  邊圖例  : {' | '.join(probe['legend_edge'])}")
        print(f"  孤立節點 checkbox: {probe['show_iso']}（False = 隱藏，與圖說一致）\n")

        print("[export_figures] 產圖：")
        page.evaluate("show('graph'); cy.resize(); cy.fit(undefined, 28);")
        page.wait_for_timeout(400)
        _grab_download(page, lambda: page.click("#btnPngGraph"),
                       out / "fig1_skill_graph.png", log,
                       lambda: page.evaluate(JS_GRAPH_DATAURL, SCALE))

        page.evaluate("show('growth')")
        page.wait_for_timeout(200)
        _grab_download(
            page,
            lambda: page.click("button:has-text('匯出四宮格 PNG')"),
            out / "fig2_growth.png", log,
            lambda: page.evaluate(JS_SVG_DATAURL, page.evaluate("""
                () => {
                  const cks = D.run.checkpoints, A = D.run.attempts;
                  const ver = cks.map(c => {
                    const u = A.slice(0, c.checkpoint)
                               .filter(a => a.verification_status === 'verified_independent');
                    return u.length ? u.filter(a => a.verified_success === true).length / u.length : 0;
                  });
                  const xs = cks.map(c => c.checkpoint);
                  return quadSVG(CH.map(ch => ({ ch, xs,
                    ys: ch.key === 'verified' ? ver : cks.map(c => ch.src(c.graph_after_phi)) })));
                }""")))

        page.evaluate("show('honest')")
        page.wait_for_timeout(200)
        _grab_download(page, lambda: page.click("#btnPngHonest"),
                       out / "fig3_honest_table.png", log,
                       lambda: page.evaluate(JS_SVG_DATAURL, page.evaluate("honestSVG()")))

        ctx.close()

        # ---- fig4：回放頁沒有匯出按鈕，用 3x 的裝置像素比直接截圖 ----
        ctx3 = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE)
        page3 = ctx3.new_page()
        page3.on("pageerror", lambda e: errors.append(str(e)))
        page3.goto(INDEX.as_uri(), wait_until="load")
        page3.wait_for_function("typeof D !== 'undefined'", timeout=30_000)
        page3.evaluate("show('replay'); go(0);")
        page3.wait_for_timeout(500)

        a0 = page3.evaluate("() => D.run.attempts[0]")
        expect = disk["run"]["attempts"][0]
        if (a0["attempt_no"], a0["verified_success"]) != (expect["attempt_no"],
                                                          expect["verified_success"]):
            raise SystemExit("[export_figures] 回放第 1 題與 data.json 不符")
        print(f"\n  fig4 對象：#{a0['attempt_no']} {a0['task_id']} "
              f"pipeline={a0['pipeline_success']} execution={a0['execution_completed']} "
              f"verified={a0['verified_success']}（{a0['verify_detail']}）")

        shot = out / "fig4_longrun_task1.png"
        page3.locator("#v-replay").screenshot(path=str(shot))
        was, now = trim_bottom_background(shot, margin_px=18 * SCALE)
        if now != was:
            print(f"  fig4 裁掉下緣空白：{was} → {now} px")
        _save(shot, shot.read_bytes(), f"頁面截圖 {SCALE}x", log)
        ctx3.close()

        if not args.keep_browser:
            browser.close()

    if errors:
        print("\n[export_figures] ⚠️ 頁面 JS 執行期錯誤：")
        for e in errors:
            print(f"  {e}")
        return 1
    print("\n[export_figures] 頁面 JS 零執行期錯誤 ✓")

    # ---- fig1 的圖例驗證 ----
    head_px = 118 * SCALE                   # graphHeaderCanvas 的 HEAD 常數 × scale
    v = verify_fig1_legend(out / "fig1_skill_graph.png", probe["edge_colors"], head_px)
    print(f"\n[export_figures] fig1 圖例檢查（頂端 {head_px}px 標題帶）")
    print(f"  尺寸 {v['size'][0]}×{v['size'][1]}，標題帶非白像素 {v['band_nonwhite']:,} 色")
    for label, color in zip(probe["legend_edge"], probe["edge_colors"]):
        print(f"  {'✓' if v['swatches'][color] else '✗'} {label:16s} {color}")
    if not all(v["swatches"].values()):
        print("[export_figures] 圖例色票沒有全部出現在標題帶裡", file=sys.stderr)
        return 1

    print("\n[export_figures] 完成：")
    for name, size, how in log:
        print(f"  {name:26s} {size:>9,} bytes  {how}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
