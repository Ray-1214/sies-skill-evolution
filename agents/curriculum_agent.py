"""
curriculum_agent.py — 出題邏輯 (W14 子任務 2，§3.10 / Agent0 curriculum)
=========================================================================
讀 ability_profile 的 frontier_signal → 依 cluster 難度等級出題 → enqueue 進 TaskQueue。
目標：對已掌握基礎的 agent，成功率約 40-70%（有挑戰但可解，§3.10.1 難度控制）。

難度模型（level → axes 疊加）：
  每 cluster 有一組 difficulty axes（難度維度，由易到難排序）。
  level 1：純基礎題（照 example_l1 風格，不疊維度）
  level N：疊加 axes 前 (N-1) 個維度
  level-1 超過 axes 數：用全部 axes + prompt 要求自由提高規模/約束

難度等級隨表現自適應（_update_levels）：
  too_easy cluster   → level + 1
  too_hard cluster   → level - 1（floor 1）
  calibrated cluster → 不變

依賴：
  agents/llm_client.py (LLMClient, anthropic format, port 8080)
  agents/ability_profiler.py (產 data/ability_profile_{source}.json)
  agents/task_queue.py (TaskQueue, enqueue curriculum item)
"""

import json
import logging
from pathlib import Path
from typing import Optional

from agents.base_extractor import strip_think

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cluster difficulty profiles
# ---------------------------------------------------------------------------
# axis 數 3/3/3/4/5（C1..C5）；example_l1 直接抄 TASKS_50 各 cluster 第一題。

CLUSTER_PROFILES = {
    "C1": {
        "theme": "Python data-structure / algorithm implementation with tests",
        "axes": [
            "add edge-case and boundary-condition tests",
            "require O(n) or better time complexity and justify it",
            "handle invalid input gracefully with explicit error paths",
        ],
        "example_l1": "Implement a singly linked list with append, remove, and search methods. "
                      "Test all three methods with at least 3 cases each.",
    },
    "C2": {
        "theme": "data processing pipeline (file I/O + aggregation, no unit tests)",
        "axes": [
            "introduce a second data format (e.g. JSON <-> CSV conversion)",
            "add grouping / aggregation across multiple columns",
            "handle malformed rows and missing values robustly",
        ],
        "example_l1": "Write 5 rows to a CSV file at /tmp/data.csv (with a numeric second column), "
                      "then read it back and count rows where the second column is greater than 50.",
    },
    "C3": {
        "theme": "pure algorithm (no file I/O, no test harness)",
        "axes": [
            "switch from iterative to recursive (or vice versa) and compare",
            "add a non-trivial mathematical constraint or larger input range",
            "require an optimized variant (memoization / divide-and-conquer)",
        ],
        "example_l1": "Compute the factorial of 20 using iteration (no recursion). Print the result.",
    },
    "C4": {
        "theme": "system query via bash (ps / find / du / grep pipelines)",
        "axes": [
            "chain multiple commands with a pipeline (filter + sort + count)",
            "add filtering by size / time / pattern with flags",
            "format the output into a structured table or summary",
            "handle the empty-result and permission-denied cases",
        ],
        "example_l1": "List all .py files anywhere under /tmp and count them.",
    },
    "C5": {
        "theme": "text processing (regex / normalization / tokenization)",
        "axes": [
            "use a regular expression instead of simple string methods",
            "handle Unicode / mixed-case / multi-delimiter input",
            "extract structured fields (dates, emails, numbers) via patterns",
            "transform between representations (snake_case <-> camelCase, etc.)",
            "aggregate or count over the extracted tokens",
        ],
        "example_l1": 'Given the string "  hello   world   how  are   you  ", replace multiple spaces '
                      'with a single space and strip leading/trailing whitespace. Print the result.',
    },
}


def _selected_axes(cluster: str, level: int) -> tuple[list[str], bool]:
    """
    level → 疊加的 axes 清單。

    回傳 (selected_axes, overflow)：
      level 1 → ([], False)
      level N → (axes[:N-1], False)
      level-1 > len(axes) → (all axes, True)  # overflow=True 時 prompt 加「自由提高規模」
    """
    axes = CLUSTER_PROFILES[cluster]["axes"]
    want = max(0, level - 1)
    if want > len(axes):
        return list(axes), True
    return list(axes[:want]), False


# ---------------------------------------------------------------------------
# Curriculum Agent
# ---------------------------------------------------------------------------

class CurriculumAgent:
    """依 ability_profile 自適應出題，enqueue 進 TaskQueue。"""

    def __init__(
        self,
        profile_path: str = "data/ability_profile_live.json",
        state_path: str = "data/curriculum_state.json",
        llm_client=None,
        queue=None,
    ):
        self.profile_path = Path(profile_path)
        self.state_path = Path(state_path)
        self.llm = llm_client
        self.queue = queue

    # ── state ─────────────────────────────────────────────

    def _load_state(self) -> dict:
        """{cluster: {"level": int}}；檔不存在 → 全 cluster level=1。"""
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"[CurriculumAgent] bad state file {self.state_path}, resetting")
        return {c: {"level": 1} for c in CLUSTER_PROFILES}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def level_cap(cluster: str) -> int:
        """
        [P1-c] 每個 cluster 的難度上限 = len(axes) + 1。

        為什麼不是一律夾 5：`_selected_axes` 在 `level - 1 > len(axes)` 時回
        `overflow=True`，prompt 會改成「自由提高輸入規模與約束」——那是沒有結構
        的難度膨脹。C1-C3 只有 3 個 axes，夾 5 的話 level 5 早就在 overflow 分支，
        等於沒解決。上限取 len(axes)+1 才剛好用滿所有維度而不進 overflow。
          C1/C2/C3 → 4    C4 → 5    C5 → 6
        """
        return len(CLUSTER_PROFILES[cluster]["axes"]) + 1

    def _update_levels(self, frontier_signal: dict, state: dict) -> dict:
        """
        [P1-c] 難度自適應的護欄。

        too_easy → +1；too_hard → -1；calibrated → 不變；
        insufficient_data → **不動**（樣本不足不亂調，ability_profiler 已用
        MIN_SAMPLES 標好）。

        兩道夾制：
          1. level ∈ [1, level_cap(cluster)]，見 level_cap 的說明
          2. 每次呼叫最多動一級（呼叫端每 10 題 checkpoint 才呼叫一次）

        原本沒有上限：P5-0 前 74 筆 success 全 True → frontier 永遠 too_easy →
        level 單調 +1，跑 100 題會 ratchet 到 L20+，遠超過每 cluster 3-5 個 axes。
        """
        too_easy = set(frontier_signal.get("too_easy", []))
        too_hard = set(frontier_signal.get("too_hard", []))
        skip = set(frontier_signal.get("insufficient_data", []))

        for cluster in list(state):
            if cluster not in CLUSTER_PROFILES or cluster in skip:
                continue
            cur = state[cluster].get("level", 1)
            if cluster in too_easy:
                delta = 1
            elif cluster in too_hard:
                delta = -1
            else:
                delta = 0                      # calibrated 或沒出現在任何一類
            if delta:
                cap = self.level_cap(cluster)
                new = max(1, min(cap, cur + delta))   # 夾制 + 每次最多一級
                if new != cur:
                    logger.info(f"[CurriculumAgent] {cluster} level {cur} → {new} "
                                f"(cap={cap})")
                state[cluster]["level"] = new

        self._save_state(state)
        return state

    # ── task generation ──────────────────────────────────

    def _gen_task_for_cluster(self, cluster: str, level: int) -> str:
        """組 prompt 餵 llm_client，回傳生成的題目字串。"""
        prof = CLUSTER_PROFILES[cluster]
        theme = prof["theme"]
        example_l1 = prof["example_l1"]
        selected, overflow = _selected_axes(cluster, level)

        system_prompt = (
            "你是一個程式題出題者（curriculum designer）。"
            "你只輸出一道程式題的題目描述本身，用英文出題，"
            "不要輸出解答、不要前言、不要 markdown 標題。"
        )

        parts = [
            f"為以下類型出一道程式題，難度等級 {level}。",
            f"類型：{theme}",
        ]
        if selected:
            axes_block = "\n".join(f"  - {a}" for a in selected)
            parts.append(f"本題需包含這些難度維度：\n{axes_block}")
        if overflow:
            parts.append("並自由提高輸入規模與約束數，讓題目更具挑戰性。")
        parts.append(
            f"風格參考（這是 level 1 基礎題，你要出的比它難 {max(0, level - 1)} 級）：\n{example_l1}"
        )
        parts.append(
            "要求：對一個已掌握基礎的 AI agent，成功率約 40-70%（有挑戰但可解）。"
            "只輸出題目描述本身，不要解答、不要前言。"
        )
        user_message = "\n\n".join(parts)

        response = self.llm.chat(system_prompt, user_message)
        return strip_think(response.content).strip()

    def generate_tasks(self, k_per_cluster: int = 1) -> list[dict]:
        """
        讀 profile → 更新 level → C1–C5 輪流、各生 k 題 → enqueue。
        游標持久化；中途失敗後重啟，從下一個尚未完成的 cluster 繼續。
        """
        if not isinstance(k_per_cluster, int) or isinstance(k_per_cluster, bool) or k_per_cluster < 1:
            raise ValueError("k_per_cluster must be a positive integer")
        if not self.profile_path.exists():
            raise FileNotFoundError(
                f"ability profile not found: {self.profile_path}. "
                f"請先跑 agents/ability_profiler.build_profile() 產生 profile。"
            )
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        frontier_signal = profile.get("frontier_signal", {})

        state = self._load_state()
        state = self._update_levels(frontier_signal, state)

        generated: list[dict] = []
        seen: set[str] = set()

        clusters = list(CLUSTER_PROFILES)
        start = int(state.get("_round_robin_next", 0)) % len(clusters)
        for position in range(len(clusters) * k_per_cluster):
            index = (start + position) % len(clusters)
            cluster = clusters[index]
            level = state.get(cluster, {"level": 1})["level"]
            task = self._gen_task_for_cluster(cluster, level)

            # 輕量 sanity + 同輪去重（重複則重生最多 2 次）
            attempts = 0
            while (not task or len(task) <= 20 or task in seen) and attempts < 2:
                logger.warning(
                    f"[CurriculumAgent] {cluster} L{level} regen "
                    f"(empty/short/dup), attempt {attempts + 1}"
                )
                task = self._gen_task_for_cluster(cluster, level)
                attempts += 1

            if not task or len(task) <= 20 or task in seen:
                raise ValueError(f"{cluster}: no valid unique task after three attempts")
            seen.add(task)
            if self.queue is not None:
                self.queue.enqueue("curriculum", task, cluster=cluster)

            generated.append({
                "cluster": cluster,
                "level": level,
                "task_description": task,
            })
            state["_round_robin_next"] = (index + 1) % len(clusters)
            self._save_state(state)

        logger.info(f"[CurriculumAgent] generated {len(generated)} tasks")
        return generated


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def main() -> int:
    """[P5-a] CLI：方向 → 學習路徑。

    舊的 `__main__` 是 W15 的 smoke script，**沒有 argparse** —— 傳任何旗標都會
    被靜默吃掉（`--direction ... --dry-run` 看起來成功其實什麼都沒測）。
    已搬到 scripts/curriculum_smoke.py。
    """
    import argparse
    import json as _json
    import logging as _logging
    import yaml as _yaml

    ap = argparse.ArgumentParser(description="方向 → 學習路徑（四元組）")
    ap.add_argument("--direction", required=True, help='例："learn to make presentations"')
    ap.add_argument("--domain", default="general", help="presentation / game / pipeline / general")
    ap.add_argument("--path-id", default="p001")
    ap.add_argument("--out", help="寫出四元組 JSON 的路徑")
    ap.add_argument("--dry-run", action="store_true",
                    help="不在沙箱跑參考解推導 expected（快，但不做品質過濾）")
    ap.add_argument("--enqueue", action="store_true", help="同時 enqueue 進 TaskQueue")
    args = ap.parse_args()

    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    cfg = _yaml.safe_load(open("config.yaml", encoding="utf-8"))
    from agents.llm_client import LLMClient
    from agents.path_generator import PathGenerator

    llm = LLMClient({**cfg.get("llm", {}), "temperature": 0.6})
    quads = PathGenerator(llm, domain=args.domain).generate(
        args.direction, path_id=args.path_id, derive=not args.dry_run)

    print(f"\n=== 路徑「{args.direction}」共 {len(quads)} 題 ===")
    for q in quads:
        print(f"  {q['path_pos']}  L{q['level']} {q['cluster']}/{q['domain']:12s} "
              f"oracle={q['oracle']:22s} {q['title'][:40]}")
        print(f"       {q['task_description'][:110]}")

    if args.out:
        pathlib_Path = __import__("pathlib").Path
        pathlib_Path(args.out).write_text(
            _json.dumps(quads, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {args.out}")

    if args.enqueue:
        from agents.task_queue import TaskQueue
        q = TaskQueue()
        for x in quads:
            q.enqueue("curriculum", x["task_description"], cluster=x["cluster"],
                      domain=x["domain"], level=x["level"], mode=x["mode"],
                      path_id=x["path_id"], path_pos=x["path_pos"],
                      parent_task_id=x.get("parent_task_id"),
                      input_files=x["input_files"],
                      reference_solution=x["reference_solution"],
                      expected=x["expected"], oracle=x["oracle"])
        print(f"已 enqueue {len(quads)} 題")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
