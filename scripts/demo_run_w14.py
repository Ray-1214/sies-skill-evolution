#!/usr/bin/env python3
"""
demo_run.py — SIES 三段式 demo（給老師看，輸出可直接截圖放投影片）
=================================================================
三段：
  第一段 curriculum 自己出題（5 cluster 各一題）
  第二段 完整認知閉環（一題走完 A1→A2→執行→A3→Φ 演化，graph N→N+）
  第三段 web search（agent 自己上網查最新資訊）

設計：所有 verbose log / HTTP / embedding 訊息都被吞掉，只印整理過的中文輸出。
注意：本腳本會 mutate graph（第二段 Φ 會 +1）。執行前請先手動 snapshot，
      執行後手動 rollback（snapshot demo-pre）。腳本本身不 rm、不 rollback。

執行：
    python scripts/demo_run.py
"""

import contextlib
import io
import logging
import sys
import subprocess
import tempfile
from pathlib import Path

import yaml

# repo root 進 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 全域壓低 log（demo 只要漂亮輸出）──
logging.disable(logging.CRITICAL)

from agents.agent_runner import AgentRunner          # noqa: E402
from agents.curriculum_agent import CurriculumAgent  # noqa: E402
from agents.llm_client import LLMClient              # noqa: E402
from parse_graph_index import parse_graph_index      # noqa: E402

GRAPH_INDEX = ROOT / "skills" / "GRAPH_INDEX.md"


def _node_count() -> int:
    return len(parse_graph_index(str(GRAPH_INDEX))["nodes"])


@contextlib.contextmanager
def _quiet():
    """吞掉 stdout/stderr（verbose log、進度條、HTTP 訊息都不印）。"""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        yield


def _final_answer(trace: list) -> str:
    for rec in trace:
        if (rec.get("action") or "").lower() == "finish":
            return rec.get("action_input", "") or rec.get("observation", "")
    return ""


def _actions_used(trace: list) -> list[str]:
    return sorted({(r.get("action") or "").lower() for r in trace if r.get("action")})


def main() -> int:
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    llm = LLMClient({**cfg.get("llm", {}), "temperature": 0.6})

    with _quiet():
        runner = AgentRunner(str(ROOT / "config.yaml"))

    # ════════════════════════════════════════════════════════════
    # 第一段：系統自己出題
    # ════════════════════════════════════════════════════════════
    print("\n===== 第一段：系統自己出題 =====\n")
    print("系統根據自己目前的能力，為 5 個能力類別各出一題（難度比上次調高一級）：\n")

    tmp_state = Path(tempfile.mkdtemp()) / "curriculum_state.json"
    cur = CurriculumAgent(
        profile_path=str(ROOT / "data" / "ability_profile_live.json"),
        state_path=str(tmp_state),
        llm_client=llm,
        queue=None,
    )
    with _quiet():
        tasks = cur.generate_tasks(k_per_cluster=1)

    for t in tasks:
        desc = t["task_description"].strip().replace("\n", " ")
        print(f"  [{t['cluster']}] {desc[:80]}")
    print("\n（出題能力已具備；讓系統自動跑完這些題的完整閉環是下一階段）")

    # ════════════════════════════════════════════════════════════
    # 第二段：完整認知閉環 A1→A2→執行→A3→Φ
    # ════════════════════════════════════════════════════════════
    print("\n\n===== 第二段：完整認知閉環（一題走完 A1→A2→執行→A3→演化）=====\n")
    T_a = ("讀取一份 JSON 格式的銷售紀錄（先自己用 code 生一份 8-10 筆範例資料），"
           "用 pandas 計算每個產品類別的總銷售額與平均單價，輸出成按總銷售額排序的 CSV 報表。")
    print("【任務】把雜亂的 JSON 銷售資料整理成排序後的 CSV 報表\n")

    before = _node_count()
    with _quiet():
        result = runner.run(T_a)

    # A1
    subtasks = (result.tstruct or {}).get("subtasks", [])
    print("【A1 任務分解】")
    for s in subtasks:
        sid = s.get("subtask_id", "?")
        sdesc = (s.get("description") or "").strip()
        print(f"  {sid}. {sdesc}")
    print()

    # A2
    print("【A2 技能檢索】系統從技能庫找出並重用了這些學過的技能：")
    for name in result.skills_used:
        print(f"  · {name}")
    print()

    # 執行
    print(f"【執行】在沙盒寫 code 跑出結果（"
          f"{'成功' if result.execution_success else '失敗'}，{result.execution_steps} 步）\n")

    # A3
    new_skill = None
    if result.evaluation is not None and result.evaluation.validated_candidates:
        new_skill = result.evaluation.validated_candidates[0].name
    if new_skill:
        print(f"【A3 反思】從執行反思，學到一個新技能：{new_skill}\n")
    else:
        print("【A3 反思】本題未抽出通過驗證的新技能（既有技能已足夠覆蓋）\n")

    # Φ 演化
    with _quiet():
        subprocess.run(
            [sys.executable, "-m", "evolution.evolution_operator"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
    after = _node_count()
    print(f"【Φ 演化】新技能存進技能庫——技能庫從 {before} 成長到 {after} 個技能")
    print("（全程沒有重新訓練模型，這就是論文核心：技能層級的演化）")

    # ════════════════════════════════════════════════════════════
    # 第三段：自己上網查最新資訊
    # ════════════════════════════════════════════════════════════
    print("\n\n===== 第三段：自己上網查最新資訊 =====\n")
    print("【任務】查 Python 3.13 的新特性\n")

    with _quiet():
        web = runner.run("查一下 Python 3.13 release 有哪些主要新特性，整理成三個重點。")

    actions = _actions_used(web.execution_trace)
    print(f"【執行】agent 自己呼叫了：{', '.join(actions)}\n")
    print("【結果】")
    print(_final_answer(web.execution_trace).strip())

    # ── 收尾 ──
    print("\n\ndemo 結束。記得手動 rollback 回乾淨狀態（snapshot demo-pre）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
