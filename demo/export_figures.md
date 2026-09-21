# 從 demo/index.html 匯出 PDF 用的圖檔

論文／簡報要的四張圖，`index.html` 裡都有對應的匯出按鈕。
本檔說明每張圖怎麼取得、輸出尺寸是多少，以及按鈕失效時的替代作法。

**開啟方式**：用瀏覽器直接開 `demo/index.html`（`file://` 即可，不需要起 server）。
需要 `demo/vendor/cytoscape.min.js` 在相對位置，其餘全部內嵌。

> **不想手動開瀏覽器的話**：`python demo/export_figures.py` 會用 headless chromium
> 載入同一份 `index.html`、按下同樣那幾個按鈕，把四張圖直接寫進 `docs/figures/`
> （已進版控）。本檔以下講的是手動路徑；兩條路徑產出的是同一批圖。
> 細節見 `docs/figures/README.md`。
>
> 注意 headless 那條路徑的第四張是 **`fig4_longrun_task1.png`**（長跑回放第 1 題的
> 三層 success 截圖），跟本檔下面講的 `fig4_activation.png` 不是同一張圖。

---

## 四張圖一覽

| 檔名 | 在哪一頁 | 按鈕 | 輸出尺寸 | 機制 |
|---|---|---|---|---|
| `fig1_skill_graph.png` | 1. 技能圖 | 右上「匯出 PNG (3x)」 | 圖寬視當前佈局而定，上方固定加 **118 px × 3 = 354 px** 的標題與圖例 | `cy.png(...)` → 另一張 canvas 合成標題＋圖例＋圖 |
| `fig2_growth.png` | 5. 成長曲線 | 底部「匯出四宮格 PNG」 | **3540 × 2100**（1180×700 的 3 倍） | SVG → canvas → PNG |
| `fig3_honest_table.png` | 7. 誠實牆 | 右上「匯出 PNG」 | **3840 × 2046**（1280×682 的 3 倍） | SVG → canvas → PNG |
| `fig4_activation.png` | 2. 語意檢索 | 表格下方「匯出本組 PNG」 | **3240 × 990**（1080×330 的 3 倍） | SVG → canvas → PNG |

---

## fig1_skill_graph.png — 技能圖

1. 開啟 `index.html`，預設就停在「1. 技能圖」。
2. **確認左上「顯示 72 個孤立節點 (65.5%)」的 checkbox 沒有勾選**（預設就是不勾）。
   孤立節點佔 110 個中的 72 個，全部畫出來會讓有邊的結構完全看不見。
3. 需要的話按「重新佈局」重跑 cose，直到分佈滿意；按「重置視野」把整張圖置中。
4. 按右上「匯出 PNG (3x)」。

下載的是 `fig1_skill_graph.png`。`full: true` 代表匯出整張圖（不是只有目前螢幕看得到的部分），
`scale: 3` 是 3 倍解析度，`bg: '#ffffff'` 讓底色是白的而不是透明（PDF 裡透明會變黑）。

**圖例會一起進到圖片裡。** `cy.png()` 只吐 cytoscape 那塊畫布，而圖例是畫面上的 HTML，
不在畫布內；照原樣匯出的話 `learned 0` 會消失，只剩「216 條邊」，讀者會得到
「系統建出了豐富的連結」這個剛好與誠實牆相反的印象。所以匯出時會另開一張 canvas，
依序畫上：

```
SIES 技能圖譜 — 110 節點 / 216 邊（隱藏 72 個孤立節點）
資料快照 2026-09-13 · 節點顏色=tier，大小=utility，菱形=macro，邊顏色=provenance
■ active 31   ■ cold 13   ■ archive 66   ◆ macro 2
— bootstrap 6   — curriculum 206   — contraction 4   — learned 0
────────────────────────────────────────────────
（cytoscape 的圖）
```

標題括號內會跟著孤立節點 checkbox 變（勾選時是「含 72 個孤立節點」）；
圖例的顏色、形狀、數字全部是匯出當下從畫面上的 DOM 讀的（`getComputedStyle`），
沒有任何色碼寫死在匯出程式裡——改了 CSS 變數，匯出就跟著改。
若某個邊類別被點掉，圖例會照畫面顯示成淡化加刪除線，跟圖的內容一致。

**若要只呈現某個子結構**：圖例的四個邊類別（bootstrap / curriculum / contraction / learned）
每一項都可以點擊切換顯示。例如只留 `contraction` 就會看到兩個 macro 與它們的 parent；
只留 `bootstrap` 就是最初那 6 條手寫種子邊。切換後再按匯出即可。

---

## fig2_growth.png — 成長曲線四宮格

1. 切到「5. 成長曲線」。
2. 按最下方「匯出四宮格 PNG (fig2_growth.png)」。

四張子圖依序是：節點數 / 邊數 / 孤島率 / verified 率（累計），
x 軸是完成題數（10/20/30/40/50 五個 checkpoint）。
前三張取每個 checkpoint 的 `graph_after_phi`；第四張是累計至該題為止、
分母排除 `verified_liveness` 的比率。

每張子圖也有各自的「匯出 PNG」按鈕（輸出 620×360 的 3 倍 = 1860×1080），
如果版面只放得下一張，用單張的比較清楚。

---

## fig3_honest_table.png — 誠實牆

1. 切到「7. 誠實牆 ★」。
2. 按右上「匯出 PNG」。

輸出含：標題列、12 條宣稱（6 個 ✅ / 3 個 ⚠️ / 3 個 ❌）、以及下方那段三行的結語。
❌ 的三列在圖上有淡紅底色，印成黑白時仍可從 ❌ 符號區分。

畫面上表格下方還有兩段文字（no-skill 對照的解讀、T3 判定為什麼恆為真），
那兩段**不在** PNG 裡，只在 demo 頁面上。要一起放進書審資料的話請另外複製。

---

## fig4_activation.png — Activation Score 拆解

1. 切到「2. 語意檢索」。
2. 左側 8 個查詢挑一組。**建議挑第 3 組**
   （`implement a recursive algorithm with memoization and test it`）：
   它的 top-1 是 `recursive-formula-implementation-with-memoization`，sim 高達 0.6811 但 centrality 是 0，
   而第 2 名 `algorithm-implementation-with-test-harness` 是 sim 較低、U 較高 —— 兩項互相拉扯的對比最清楚。
3. 按表格下方「匯出本組 PNG」。

輸出含公式 `A(σ) = 0.5·sim + 0.3·U(σ) + 0.2·centrality(σ)`、6 列結果、
每列的三段堆疊橫條（藍 = λ1·sim，中藍 = λ2·U，淺藍 = λ3·centrality），
以及右側的 sim / U / centrality 三欄數值。

---

## 如果按鈕沒有反應 → 改用瀏覽器截圖

**匯出機制與已知限制**：

- `fig1` 先用 `cy.png({output:'blob'})` 取得 cytoscape 的畫布，再經
  `Image` → `<canvas>` → `toBlob('image/png')` 跟標題與圖例合成。
  中間那張 `Image` 載的是 blob URL、屬同源，不會讓 canvas 變 tainted。
- `fig2` / `fig3` / `fig4` 走「SVG → `Image` → `<canvas>` → `toDataURL('image/png')`」。
  這三張的 SVG 已驗證是**完全自足**的：合法 XML、**0 個外部引用**、
  沒有 `<image>`、沒有 `<foreignObject>`。這正是 canvas 不會被標記為 tainted、
  `toDataURL()` 可以正常取值的條件。
- 但兩者都依賴 `<a download>` 觸發下載。**部分瀏覽器對 `file://` 頁面的
  程式化下載有額外限制**，若真的被擋，程式會跳出提示要你改用截圖。

> ✅ **已實際點過（2026-09-21）**：`demo/export_figures.py` 在 playwright 的
> headless chromium（153.0.8010.12）裡載入 `file://` 的 `index.html`，實際點下
> `#btnPngGraph`、「匯出四宮格 PNG」、`#btnPngHonest` 三個按鈕，三次都成功觸發
> `<a download>` 並接住檔案 —— 也就是說 **file:// 的程式化下載在 chromium 沒有被擋**。
> 頁面 JS 零執行期錯誤，fig1 合成出來的標題帶經逐點取樣，四個 provenance 色票
> （含 `learned` 的 `#a02c5a`）都在。
>
> 仍未驗證的是 **firefox / safari** 上的下載行為：這台機器的 `firefox` 是 snap
> wrapper，headless 連空白頁都會卡住，無法自動化。若在那邊按了沒反應，
> 用下面的截圖備案。

### 截圖備案（保證可行）

1. 把瀏覽器**視窗寬度設為 1440**（開發者工具的裝置模擬可以精確設定）。
2. **瀏覽器縮放設為 200%**，這樣截出來的點陣圖等同 2 倍解析度。
3. 切到目標分頁，用系統截圖工具framed 截取內容區域。
   - macOS：`Cmd+Shift+4` 後按空白鍵改成視窗截取
   - Windows：`Win+Shift+S`
   - Linux/GNOME：`Shift+PrtSc`
4. 誠實牆與成長曲線的內容在 1440×900 下不需捲動即可完整入鏡；
   技能圖若要完整版建議仍用 `cy.png()`，因為 `full:true` 會含畫布外的部分。

### 再一個備案：直接取 SVG 原始碼

四張 SVG 都是程式即時產生的字串，可以在 DevTools console 裡直接取出來存成 `.svg`
（向量格式，放進 LaTeX 比 PNG 更清楚）：

```js
// 誠實牆
copy(honestSVG())

// Activation 拆解（第 3 組查詢，index 從 0 起算）
copy(activationSVG(Q.retrieval[2], Q.config))

// 成長曲線四宮格
copy((function(){
  const cks = D.run.checkpoints, A = D.run.attempts;
  const ver = cks.map(c => {
    const u = A.slice(0, c.checkpoint).filter(a => a.verification_status === 'verified_independent');
    return u.length ? u.filter(a => a.verified_success === true).length / u.length : 0;
  });
  const xs = cks.map(c => c.checkpoint);
  return quadSVG(CH.map(ch => ({ ch, xs,
    ys: ch.key === 'verified' ? ver : cks.map(c => ch.src(c.graph_after_phi)) })));
})())
```

貼進檔案存成 `.svg` 即可。這條路徑不經過 canvas，也不需要下載權限，
是三者中最不會出問題的。（上面四份 SVG 就是用這個方式產出來驗證的。）

---

## 重新產生資料後要做的事

`index.html` 是把資料**內嵌**進去的靜態檔，來源資料變了要重跑：

```bash
python demo/build_data.py      # → demo/data.json
python demo/build_queries.py   # → demo/queries.json   （約 42 秒，會載 embedding 模型）
python demo/build_html.py      # → demo/index.html
```

`build_queries.py` 需要 embedding 模型（CPU，冷啟動約 7.5 秒、常駐約 14 GiB RAM），
另外兩支不需要。三支都只讀來源檔，唯一的寫入是各自的輸出。
