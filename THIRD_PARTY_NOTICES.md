# 第三方授權聲明 — Third-Party Notices

本專案整體以 MIT 授權發布，著作權人 Bo-Zhang Huang（見 [`LICENSE`](LICENSE)）。

`skills/` 底下有 **13 個種子技能**改寫自兩個開源專案。兩個上游都是 **MIT**，
允許再散布與修改，條件是保留其著作權聲明與授權條文 —— 本檔即為該保留。

這 13 個檔案是技能圖的**初始種子**，不是系統演化產出的。其餘 97 個技能中，
90 個由 A3 萃取（`author: SIES-A3`）、2 個由 Φ-iii 收縮產生
（`author: SIES-Phi-iii`）、5 個為本專案手寫（`author: SIES`）。

每個受影響檔案的 frontmatter 都有 `source:` 欄位指回上游 repo。

---

## 1. superpowers — 8 個檔案

| | |
|---|---|
| **上游** | https://github.com/obra/superpowers |
| **授權** | MIT |
| **著作權聲明** | `Copyright (c) 2025 Jesse Vincent` |
| **取得版本** | `v5.0.7-2-gdd23728` |

改寫自上游 `skills/<name>/SKILL.md`（該路徑在 v5.x 之後的版本已不存在；
內容取自 commit `3f80f1c` 時的狀態）：

| 本專案路徑 | 上游路徑 |
|---|---|
| `skills/active/seed/brainstorming/SKILL.md` | `skills/brainstorming/SKILL.md` |
| `skills/active/seed/subagent-driven-development/SKILL.md` | `skills/subagent-driven-development/SKILL.md` |
| `skills/active/seed/verification-before-completion/SKILL.md` | `skills/verification-before-completion/SKILL.md` |
| `skills/archive/executing-plans/SKILL.md` | `skills/executing-plans/SKILL.md` |
| `skills/archive/systematic-debugging/SKILL.md` | `skills/systematic-debugging/SKILL.md` |
| `skills/archive/test-driven-development/SKILL.md` | `skills/test-driven-development/SKILL.md` |
| `skills/archive/writing-plans/SKILL.md` | `skills/writing-plans/SKILL.md` |
| `skills/archive/writing-skills/SKILL.md` | `skills/writing-skills/SKILL.md` |

部分技能目錄另含上游隨附的輔助檔（`.md` 說明與 `.sh` 腳本），一併適用本節授權。

### 授權全文

```
MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. everything-claude-code — 5 個檔案

| | |
|---|---|
| **上游** | https://github.com/affaan-m/everything-claude-code |
| **授權** | MIT |
| **著作權聲明** | `Copyright (c) 2026 Affaan Mustafa` |
| **取得版本** | `v1.9.0-354-g401966b` |

| 本專案路徑 | 上游路徑 |
|---|---|
| `skills/active/seed/api-design/SKILL.md` | `.agents/skills/api-design/SKILL.md` |
| `skills/active/seed/architecture-decision-records/SKILL.md` | `docs/zh-CN/skills/architecture-decision-records/SKILL.md` |
| `skills/archive/agentic-engineering/SKILL.md` | `.kiro/skills/agentic-engineering/SKILL.md` |
| `skills/archive/ai-regression-testing/SKILL.md` | `docs/zh-CN/skills/ai-regression-testing/SKILL.md` |
| `skills/archive/coding-standards/SKILL.md` | `.agents/skills/coding-standards/SKILL.md` |

上游把同一組技能鏡射在 `.agents/skills/`、`.kiro/skills/` 與多個
`docs/<locale>/skills/` 底下，內容不完全一致。上表列的是本專案實際取用的那一份。

### 授權全文

```
MIT License

Copyright (c) 2026 Affaan Mustafa

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 3. cytoscape.js — demo 前端

| | |
|---|---|
| **上游** | http://js.cytoscape.org |
| **授權** | MIT |
| **版本** | 3.34.3 |
| **檔案** | `demo/vendor/cytoscape.min.js` |

授權全文隨附於 [`demo/vendor/cytoscape-LICENSE.txt`](demo/vendor/cytoscape-LICENSE.txt)。
這是 demo 唯一的第三方前端相依，已 vendored 進 repo、未使用 CDN。

---

## 修改說明

13 個種子技能都經過改寫，不是原樣複製。主要改動是套上本專案的 SKILL.md
frontmatter schema（論文 Definition 2 的 `tier` / `utility` / `frequency` /
`reinforcement` / `cost` / `domain` / `type` / `linked_nodes` 等欄位），
供演化引擎讀取；部分技能的正文亦經裁剪與調整。上游的 `author` 欄位改為
`superpowers-seed` / `ECC-seed` 以標示來源批次。
