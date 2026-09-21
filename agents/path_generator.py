"""
path_generator.py — 方向 → 學習路徑（P5-a）
============================================
給一句方向（「學會做簡報」），產出 5-10 個由淺到深的子任務，**每題自帶
可執行的驗證**。這是 demo 的開場（§2.2 條件 E），也是 P3-5 provenance 邊
的資料來源。

## 為什麼是四元組而不是「叫 LLM 順便寫個 verifier」

P5-0 量到 33% 捏造率，而其中 G2 編出來的 `COLLISION=20` 正好落在手寫 verifier
的合理區間內 —— **LLM 生的檢查會有洞**。再叫同一個 LLM 生 verifier 只是把洞
往上移一層。

所以出題器產的是：

    task_description   給 agent 看的題目
    input_files        harness 先放進 workdir 的已知輸入
    reference_solution 由 harness 在沙箱裡**執行**，用它產生的產物推導 expected
    oracle             生成器的**意圖**（實際強度由 verify_runner.compute_status
                       從跑過的 kind 算出，不採信這個欄位）

LLM 不負責「算出正解」（它在腦中算 10.75 會偶爾錯，而錯的 expected 產生的是
false negative —— 跟捏造相反方向的污染），只負責「寫一份參考解」。附帶好處：
參考解跑不起來的題，在送到 agent 之前就被淘汰，免費的品質過濾。

## 兩階段

一次要本機 26B 吐出完整四元組不可靠，拆成：
  Stage A  方向 → 5-10 題大綱（description / cluster / domain / level）
  Stage B  逐題 → input_files + reference_solution + expected 樣板

## 後處理硬保證（不靠 LLM 自律）

  - level 單調不減（依 level 穩定排序後重編）
  - path_pos 連續 0..n-1
  - level 夾在 [1, CurriculumAgent.level_cap(cluster)]
  - 參考解跑不起來的題直接淘汰
"""

import json
import logging
import pathlib
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agents.base_extractor import strip_think          # noqa: E402
from agents.curriculum_agent import CLUSTER_PROFILES, CurriculumAgent  # noqa: E402

logger = logging.getLogger(__name__)

MIN_STEPS, MAX_STEPS = 5, 10
# 跟 LLM 多要幾題，因為參考解跑不起來的會被淘汰（實測第一次跑就掉了 1/5）
OUTLINE_ASK = (7, 10)

# [P5-a] check kind **由副檔名推導，不採信生成器自報**。
# 跟 verification_status 同一個道理：實測第一次跑，LLM 把 .json 輸出全部標成
# run_capture（那個 kind 需要 pattern，會在檢查時直接失敗）。
_KIND_BY_EXT = {
    ".json": "json_equals",
    ".csv": "csv_column",
    ".pptx": "pptx_outline",
    ".py": "run_capture",
}


def kind_for(output_file: str, hint: str | None = None) -> str:
    """副檔名優先；沒對到的才退回生成器的建議，再退回 file_exists。"""
    ext = pathlib.PurePosixPath(output_file).suffix.lower()
    if ext in _KIND_BY_EXT:
        return _KIND_BY_EXT[ext]
    if hint in ("json_equals", "csv_column", "pptx_outline", "run_capture"):
        return hint
    return "file_exists"

_CLUSTER_HINT = "\n".join(
    f"  {c}: {p['theme']}" for c, p in CLUSTER_PROFILES.items()
)

OUTLINE_SYSTEM = (
    "You design short learning curricula for a coding agent. "
    "You output ONLY a JSON array, no prose, no markdown fences."
)

OUTLINE_USER = """Design a learning path of {lo}-{hi} subtasks that teaches an AI coding agent
the direction: "{direction}"

Rules:
- Order them from simplest to hardest. Each step should build on the previous one.
- Every subtask must be solvable by writing and running a Python program in a sandbox
  that has: pandas, numpy, requests, beautifulsoup4, matplotlib, python-pptx, pygame, pillow.
- Every subtask must read at least one INPUT FILE that will be placed in its working
  directory, and must WRITE at least one OUTPUT FILE. This is mandatory: a task whose
  answer does not depend on an input file cannot be verified.
- Phrase each task as "read <input file> ... write <output file> ... then print exactly
  one line: KEY=<value>". Do NOT phrase it as "write a program at <path> and run it".
- Assign each subtask a capability cluster:
{clusters}
- Assign a difficulty level 1-{maxlevel}, non-decreasing along the path.

Output a JSON array of objects with exactly these keys:
  "title"        short slug, kebab-case
  "description"  the task text the agent will receive
  "cluster"      one of C1..C5
  "level"        integer
  "input_file"   the filename the task reads (e.g. "sales.csv")
  "output_file"  the filename the task writes (e.g. "report.json")
"""

DETAIL_SYSTEM = (
    "You write reference solutions and test fixtures for coding tasks. "
    "You output ONLY a JSON object, no prose, no markdown fences."
)

DETAIL_USER = """Here is a coding task that will be given to an AI agent:

{description}

It reads "{input_file}" from its working directory and writes "{output_file}".

Produce a JSON object with exactly these keys:

"input_files": an object mapping "{input_file}" to its full literal content as a string.
    Make the data small (4-8 rows) but non-trivial, and make sure the correct answer
    genuinely depends on these values.

"reference_solution": a complete standalone Python program, as a single string, that
    solves the task correctly. It runs with the working directory set to where the
    input file is, reads "{input_file}", writes "{output_file}", and prints the required
    line. Use only the standard library plus pandas/numpy/python-pptx/pygame if needed.
    Do NOT hardcode the answer — compute it from the input file.

"expected_kind": one of "json_equals" (if the output file is JSON),
    "csv_column" (if it is CSV), "pptx_outline" (if it is .pptx),
    "run_capture" (if the output file is a .py program that must be executed).

"expected_column": ONLY if expected_kind is "csv_column" — the name of the numeric
    column whose values must match. Otherwise null.
"""


class PathGenerator:
    """方向 → 學習路徑（四元組）。"""

    def __init__(self, llm_client, domain: str = "general"):
        self.llm = llm_client
        self.domain = domain

    # ── LLM 呼叫與解析 ──────────────────────────────────────────

    @staticmethod
    def _json_from(text: str, want: type = dict):
        """LLM 常常包 markdown fence 或前後多話，抽出想要的那個 JSON 值。

        `want` 是必要的：細節回應裡若同時出現 array 與 object，盲抓第一個
        會拿錯型別（實測第一次跑就踩到）。
        """
        t = strip_think(text).strip()
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.M).strip()
        order = ((("[", "]"), ("{", "}")) if want is list
                 else (("{", "}"), ("[", "]")))
        for opener, closer in order:
            i, j = t.find(opener), t.rfind(closer)
            if i != -1 and j > i:
                try:
                    v = json.loads(t[i:j + 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(v, want):
                    return v
        raise ValueError(f"回應裡找不到 {want.__name__}: {t[:200]}")

    def _outline(self, direction: str) -> list[dict]:
        maxlevel = max(CurriculumAgent.level_cap(c) for c in CLUSTER_PROFILES)
        msg = OUTLINE_USER.format(direction=direction, lo=OUTLINE_ASK[0], hi=OUTLINE_ASK[1],
                                  clusters=_CLUSTER_HINT, maxlevel=maxlevel)
        raw = self.llm.chat(OUTLINE_SYSTEM, msg).content
        return self._json_from(raw, want=list)

    def _detail(self, step: dict) -> dict:
        msg = DETAIL_USER.format(description=step["description"],
                                 input_file=step["input_file"],
                                 output_file=step["output_file"])
        raw = self.llm.chat(DETAIL_SYSTEM, msg).content
        d = self._json_from(raw, want=dict)
        if not isinstance(d.get("input_files"), dict) or not d.get("reference_solution"):
            raise ValueError("細節回應缺 input_files 或 reference_solution")
        return d

    # ── 後處理硬保證 ────────────────────────────────────────────

    @staticmethod
    def _normalise(steps: list[dict], path_id: str, domain: str) -> list[dict]:
        """level 夾制 + 單調不減 + path_pos 連續。不靠 LLM 自律。"""
        clean = []
        for s in steps:
            c = s.get("cluster")
            if c not in CLUSTER_PROFILES:
                c = "C2"                      # 落到最通用的資料處理群
            lvl = int(s.get("level", 1) or 1)
            lvl = max(1, min(CurriculumAgent.level_cap(c), lvl))
            clean.append({**s, "cluster": c, "level": lvl})
        # 依 level 穩定排序（同 level 保持 LLM 給的順序），再讓 level 單調不減
        clean.sort(key=lambda x: x["level"])
        prev = 0
        for i, s in enumerate(clean):
            s["level"] = max(s["level"], prev)
            prev = s["level"]
            s["path_id"] = path_id
            s["path_pos"] = i
            s["domain"] = s.get("domain") or domain
            s["mode"] = "focus"
            s["parent_task_id"] = clean[i - 1].get("task_id") if i else None
        return clean

    # ── 主流程 ──────────────────────────────────────────────────

    def generate(self, direction: str, path_id: str = "p001",
                 derive: bool = True, workdir_prefix: str = "/tmp/p5a") -> list[dict]:
        """
        回傳四元組清單。derive=True 時在沙箱跑 reference_solution 推導 expected，
        跑不起來的題**直接淘汰**（免費的品質過濾）。
        """
        outline = self._outline(direction)
        logger.info(f"[PathGenerator] 大綱 {len(outline)} 題")

        quads = []
        for i, step in enumerate(outline[:MAX_STEPS]):
            for key in ("description", "input_file", "output_file"):
                if not step.get(key):
                    logger.warning(f"[PathGenerator] 第 {i} 題缺 {key}，跳過")
                    break
            else:
                try:
                    d = self._detail(step)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[PathGenerator] 第 {i} 題細節生成失敗: {e}")
                    continue
                kind = kind_for(step["output_file"], d.get("expected_kind"))
                spec = {"kind": kind, "from_reference": True}
                if kind == "csv_column":
                    spec["column"] = d.get("expected_column") or "value"
                    spec["tol"] = 0.011
                elif kind == "json_equals":
                    spec["tol"] = 0.01
                quads.append({
                    "task_id": f"{path_id}-{i:02d}",
                    "title": step.get("title") or f"step-{i}",
                    "task_description": step["description"],
                    "cluster": step["cluster"], "level": step.get("level", 1),
                    "input_files": d.get("input_files") or {},
                    "reference_solution": d.get("reference_solution") or "",
                    "expected": {step["output_file"]: spec},
                    "oracle": ("verified_independent"
                               if kind in ("json_equals", "csv_column")
                               else "verified_liveness"),
                })

        quads = self._normalise(quads, path_id, self.domain)

        if derive:
            from verify_runner import derive_expected
            kept = []
            for q in quads:
                exp, why = derive_expected(q, f"{workdir_prefix}_{q['task_id']}")
                if exp is None:
                    logger.warning(f"[PathGenerator] {q['task_id']} 參考解跑不起來，"
                                   f"淘汰：{why}")
                    continue
                q["expected"] = exp
                kept.append(q)
            quads = self._normalise(kept, path_id, self.domain)

        return quads
