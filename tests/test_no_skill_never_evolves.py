"""對照組（--no-skill）在任何情況下都不得執行 Φ。

這是 2026-09-17 合併回歸的守門測試。
`pre-codex-20260914:scripts/w16_run.py:332` 原本是
    if not args.dry_run and not args.no_skill:
合併後變成
    if not args.dry_run and trigger_result is not None and trigger_result.triggered:
`no_skill` 條件被無意間拿掉。配合 T3 在真實資料上恆為真
（docs/T3_TRIGGER_RATE_20260916.md：第 1 題就觸發、50/50），
對照組會變成每題跑一次 Φ —— 那樣比較的是
「有技能庫 vs 技能庫在背景演化但用不到」，不是對照組。

做法與 tests/test_no_skills.py:25-30 相同：把不該被呼叫的東西換成
會拋 AssertionError 的 forbidden()，讓違規直接炸掉而不是靜默通過。
"""
import json
import sys
from types import SimpleNamespace

import networkx as nx
import pytest

from agents.agent_runner import RunResult
from evolution.evolution_triggers import TriggerResult
from test_triggers_wired import isolated  # noqa: F401 — pytest fixture


def _wire(isolated, monkeypatch, *, forbid_phi):
    """把 w16_run 的外部相依換成測試替身。

    forbid_phi=True 時，EvolutionOperator 一旦被建構就拋 AssertionError。
    """
    from scripts import w16_run as mod
    import agents.agent_runner as runner_mod
    import evolution.evolution_operator as phi_mod
    import verify_runner

    built = []
    if forbid_phi:
        def forbidden(*a, **kw):
            raise AssertionError(
                "對照組不得執行 Φ：--no-skill 模式下 EvolutionOperator 被建構了")
        monkeypatch.setattr(phi_mod, "EvolutionOperator", forbidden)
    else:
        op = SimpleNamespace(
            _engine=None, _store=None,
            evolve=lambda **kw: SimpleNamespace(
                inserted_skills=[], rejected_skills=[], macro_skills_created=[],
                tier_migrations=[], candidates_found=0,
                triggered_by=list(kw["trigger_result"].reasons)))
        monkeypatch.setattr(phi_mod, "EvolutionOperator",
                            lambda *a, **kw: (built.append(1), op)[1])

    monkeypatch.setattr(mod, "ROOT", isolated.parent)
    monkeypatch.setattr(mod, "RUNS", isolated.parent / "runs")
    monkeypatch.setattr(mod, "LOCK", isolated.parent / "run.lock")
    monkeypatch.setattr(mod.RunLock, "__enter__", lambda self: self)
    monkeypatch.setattr(mod.RunLock, "__exit__", lambda *a: None)
    monkeypatch.setattr(mod, "clean_tmp", lambda: (0, 0))
    monkeypatch.setattr(mod, "integrity", lambda: {"consistent": True})
    monkeypatch.setattr(mod, "_shared_engine", lambda *a: None)
    monkeypatch.setattr(mod, "_shared_store", lambda *a: None)
    monkeypatch.setattr(verify_runner, "derive_expected", lambda *a: ({}, "test"))

    # 每次都宣稱「該演化了」——測的是 no_skill 能不能擋住，不是觸發條件本身。
    # w16_run.main() 是在函式內才 import evolution_decision，所以要 patch 來源模組。
    import evolution.evolution_triggers as trig_mod
    monkeypatch.setattr(trig_mod, "evolution_decision",
                        lambda *a, **kw: TriggerResult(
                            triggered=True, reasons=["forced: test"]))

    result = RunResult("ok", "t", execution_success=True, execution_steps=2)
    planner = SimpleNamespace(reload_graph=lambda: None, graph=nx.DiGraph())
    fake = SimpleNamespace(run=lambda *a, **kw: result, planner=planner, no_skills=None)

    def make_runner(*a, **kw):
        fake.no_skills = kw.get("no_skills")
        return fake
    monkeypatch.setattr(runner_mod, "AgentRunner", make_runner)

    taskset = isolated.parent / "tasks.json"
    taskset.write_text(json.dumps([{"task_id": "t1", "task_description": "x"},
                                   {"task_id": "t2", "task_description": "y"}]))
    return mod, fake, built, taskset


def _argv(isolated, taskset, run_id, *extra):
    return ["w16_run.py", "--direction", "test", "--tasks", "2",
            "--taskset", str(taskset), "--config", str(isolated),
            "--run-id", run_id, *extra]


def test_no_skill_never_constructs_the_evolution_operator(isolated, monkeypatch):
    """--no-skill：即使 evolution_decision 每題都回 triggered=True，Φ 也不得執行。"""
    mod, fake, _, taskset = _wire(isolated, monkeypatch, forbid_phi=True)
    monkeypatch.setattr(sys, "argv", _argv(isolated, taskset, "ns", "--no-skill"))

    assert mod.main() == 0                     # forbidden() 被呼叫就會在這裡炸
    assert fake.no_skills is True              # 旗標確實傳進 AgentRunner

    run = mod.RUNS / "ns"
    # 週期性 checkpoint 整個跳過（Φ 是它唯一的副作用來源）
    assert not (run / "checkpoints/001.json").exists()
    assert not (run / "checkpoints/002.json").exists()
    # final 仍要留下：圖狀態 / 三方一致性 / 快照是對照組也需要的紀錄
    final = run / "checkpoints/002_final.json"
    assert final.exists()
    ck = json.loads(final.read_text())
    assert ck["phi"] is None, "final checkpoint 不得跑 Φ"
    assert ck["graph_before_phi"] == ck["graph_after_phi"], "對照組的圖不得改變"
    assert (run / "graph_snapshots/graph_002.md").exists()
    # 沒有演化就不該有 evolution_log
    assert not (isolated.parent / "episodic/evolution_log.jsonl").exists()


def test_skill_mode_still_evolves(isolated, monkeypatch):
    """對照：不加 --no-skill 且 triggered=True 時，Φ 確實會跑。

    沒有這一半，上面那個測試用「Φ 永遠不跑」也能通過。
    """
    mod, fake, built, taskset = _wire(isolated, monkeypatch, forbid_phi=False)
    monkeypatch.setattr(sys, "argv", _argv(isolated, taskset, "sk"))

    assert mod.main() == 0
    assert fake.no_skills is False
    assert built, "有技能庫模式下 EvolutionOperator 應該被建構"

    run = mod.RUNS / "sk"
    ck = json.loads((run / "checkpoints/001.json").read_text())
    assert ck["phi"] is not None
    assert ck["phi"]["triggered_by"] == ["forced: test"]


@pytest.mark.parametrize("flag", ["--no-skill", "--no-skills"])
def test_both_spellings_disable_evolution(isolated, monkeypatch, flag):
    """--no-skill 與 --no-skills 是同一個 dest，兩種拼法都必須擋住 Φ。"""
    mod, fake, _, taskset = _wire(isolated, monkeypatch, forbid_phi=True)
    monkeypatch.setattr(sys, "argv",
                        _argv(isolated, taskset, "ns-" + flag.strip("-"), flag))
    assert mod.main() == 0
    assert fake.no_skills is True
