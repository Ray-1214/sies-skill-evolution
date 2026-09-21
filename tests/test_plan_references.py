"""Plan claims are additive observations, never replacements for retrieval history."""
import json
from types import SimpleNamespace

import pytest
import yaml

from agents.agent_runner import AgentRunner, RunResult


@pytest.mark.parametrize("raw, expected", [
    ('{"steps":[{"skill_used":"a"},{"skill_used":"a"},{"skill_used":"b"},{"skill_used":"none"}]}', ["a", "b"]),
    ('<think>ignore</think>\n```json\n{"steps": [{"skill_used":"a"}]}\n```', ["a"]),
    ('Here is the plan: {"steps": []} done.', []),
    ('{"steps": [{"skill_used": null}]}', []),
    ('broken JSON', None), ('{"steps": [3]}', None),
    ('{"steps": [{"action": "missing citation"}]}', None),
    ('{"steps": [{"skill_used": ["a"]}]}', None),
    ('[]', None), ('null', None), (None, None),
])
def test_tolerant_parse_and_schema(raw, expected):
    result = RunResult(task="t", task_id="t", skills_used=["retrieved"])
    AgentRunner._record_plan(result, raw)
    assert result.skills_referenced == expected
    assert result.plan_parse_success is (expected is not None)
    assert result.skills_used == ["retrieved"]


def test_malformed_plan_does_not_abort_and_a2_failure_is_logged(tmp_path):
    cfg = tmp_path / "config.codex.yaml"
    cfg.write_text(yaml.safe_dump({"system": {"trace_dir": str(tmp_path / "episodic")}}))
    runner = AgentRunner(str(cfg))
    runner._decomposer = SimpleNamespace(decompose=lambda task: {"task_id": task})
    runner._planner = SimpleNamespace(plan=lambda task: {
        "selected_skills": [{"name": f"s{i}"} for i in range(6)],
        "execution_plan": "invalid JSON", "working_memory": "context"})
    calls = []
    runner._agent = SimpleNamespace(run=lambda **kw: calls.append(kw) or {
        "success": True, "trace": [{"action": "finish", "success": True}], "total_steps": 1})
    runner._evaluator = SimpleNamespace(evaluate=lambda **kw: SimpleNamespace(
        validated_candidates=[], rejected_candidates=[]))
    malformed = runner.run("malformed")
    assert malformed.pipeline_success and malformed.execution_success
    assert malformed.skills_referenced is None
    def fail(task):
        raise RuntimeError("A2 unavailable")
    runner._planner.plan = fail
    aborted = runner.run("a2-failed")
    assert aborted.error_stage == "a2_plan" and not aborted.pipeline_success
    assert len(calls) == 1
    rows = [json.loads(line) for line in (tmp_path / "episodic/run_summary.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["execution_plan_raw"] == "invalid JSON"
    assert rows[0]["skills_used"] == [f"s{i}" for i in range(6)]
    assert rows[0]["skills_referenced"] is None
    stats = AgentRunner.summarize_results([malformed, aborted])
    assert stats["plan_parse_attempts"] == 1 and stats["plan_parse_rate"] == 0


def test_actual_reads_are_persisted_separately_from_retrieval(tmp_path):
    cfg = tmp_path / "config.codex.yaml"
    cfg.write_text(yaml.safe_dump({"system": {"trace_dir": str(tmp_path / "episodic")}}))
    runner = AgentRunner(str(cfg), linked_memory=True)
    runner._decomposer = SimpleNamespace(decompose=lambda task: {"task_id": task})
    runner._planner = SimpleNamespace(plan=lambda task: {
        "selected_skills": [{"name": "retrieved"}], "working_memory": "context",
        "execution_plan": '{"steps":[{"skill_used":"planned"}]}'})
    events = [{"id": "skill:read", "offset": 0, "chars": 40},
              {"id": "skill:read", "offset": 40, "chars": 20},
              {"id": "note:personal", "offset": 0, "chars": 10}]
    runner._agent = SimpleNamespace(run=lambda **kw: {
        "success": True, "trace": [], "total_steps": 4, "memory_reads": events})
    runner._evaluator = SimpleNamespace(evaluate=lambda **kw: SimpleNamespace(
        validated_candidates=[], rejected_candidates=[]))
    result = runner.run("read-observations")
    assert result.pipeline_success
    row = json.loads((tmp_path / "episodic/run_summary.jsonl").read_text())
    assert row["skills_used"] == ["retrieved"]
    assert row["skills_referenced"] == ["planned"]
    assert row["skills_read"] == ["read"]
    assert row["memory_reads"] == events
