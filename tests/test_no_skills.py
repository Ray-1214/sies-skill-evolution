"""A no-skills control must still plan, execute, reflect, and emit its outcome."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.agent_runner import AgentRunner
from memory_planner import MemoryPlanner
from parse_graph_index import graph_to_index_md


def test_no_skills_preserves_pipeline_without_retrieval(tmp_path, monkeypatch):
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    cfg["system"].update(project_root=str(tmp_path), trace_dir=str(tmp_path / "episodic"))
    config = tmp_path / "config.codex.yaml"
    config.write_text(yaml.safe_dump(cfg))
    (tmp_path / "skills").mkdir()
    graph_to_index_md(nx.DiGraph(), str(tmp_path / "skills/GRAPH_INDEX.md"))
    def forbidden(*a, **kw):
        raise AssertionError("no-skills must not query embeddings or read skills")
    engine = SimpleNamespace(embed_text=forbidden)
    store = SimpleNamespace(query=forbidden)
    planner = MemoryPlanner(str(config), engine, store, no_skills=True)
    monkeypatch.setattr(planner, "_read_skill_detail", forbidden)
    observed = {"plans": 0, "execution": 0, "reflection": 0}
    def plan(tstruct, wm):
        observed["plans"] += 1
        assert "可用技能" not in wm
        return '{"steps": [{"skill_used": "none", "skill_source": "none"}]}'
    monkeypatch.setattr(planner, "_generate_plan", plan)
    runner = AgentRunner(str(config), no_skills=True)
    runner._planner = planner
    runner._decomposer = SimpleNamespace(decompose=lambda task: {
        "task_id": task, "requirements_restatement": task, "subtasks": []})
    def execute(**kw):
        observed["execution"] += 1
        return {"success": True, "total_steps": 1,
                "trace": [{"action": "finish", "success": True}]}
    def reflect(**kw):
        observed["reflection"] += 1
        assert kw["write_candidates"] is True
        return SimpleNamespace(validated_candidates=[], rejected_candidates=[])
    runner._agent = SimpleNamespace(run=execute)
    runner._evaluator = SimpleNamespace(evaluate=reflect)
    for i in range(3):
        result = runner.run(f"control-{i}")
        assert result.pipeline_success and result.execution_success
        assert result.verified_success is None
        assert result.skills_used == result.plan_result["selected_skills"] == []
    records = [json.loads(l) for l in (tmp_path / "episodic/run_summary.jsonl").read_text().splitlines()]
    assert len(records) == 3
    assert all(r["skills_used"] == [] and r["no_skills"] for r in records)
    assert observed == {"plans": 3, "execution": 3, "reflection": 3}


def test_normal_retrieval_and_legacy_zero_top_k(tmp_path):
    planner = MemoryPlanner.__new__(MemoryPlanner)
    planner.config = {"planner": {"top_k": 6}}
    planner.no_skills = False
    planner.graph = nx.DiGraph()
    planner.centrality = {}
    calls = []
    planner.engine = SimpleNamespace(embed_text=lambda text: calls.append(text) or [1])
    planner.store = SimpleNamespace(query=lambda *a, **kw: [
        {"name": "existing", "path": "skills/active/existing/SKILL.md", "score": 0.1}])
    assert planner._select_top_k("task")[0]["name"] == "existing"
    planner.config["planner"]["top_k"] = 0
    assert planner._select_top_k("no query") == []
    assert calls == ["task"]
