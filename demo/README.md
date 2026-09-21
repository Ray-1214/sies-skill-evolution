# SIES demo — 離線單檔前端

用瀏覽器直接開 `demo/index.html`（`file://` 即可，**不需要起 server、不需要網路**）。
所有資料都內嵌在 HTML 裡，唯一的外部檔案是相對路徑的 `./vendor/cytoscape.min.js`。

```
demo/
├── index.html            ← 產出物（484 KiB），直接開這個
├── template.html         ← index.html 的原始碼（版面 + CSS + JS，資料是 placeholder）
├── build_data.py         ← 產生 data.json
├── build_queries.py      ← 產生 queries.json（需 embedding 模型）
├── build_html.py         ← template + 三份資料 → index.html
├── data.json             ← 圖 / 技能全文 / 演化記錄 / 長跑 / doctor（463 KiB）
├── queries.json          ← 預先算好的檢索與去重範例（20 KiB）
├── export_figures.md     ← 怎麼手動匯出論文用的四張圖
├── export_figures.py     ← headless chromium 自動產出四張圖 → docs/figures/
├── README.md             ← 本檔
└── vendor/
    ├── cytoscape.min.js       ← 見下方版本資訊
    └── cytoscape-LICENSE.txt
```

---

## 第三方相依

**只有一個。**

| 套件 | 版本 | 授權 | 檔案 | 大小 | 取得方式 |
|---|---|---|---|---|---|
| [cytoscape.js](http://js.cytoscape.org) | **3.34.3** | MIT | `vendor/cytoscape.min.js` | 435,503 bytes | `npm pack cytoscape` → `package/dist/cytoscape.min.js` |

- build：UMD（minified）。以 `require()` 實測回傳 function、`cytoscape.version === '3.34.3'`、
  headless 模式可建圖並跑 `cose` layout。
- sha256：`5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91`
- **沒有使用 CDN**。檔案已 vendored 進 repo，離線可用。
- 授權全文在 `vendor/cytoscape-LICENSE.txt`。

除此之外是純 vanilla JS：無框架、無圖表函式庫（成長曲線與匯出圖都是手寫 SVG）、
無 `fetch`、無 `XMLHttpRequest`、無 `localStorage` / `sessionStorage`。

---

## 七個分頁

| # | 分頁 | 內容 |
|---|---|---|
| 1 | **技能圖** | cytoscape 力導向圖（cose）。節點顏色 = tier、大小 = utility、macro 用菱形；邊顏色 = provenance_class，圖例可點擊切換。孤立節點預設隱藏。點節點看該技能的 SKILL.md 全文並高亮鄰居。 |
| 2 | **語意檢索** | 8 組查詢的 A2 Activation Score 結果，每列用堆疊橫條拆出 λ1·sim / λ2·U / λ3·centrality 三項貢獻。 |
| 3 | **去重閘** | 4 組候選丟進 `SkillValidator._check_dedup` 的結果，sim 值畫在以 θdup=0.75 為界的水平軸上。 |
| 4 | **長跑回放** | 50 題逐題翻頁：題目、A2 檢索到的 6 個技能、三層 success、produced_skills、成本。 |
| 5 | **成長曲線** | 5 個 checkpoint 的節點數 / 邊數 / 孤島率 / verified 率，純 SVG。 |
| 6 | **演化日誌** | Φ 的 19 次呼叫明細與累計統計。 |
| 7 | **誠實牆** | 8 條宣稱對照證據：4 個 ✅、1 個 ⚠️、3 個 ❌。 |

第 2、3 頁的結果是 **`build_queries.py` 預先算好的快照，不是即時查詢** ——
頁面上有明確標註。原因是 embedding 模型冷啟動約 7.5 秒、常駐約 14 GiB RAM，
不適合在 demo 當下載入。

---

## 重新產生

```bash
python demo/build_data.py      # 讀 GRAPH_INDEX / evolution_log / run_summary / w16 run / doctor
python demo/build_queries.py   # 約 42 秒；需 embedding 模型（CPU）
python demo/build_html.py      # 把三份資料內嵌進 template.html
```

三支都**只讀來源檔**，各自唯一的寫入是自己的輸出檔。
`build_queries.py` 對 LanceDB 只做查詢、不寫入，也不觸發 Φ、不寫 `run_summary.jsonl`。

`build_html.py` 除了 `data.json` / `queries.json`，還會去讀
`data/w16/runs/<run_id>/tasks.jsonl` 取題目描述 ——
因為 `attempts.jsonl` 只有 `task_id`，沒有題目文字。

---

## 已驗證 / 未驗證

**已驗證**（本機自動化）：

- 三個內嵌 JSON 區塊皆可解析；`<script>` 標籤配對正確（5/5）。
- 頁面 JS 在 jsdom 下**零執行期錯誤**，7 個分頁的 DOM 全部正確建出
  （節點 110 / 邊 216 / 8 組查詢 / 4 組去重 / 50 題回放可翻頁 / 4 張曲線 / 19 列日誌 / 8 列誠實牆）。
- 真 cytoscape 3.34.3 headless 實際收下 110 節點 + 216 邊並跑完 cose layout；
  style mapper 對全部 326 個元素都取得顏色（無 `undefined.color`）。
- 匯出用的四份 SVG 皆為合法 XML、0 個外部引用、無 `<image>` / `<foreignObject>`、
  所有座標都在畫布內。

- **三個匯出按鈕在真實瀏覽器裡實際點過**（2026-09-21，playwright headless
  chromium 153）：三次都成功觸發下載，產物就是版控裡的 `docs/figures/fig1..fig3`。
  頁面在 1440×900 下零執行期錯誤。見 `export_figures.py`。

**未驗證**：

- firefox / safari 的匯出按鈕行為。這台機器的 `firefox` 是 snap wrapper，
  headless 連空白頁都會卡住，無法自動化。備案見 `export_figures.md`。
- 版面在 1440×900 下是否「好看」—— 有截圖（`docs/figures/fig4_longrun_task1.png`
  就是 1440 寬的回放頁），但沒有逐頁檢查過排版。
