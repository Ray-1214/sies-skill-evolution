# SIES 架構速覽

> **一句話**：SIES 讓 LLM 代理在**模型權重全程凍結**的前提下成長——成長發生在一張
> 外顯、可讀、可回溯的**技能圖譜**上，由演化算子 Φ 反覆改寫，而不是發生在參數裡。

30 秒版：代理每做完一批任務，就回頭看自己的軌跡，把可重用的做法抽成技能檔案存進圖裡；
圖會自己評估哪些技能有用（效用衰減）、把重複的擋掉（去重門檻）、把常一起用的合併成巨集技能、
再依效用把技能分到活躍／冷卻／封存三層。下一次規劃時，只有活躍層會被載入。
整個演化過程是一堆人看得懂的 `SKILL.md` 與一份 `GRAPH_INDEX.md`，不是一坨權重。

---

## 1. 閉環

```
                  ┌──────────────────── 演化閉環（Φ 更新後，A2 下次即可檢索）─────────────────┐
                  │                                                                          │
   ┌─────────┐   ┌┴────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐      │
   │ 課程出題 │──▶│   A1    │──▶│   A2    │──▶│ Executor │──▶│   A3    │──▶│    Φ     │──────┘
   │curriculum│   │任務分解 │   │記憶規劃 │   │ ReAct 迴圈│   │反思萃取 │   │  演化    │
   └─────────┘   └─────────┘   └────┬────┘   └──────────┘   └─────────┘   └────┬─────┘
                                     │ 檢索 top-k                                │ 寫入
                                     │                                          │
                            ┌────────▼──────────────────────────────────────────▼────────┐
                            │  技能圖譜 G = (Σ, E, W)                                     │
                            │  活躍層 M_active │ 冷卻層 M_cold │ 封存層 M_archive          │
                            └───────────────────────────────────────────────────────────┘

   T → T_struct        T_struct + G → 執行計畫        τ → ΔΣ           G_t → G_{t+1}
```

- **A1 任務分解**：自然語言任務 → `{subtasks, constraints, objectives}`，標注依賴與風險。
- **A2 記憶引導規劃**：以 `T_struct` 查圖，依活化分數 `Act(σ) = λ₁·sim + λ₂·U(σ) + λ₃·centrality` 取 top-k 注入工作記憶。
  `sim = 1 − d/2`（d 為 LanceDB l2 metric 回傳的平方距離，向量已正規化）。
- **Executor**：自建最小化 ReAct 代理（`SimpleAgent`），工具＝程式碼執行／shell／網路搜尋，跑在 Docker 沙盒。
- **A3 反思萃取**：讀執行軌跡 τ，抽出候選技能 ΔΣ。
- **Φ 演化**：每批任務後作用一次，把 ΔΣ 與效用變動落地到圖上。

---

## 2. 四個演化算子

| | 算子 | 一句話 |
|---|---|---|
| **Φ-i** | 效用評估 | 依真實軌跡更新 `U(σ) = α·r + β·f − γ_c·c`，並施加時間衰減 `U ← (1−γ)U + ΔU`。 |
| **Φ-ii** | 技能插入 | 三重驗證——格式檢查、去重（`sim > θ_dup = 0.75` 即剔除）、品質檢查——通過才入圖。 |
| **Φ-iii** | 子圖收縮 | 以共現 support × lift 雙門檻找高頻技能對，合併為 macro 節點；**parent 不移除**，降為冷卻層並補 `composes_into` 邊（刻意偏離 Definition 7，見 §5）。 |
| **Φ-iv** | 記憶分層 | 依更新後的效用，以遲滯閾值（θ_high/θ_low ± ε）在三層間遷移，避免邊界震盪。 |

觸發條件：**T1** 任務失敗｜**T2** 軌跡長度超過移動平均｜**T3** 高共現子序列頻率超門檻。
任一成立即啟動。（T3 現況見 §5。）

---

## 3. 形式化物件 → 實作落點

| 形式化物件 | 內容 | 實作 |
|---|---|---|
| **Definition 2** 技能 | `σ = (π_σ, β_σ, I_σ, µ_σ)`，`µ_σ = (f, r, c, v)` | `skills/*/SKILL.md` frontmatter＋[parse_graph_index.py](parse_graph_index.py) |
| **Eq. 20-21** 活化分數 | `Act(σ) = λ₁·sim + λ₂·U + λ₃·centrality` | [memory_planner.py](memory_planner.py)（A2） |
| **Definition 4** 效用 | `U(σ) = α·r + β·f − γ_c·c`；衰減 `U_{t+1} ← (1−γ)U_t + ΔU_t` | [evolution/utility_engine.py](evolution/utility_engine.py) |
| **Definition 5** 記憶分割 | 三層＋遲滯 ε_h / ε_l | [evolution/memory_tier_manager.py](evolution/memory_tier_manager.py) |
| **Definition 7** 巨集技能 | `π_{σ*} = π_{σj} ∘ … ∘ π_{σi}` | [evolution/graph_contractor.py](evolution/graph_contractor.py) |
| **Definition 8** 演化算子 Φ | 四子算子 (i)–(iv) | [evolution/evolution_operator.py](evolution/evolution_operator.py) |
| **Lemma 1** 幾何衰減 | `U_t(σ) = U_{t₀}(σ)(1−γ)^{t−t₀}` | `utility_engine`（⚠️ 衰減只作用於活躍層，故對 cold/archive 不適用） |
| **Lemma 2** 收縮保可解性 | 收縮後任務仍可解且序列更短 | `graph_contractor` |
| **Proposition 1** 規模有界 | `K* ≤ c·⌈log(U_max/θ) / −log(1−γ)⌉` | ❌ **未實作**（`max_skills` 是死鍵，從未被讀取） |

---

## 4. 技術堆疊與硬體

| 層 | 選型 |
|---|---|
| 語言模型 | Gemma-4-26B-A4B，本地 llama-server（`:8080`），**權重全程凍結** |
| 嵌入 | llama-embed-nemotron-8b，**在 CPU 執行**（`config.yaml: embedding.device: "cpu"`）。冷啟動約 7.6 s、常駐約 14.1 GiB RAM，實測見 `docs/DEMO_FEASIBILITY_20260913.md` |
| 向量檢索 | LanceDB（l2 metric） |
| 圖 | NetworkX，落地為可讀的 `skills/GRAPH_INDEX.md` |
| 執行沙盒 | Docker |
| 技能格式 | 相容開放 SKILL.md 標準 |
| 硬體 | i9-13900K ＋ **單張 RTX 4060 Ti 16GB**（消費級）。全程單機本地：**語言模型在 GPU、嵌入模型在 CPU**、演化與圖操作在 CPU。不倚賴任何外部 API |

---

## 5. 這個系統做到了什麼、沒做到什麼

| ✅ 做到了 | ❌ 還沒做到 / 不成立 |
|---|---|
| A1→A2→Executor→A3→Φ 全串通，2026-09-08 完成 50 題長跑，pipeline 成功 **50/50** | **Prop 1 的硬容量上限未實作**。收縮不移除 parent、封存層不刪節點、無剪枝路徑 → 節點數**單調成長**，與 Definition 10「硬容量上限 K ≥ K*」衝突 |
| 獨立 oracle 驗證 **32/43 = 74%**（分母是「有可用獨立 oracle 的題數」，不是 50） | **統計語意學到的邊 = 0**。216 條邊的帳目：bootstrap 6／`composes_into` 4／provenance 206／**學到的 0** |
| 技能與演化全部外顯為 `SKILL.md` ＋ `GRAPH_INDEX.md`，可讀、可回溯、可稽核 | **`composes_into` 邊是機械產生的**（＝2×收縮次數），不能當學習證據 |
| 控制實驗（同 50 題，唯一變數是 A3 提示）：候選 **−52%**、插入 **−45%**、步數 **−15%**，成功率 49/50 → 50/50 | **206 條 provenance 邊不是學習成果**，權重只有 `0.4`/`0.7` 兩個硬編常數，由課程路徑位置序機械落地 |
| 三層分級＋遲滯運作中（110 節點：active 31／cold 13／archive 66） | **T3 觸發條件無鑑別力**：真實 324 筆軌跡上四個切片全為 True，唯一過門檻的 n-gram 是 `code_execution → finish`（80.6%），那是 ReAct 收尾形狀而非技能訊號 |
| Φ-iii 收縮可運作，產出 2 個 macro 並補上 `composes_into` 邊 | **Assumption 3（uniform decay）不成立**：衰減只作用於活躍層 → Lemma 1 對 cold/archive 無效；**Assumption 4(c)（held-out 可解性不下降）完全未實作** |
| 課程式自動出題閉環為 in-process，演化後即刷新 A2 圖譜快取 | 百題長期演化與跨領域遷移**尚未執行**；該場長跑 5 個 checkpoint 的 Φ-iii `macros=0`（現有 2 個 macro 來自更早期） |

> 詳細診斷：[docs/T3_TRIGGER_RATE_20260916.md](docs/T3_TRIGGER_RATE_20260916.md)、
> `SIES_MASTER_TRACKER.md` §11.5（論文必改清單）與 §16.4（零證據項目）。
> 論文側的對應說明見 [proposal/main.tex](proposal/main.tex) §5.4 限制條款。

---

## 6. 檔案在哪

```
（專案根目錄）    A2 與執行層
  memory_planner.py       A2 記憶引導規劃（活化分數 + top-k + 工作記憶組裝）
  executor.py             計畫執行器（docker_exec / local 兩種模式）
  embedding_engine.py     嵌入模型封裝
  vector_store.py         LanceDB 檢索
  parse_graph_index.py    GRAPH_INDEX.md → NetworkX DiGraph + centrality

agents/          A1 / A3 / 執行器與課程
  task_decomposer.py      A1 任務分解
  reflective_evaluator.py A3 反思評估
  skill_extractor.py      A3 的技能萃取
  skill_validator.py      Φ-ii 三重驗證（格式 / 去重 / 品質）
  simple_agent.py         ReAct 執行器（Thought → Action → Observation）
  agent_runner.py         單題端到端串接
  curriculum_agent.py     課程式自動出題
  curriculum_loop.py      消費／生產雙分支閉環
  path_generator.py       方向 → 學習路徑四元組（provenance 邊的資料來源）
  pattern_recognizer.py   T3 的 n-gram 共現分析

evolution/       演化算子 Φ
  evolution_operator.py   Φ 主控（i → ii → iii → iv）
  utility_engine.py       Φ-i 效用與衰減
  graph_contractor.py     Φ-iii 子圖收縮
  memory_tier_manager.py  Φ-iv 三層遷移
  skill_cooccurrence.py   共現 support / lift
  provenance_edges.py     follows / requires 邊
  evolution_triggers.py   T1 / T2 / T3

skills/          技能圖譜（人看得懂的那一份）
  active/ cold/ archive/  三層的 SKILL.md
  candidates/             待驗證的候選技能
  GRAPH_INDEX.md          節點、邊、tier 分布

demo/            終端 demo 與圖表輸出
proposal/        專題計畫書（main.tex）
docs/paper/      形式框架論文（main.pdf，10 個 Definition / Prop 1-4 / Theorem 1）
scripts/         長跑、驗證、體檢（verify_runner.py / sies_doctor.py / w16_run.py）
memory/episodic/ 執行軌跡（T-*.jsonl）與 run_summary.jsonl
config.yaml      所有閾值（含哪些是死鍵的註記）
```
