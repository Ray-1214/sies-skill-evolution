# 論文／書審用圖

四張圖由 `demo/export_figures.py` 產生，**進版控**，不需要每次手動開瀏覽器截圖。

```bash
pip install playwright && python -m playwright install chromium   # 一次性
python demo/export_figures.py                                      # → docs/figures/*.png
```

## 產生方式

腳本用 playwright 的 **headless chromium** 載入 `demo/index.html`（`file://`，
跟人工開的是同一個檔），然後：

| 檔案 | 怎麼來的 |
|---|---|
| `fig1_skill_graph.png` | 按下頁面上的「匯出 PNG (3x)」，接住瀏覽器的下載 |
| `fig2_growth.png` | 按下「匯出四宮格 PNG」，接住下載 |
| `fig3_honest_table.png` | 按下誠實牆的「匯出 PNG」，接住下載 |
| `fig4_longrun_task1.png` | 回放頁沒有匯出按鈕，改用 `device_scale_factor=3` 對 `#v-replay` 截圖，再裁掉下緣空白 |

前三張是 demo 頁面自己用 canvas 畫出來的 3x 點陣，**不是螢幕截圖**；
第四張是 3x 的真實截圖。四張都是同一份頁面、同一份資料。

**數字全部來自 `demo/data.json`**：`index.html` 是 `build_html.py` 把 `data.json`
內嵌進 `template.html` 的產物。腳本開跑前會把頁面上的 `D.counts` 跟磁碟上的
`demo/data.json` 逐鍵比對，不一致就中止（代表 `index.html` 沒重建）。腳本本身
不算任何統計值、不寫死任何色碼 —— 連 fig1 圖例的色票都是匯出當下從頁面的
`EDGE_CLASSES` 讀回來的。

**可重現性**：fig2 / fig3 / fig4 每次產出的像素完全相同。**fig1 不是**——
cytoscape 的 `cose` 力導向佈局每次收斂到不同位置，所以節點擺放與畫布尺寸會變，
但節點數、邊數、顏色、圖例文字都一樣。要換一個佈局就再跑一次。

`firefox` 不能用：這台機器上的是 snap wrapper，headless 連空白頁都會卡住。

---

## 圖說

**圖 1.** SIES 技能圖譜，110 個節點、216 條邊（隱藏 72 個孤立節點，佔 65.5%）。
節點顏色為記憶分層，大小為效用值，菱形為 Φ-iii 收縮產生的複合技能。
邊依來源著色：其中 206 條由課程結構機械產生，4 條為收縮的工程不變式，
6 條為手寫種子，由系統從統計學到的為 0 條。

![圖 1](fig1_skill_graph.png)

---

**圖 2.** 50 題長跑的成長曲線，每 10 題取一個檢查點。右上「邊數」自 20 增至 216，
但該成長幾乎全部來自課程路徑的機械落地（206 條），不代表系統學到了技能間
的關聯；左上「節點數」97→110 才是 Φ-ii 實際插入新技能的結果。孤島率由
76.3% 降至 65.5%，同樣來自課程結構而非學習。

![圖 2](fig2_growth.png)

---

**圖 3.** 誠實牆：12 項宣稱與各自的證據來源。六項成立、三項部分成立、三項未達成。
每一格都指向可用 `python scripts/sies_doctor.py` 重算的資料檔。

![圖 3](fig3_honest_table.png)

---

**圖 4.** 長跑第 1 題的三層驗證。管線完成（pipeline_success=true）、代理自認已完成
（execution_completed=true），但獨立 oracle 檢查輸出檔案時發現 data.json 不存在
（verified_success=false）。這正是三層 success schema 存在的理由：代理的自我
報告不可作為成功的依據。

![圖 4](fig4_longrun_task1.png)
