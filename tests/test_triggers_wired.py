"""Exercise both scheduling entry points and persisted reasons without an LLM."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.agent_runner import RunResult
from evolution.evolution_operator import EvolutionOperator
from evolution.evolution_triggers import EvolutionTriggers, evolution_decision
from parse_graph_index import graph_to_index_md


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    cfg["system"].update(project_root=str(tmp_path), trace_dir=str(tmp_path / "episodic"))
    path = tmp_path / "config.codex.yaml"
    path.write_text(yaml.safe_dump(cfg))
    (tmp_path / "episodic").mkdir()
    (tmp_path / "skills").mkdir()
    graph_to_index_md(nx.DiGraph(), "skills/GRAPH_INDEX.md")
    return path


def write_records(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def operator_without_transformations(config, monkeypatch):
    """Keep real graph/report IO; scheduling tests do not test Φ's four stages."""
    op = EvolutionOperator(str(config))
    monkeypatch.setattr(op, "_step_i_utility_evaluation", lambda *a: ([], []))
    monkeypatch.setattr(op, "_step_ii_skill_insertion", lambda *a: ([], []))
    monkeypatch.setattr(op, "_step_iii_subgraph_contraction", lambda *a: [])
    monkeypatch.setattr(op, "_step_iv_tier_migration", lambda *a: [])
    return op


def test_t1_and_periodic_reason_are_both_retained(isolated):
    decision = evolution_decision(EvolutionTriggers(str(isolated)),
                                  RunResult("failure", "t1"), 10, 10)
    assert decision.t1_fired
    assert decision.reasons == ["T1: task failed", "periodic: every 10 tasks"]


def test_t2_uses_ten_previous_runs_not_current_result(isolated):
    records = [{"task_id": f"t{i}", "timestamp": f"{i:03d}", "total_steps": 2}
               for i in range(10)]
    records.append({"task_id": "current", "timestamp": "010", "total_steps": 3})
    write_records(isolated.parent / "episodic/run_summary.jsonl", records)
    result = RunResult("long", "current", execution_success=True, execution_steps=3)
    decision = EvolutionTriggers(str(isolated)).should_trigger(result)
    assert decision.t2_fired and decision.t2_window_size == 10
    assert decision.t2_moving_avg == decision.t2_threshold == 2


@pytest.mark.parametrize("count, expected", [(3, False), (4, True)])
def test_t3_strict_threshold_and_summary_is_not_a_trace(isolated, count, expected):
    directory = isolated.parent / "episodic"
    for i in range(10):
        actions = ["code_execution", "finish"] if i < count else [f"unique_{i}"]
        write_records(directory / f"T-{i}.jsonl",
                      [{"action": a, "success": True} for a in actions])
    write_records(directory / "run_summary.jsonl", [{"total_steps": 2}] * 20)
    write_records(directory / "evolution_log.jsonl", [{"triggered_by": ["force"]}])
    assert EvolutionTriggers(str(isolated)).check_t3() is expected


def test_no_trigger_and_periodic_only(isolated):
    triggers = EvolutionTriggers(str(isolated))
    result = RunResult("ok", "t", execution_success=True, execution_steps=2)
    assert not evolution_decision(triggers, result, 1, 10).triggered
    decision = evolution_decision(triggers, result, 10, 10)
    assert decision.reasons == ["periodic: every 10 tasks"]
    with pytest.raises(ValueError):
        evolution_decision(triggers, result, 1, 0)


def test_curriculum_loop_persists_automatic_reason(isolated, monkeypatch):
    from agents import curriculum_loop as mod
    from agents.task_queue import TaskQueue

    op = operator_without_transformations(isolated, monkeypatch)
    monkeypatch.setattr(mod, "EvolutionOperator", lambda *a: op)
    result = RunResult("fail", "failed-task", execution_steps=2)
    planner = SimpleNamespace(reload_graph=lambda: None, graph=nx.DiGraph())
    monkeypatch.setattr(mod, "AgentRunner", lambda *a: SimpleNamespace(
        run=lambda *a, **kw: result, planner=planner))
    loop = mod.CurriculumLoop(str(isolated))
    # Use the real queue and run loop, with one failing task and a periodic interval of 10.
    loop.queue.enqueue(source="user", task_description="test failure")
    loop.run(max_tasks=1)
    records = [json.loads(line) for line in
               (isolated.parent / "episodic/evolution_log.jsonl").read_text().splitlines()]
    assert len(records) == 1 and records[0]["triggered_by"] == ["T1: task failed"]


def test_w16_main_wires_triggers_and_final_does_not_evolve_twice(isolated, monkeypatch):
    from scripts import w16_run as mod
    import agents.agent_runner as runner_mod
    import evolution.evolution_operator as phi_mod
    import verify_runner

    op = operator_without_transformations(isolated, monkeypatch)
    monkeypatch.setattr(phi_mod, "EvolutionOperator", lambda *a: op)
    monkeypatch.setattr(mod, "ROOT", isolated.parent)
    monkeypatch.setattr(mod, "RUNS", isolated.parent / "runs")
    monkeypatch.setattr(mod, "LOCK", isolated.parent / "run.lock")
    # Test doubles retain lock artifacts; no cleanup/deletion of any fixture files.
    monkeypatch.setattr(mod.RunLock, "__enter__", lambda self: self)
    monkeypatch.setattr(mod.RunLock, "__exit__", lambda *a: None)
    monkeypatch.setattr(mod, "clean_tmp", lambda: (0, 0))
    monkeypatch.setattr(mod, "integrity", lambda: {"consistent": True})
    monkeypatch.setattr(mod, "_shared_engine", lambda *a: None)
    monkeypatch.setattr(mod, "_shared_store", lambda *a: None)
    monkeypatch.setattr(verify_runner, "derive_expected", lambda *a: ({}, "test"))
    result = RunResult("fail", "t", execution_steps=2)
    planner = SimpleNamespace(reload_graph=lambda: None, graph=nx.DiGraph())
    fake = SimpleNamespace(run=lambda *a, **kw: result, planner=planner)
    # Replace the module binding: patching object.__new__ changes CPython's type
    # allocation slot even after monkeypatch restores it, leaking across tests.
    monkeypatch.setattr(runner_mod, "AgentRunner", lambda *a, **kw: fake)
    taskset = isolated.parent / "tasks.json"
    taskset.write_text(json.dumps([{"task_id": "t", "task_description": "fail"}]))
    monkeypatch.setattr(sys, "argv", ["w16_run.py", "--direction", "test", "--tasks", "1",
                                     "--taskset", str(taskset), "--config", str(isolated),
                                     "--run-id", "test-trigger"])
    assert mod.main() == 0
    records = [json.loads(line) for line in
               (isolated.parent / "episodic/evolution_log.jsonl").read_text().splitlines()]
    assert len(records) == 1 and records[0]["triggered_by"] == ["T1: task failed"]
    ck = json.loads((mod.RUNS / "test-trigger/checkpoints/001.json").read_text())
    assert ck["phi"]["triggered_by"] == ["T1: task failed"]
    assert (mod.RUNS / "test-trigger/checkpoints/001_final.json").exists()
