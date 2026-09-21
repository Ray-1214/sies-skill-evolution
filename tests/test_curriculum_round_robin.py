import json
from types import SimpleNamespace

import pytest

from agents.curriculum_agent import CurriculumAgent, CLUSTER_PROFILES


def agent_at(root, llm):
    profile = root / "profile.json"
    profile.write_text(json.dumps({"frontier_signal": {
        "too_easy": ["C1"], "too_hard": ["C2"], "insufficient_data": ["C3", "C4", "C5"]}}))
    return CurriculumAgent(str(profile), str(root / "state.json"), llm)


def test_round_robin_order_caps_and_legacy_state(tmp_path):
    calls = []
    llm = SimpleNamespace(chat=lambda *a: SimpleNamespace(content=f"Valid unique task description number {len(calls)}"))
    agent = agent_at(tmp_path, llm)
    original = agent._gen_task_for_cluster
    def generate(c, l):
        calls.append((c, l))
        return original(c, l)
    agent._gen_task_for_cluster = generate
    agent._save_state({c: {"level": agent.level_cap(c)} for c in CLUSTER_PROFILES})
    tasks = agent.generate_tasks(2)
    assert [t["cluster"] for t in tasks] == list(CLUSTER_PROFILES) * 2
    assert {c: l for c, l in calls} == {"C1": 4, "C2": 3, "C3": 4, "C4": 5, "C5": 6}
    assert json.loads(agent.state_path.read_text())["_round_robin_next"] == 0


def test_restart_resumes_at_unfinished_cluster(tmp_path):
    agent = agent_at(tmp_path, None)
    def generate(c, l):
        if c == "C4":
            raise RuntimeError("model unavailable")
        return f"A valid long task description for cluster {c}"
    agent._gen_task_for_cluster = generate
    with pytest.raises(RuntimeError):
        agent.generate_tasks()
    restarted = agent_at(tmp_path, None)
    restarted._gen_task_for_cluster = lambda c,l: f"Another valid long task description for {c}"
    assert [t["cluster"] for t in restarted.generate_tasks()] == ["C4", "C5", "C1", "C2", "C3"]


def test_invalid_response_never_enqueues(tmp_path):
    enqueued = []
    agent = agent_at(tmp_path, SimpleNamespace(chat=lambda *a: SimpleNamespace(content="")))
    agent.queue = SimpleNamespace(enqueue=lambda *a, **kw: enqueued.append(a))
    with pytest.raises(ValueError):
        agent.generate_tasks()
    assert not enqueued
