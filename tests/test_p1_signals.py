"""
test_p1_signals.py — P1 訊號修復的迴歸測試
==========================================
守住三件容易靜默壞掉的事：

  P1-a  三層 success 的 schema 與 alias 相容性（五個消費者靠 `success` 這個名字）
  P1-b  profiler 依 cluster 標籤分組、不再對 TASKS_50 位置對齊（TD-27 step③）
  P1-c  難度 level 的上下夾制與 insufficient_data 護欄

這些壞掉都不會拋例外，只會讓數字悄悄變錯 —— 所以要有測試釘住。
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.ability_profiler import build_profile, MIN_SAMPLES, PER_CLUSTER_WINDOW  # noqa: E402
from agents.curriculum_agent import CurriculumAgent, CLUSTER_PROFILES, _selected_axes  # noqa: E402


def _rec(cluster, *, verified=None, status=None, legacy=False, steps=3):
    r = {"task_id": "t", "task": "NOT IN TASKS_50", "cluster": cluster,
         "skills_used": ["code-execution"], "total_steps": steps,
         "success": True, "timestamp": "2026-09-07T00:00:00+08:00"}
    if not legacy:
        r.update(execution_completed=True, pipeline_success=True,
                 verified_success=verified, verification_status=status or "not_available")
    return r


def _profile_from(records, **kw):
    p = Path(tempfile.mkdtemp()) / "rs.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                 encoding="utf-8")
    return build_profile("live", n_recent=0, path=str(p), write=False, **kw)


# ── P1-b: profiler ─────────────────────────────────────────────────

class TestProfilerTagDriven:
    """TD-27 step③：依標籤分組，不對 TASKS_50 位置對齊。"""

    def test_does_not_crash_on_non_tasks50_records(self):
        """舊版會在 `assert TASKS_50[pos].startswith(...)` 掛掉。"""
        prof = _profile_from([_rec("C3") for _ in range(MIN_SAMPLES)])
        assert prof["per_cluster"]["C3"]["attempted"] == MIN_SAMPLES

    def test_groups_by_tag_not_position(self):
        """順序打亂不影響分組結果。"""
        recs = [_rec("C1"), _rec("C5"), _rec("C1"), _rec("C5"),
                _rec("C1"), _rec("C5"), _rec("C1"), _rec("C5")]
        prof = _profile_from(recs)
        assert prof["per_cluster"]["C1"]["attempted"] == 4
        assert prof["per_cluster"]["C5"]["attempted"] == 4
        assert prof["per_cluster"]["C2"]["attempted"] == 0

    def test_null_cluster_ignored_not_miscounted(self):
        prof = _profile_from([_rec(None) for _ in range(5)] + [_rec("C2")])
        assert prof["ignored_records"]["null_cluster"] == 5
        assert prof["per_cluster"]["C2"]["attempted"] == 1

    def test_rolling_window(self):
        prof = _profile_from([_rec("C1") for _ in range(PER_CLUSTER_WINDOW + 7)])
        assert prof["per_cluster"]["C1"]["attempted"] == PER_CLUSTER_WINDOW

    def test_insufficient_samples_do_not_enter_frontier(self):
        """樣本不足不亂調難度 —— 只進 insufficient_data。"""
        prof = _profile_from([_rec("C1") for _ in range(MIN_SAMPLES - 1)])
        fs = prof["frontier_signal"]
        assert "C1" in fs["insufficient_data"]
        assert "C1" not in fs["too_easy"] and "C1" not in fs["too_hard"]

    def test_outcome_layer_priority(self):
        """verified_independent > liveness > execution_completed > self_reported，
        且 verified_success=None 絕不當 True。"""
        recs = [
            _rec("C1", verified=False, status="verified_independent"),  # 失敗
            _rec("C1", verified=True, status="verified_independent"),   # 成功
            _rec("C1", verified=None, status="not_available"),          # 退回 exec=True
            _rec("C1", legacy=True),                                    # 退回自報 True
        ]
        prof = _profile_from(recs)
        c1 = prof["per_cluster"]["C1"]
        assert c1["attempted"] == 4
        assert c1["succeeded"] == 3, "verified_success=False 那筆必須算失敗"
        assert "verified_independent" in c1["outcome_layers"]
        assert "self_reported" in c1["outcome_layers"]
        fails = [f for f in prof["recent_failures"] if f["cluster"] == "C1"]
        assert len(fails) == 1 and fails[0]["layer"] == "verified_independent"

    def test_write_false_does_not_touch_disk(self):
        before = (ROOT / "data" / "ability_profile_live.json").stat().st_mtime
        _profile_from([_rec("C1") for _ in range(MIN_SAMPLES)])
        after = (ROOT / "data" / "ability_profile_live.json").stat().st_mtime
        assert before == after


# ── P1-c: 難度護欄 ─────────────────────────────────────────────────

@pytest.fixture
def agent():
    return CurriculumAgent(state_path=str(Path(tempfile.mkdtemp()) / "cs.json"))


class TestLevelGuardrails:

    def test_cap_is_axes_plus_one(self, agent):
        for c, prof in CLUSTER_PROFILES.items():
            assert agent.level_cap(c) == len(prof["axes"]) + 1

    def test_level_never_exceeds_cap(self, agent):
        """原本沒有上限：success 恆 True → 永遠 too_easy → 跑 100 題 ratchet 到 L20+。"""
        st = {c: {"level": 1} for c in CLUSTER_PROFILES}
        sig = {"too_easy": list(CLUSTER_PROFILES), "too_hard": [],
               "calibrated": [], "insufficient_data": []}
        for _ in range(30):
            st = agent._update_levels(sig, st)
        for c, v in st.items():
            assert v["level"] == agent.level_cap(c)

    def test_at_most_one_step_per_call(self, agent):
        st = {c: {"level": 1} for c in CLUSTER_PROFILES}
        st = agent._update_levels(
            {"too_easy": list(CLUSTER_PROFILES), "too_hard": [],
             "calibrated": [], "insufficient_data": []}, st)
        assert all(v["level"] == 2 for v in st.values())

    def test_floor_is_one(self, agent):
        st = {c: {"level": 1} for c in CLUSTER_PROFILES}
        sig = {"too_easy": [], "too_hard": list(CLUSTER_PROFILES),
               "calibrated": [], "insufficient_data": []}
        for _ in range(5):
            st = agent._update_levels(sig, st)
        assert all(v["level"] == 1 for v in st.values())

    def test_insufficient_data_clusters_untouched(self, agent):
        st = {c: {"level": 3} for c in CLUSTER_PROFILES}
        st = agent._update_levels(
            {"too_easy": list(CLUSTER_PROFILES), "too_hard": [],
             "calibrated": [], "insufficient_data": ["C1", "C3"]}, st)
        assert st["C1"]["level"] == 3 and st["C3"]["level"] == 3
        assert st["C2"]["level"] == 4

    def test_cap_does_not_enter_overflow_branch(self, agent):
        """上限剛好用滿所有 axes；再高一級才進 overflow（沒有結構的難度膨脹）。"""
        for c in CLUSTER_PROFILES:
            cap = agent.level_cap(c)
            sel, overflow = _selected_axes(c, cap)
            assert not overflow and len(sel) == len(CLUSTER_PROFILES[c]["axes"])
            assert _selected_axes(c, cap + 1)[1] is True

    def test_end_to_end_profiler_to_levels(self, agent):
        """profiler 產的 frontier_signal 直接餵進 _update_levels 不會炸，
        且 insufficient_data 這個新 key 被正確消費。"""
        prof = _profile_from(
            [_rec("C1", verified=True, status="verified_independent")
             for _ in range(MIN_SAMPLES)]          # C1 全過 → too_easy
            + [_rec("C2") for _ in range(MIN_SAMPLES - 1)])   # C2 樣本不足
        st = {c: {"level": 2} for c in CLUSTER_PROFILES}
        st = agent._update_levels(prof["frontier_signal"], st)
        assert st["C1"]["level"] == 3, "C1 全過應該升一級"
        assert st["C2"]["level"] == 2, "C2 樣本不足不該動"


# ── P5-a: 方向 → 學習路徑 ───────────────────────────────────────────

from agents.path_generator import PathGenerator, kind_for, MIN_STEPS, MAX_STEPS  # noqa: E402


class TestPathGenerator:
    """不打 LLM，只測後處理的硬保證與 kind 推導。"""

    def test_kind_inferred_from_extension_not_generator(self):
        """實測第一次跑，LLM 把 .json 輸出全部標成 run_capture（那個 kind 需要
        pattern，會在檢查時直接失敗）。副檔名優先。"""
        assert kind_for("a.json", "run_capture") == "json_equals"
        assert kind_for("b.csv", "run_capture") == "csv_column"
        assert kind_for("c.pptx", None) == "pptx_outline"
        assert kind_for("d.py", None) == "run_capture"
        assert kind_for("e.txt", None) == "file_exists"      # 沒對到才退回
        assert kind_for("f.txt", "json_equals") == "json_equals"

    def test_level_clamped_to_cluster_cap(self):
        steps = [{"cluster": "C1", "level": 99}, {"cluster": "C5", "level": 99}]
        out = PathGenerator._normalise(steps, "p1", "pipeline")
        assert out[0]["level"] == 4 and out[1]["level"] == 6   # C1 cap 4, C5 cap 6

    def test_level_monotone_and_pos_contiguous(self):
        steps = [{"cluster": "C2", "level": 3}, {"cluster": "C2", "level": 1},
                 {"cluster": "C2", "level": 2}]
        out = PathGenerator._normalise(steps, "p1", "pipeline")
        assert [s["path_pos"] for s in out] == [0, 1, 2]
        assert [s["level"] for s in out] == sorted(s["level"] for s in out)

    def test_unknown_cluster_falls_back(self):
        out = PathGenerator._normalise([{"cluster": "C99", "level": 1}], "p1", "g")
        assert out[0]["cluster"] in CLUSTER_PROFILES

    def test_parent_chain(self):
        steps = [{"cluster": "C2", "level": 1, "task_id": "a"},
                 {"cluster": "C2", "level": 2, "task_id": "b"},
                 {"cluster": "C2", "level": 3, "task_id": "c"}]
        out = PathGenerator._normalise(steps, "p1", "g")
        assert [s["parent_task_id"] for s in out] == [None, "a", "b"]

    def test_json_extraction_respects_wanted_type(self):
        """細節回應裡同時有 array 與 object 時，盲抓第一個會拿錯型別。"""
        blob = 'here you go\n```json\n{"a": [1,2,3], "b": "x"}\n```\n'
        assert PathGenerator._json_from(blob, want=dict)["b"] == "x"
        assert PathGenerator._json_from('[{"k":1}]', want=list)[0]["k"] == 1


class TestVerifyRunnerStatus:
    """verification_status 由實跑的 kind 算出，不採信生成器自報。"""

    def test_status_computed_not_declared(self):
        import sys as _s
        _s.path.insert(0, str(ROOT / "scripts"))
        from verify_runner import compute_status
        assert compute_status({"a.json": {"kind": "json_equals"}}) == "verified_independent"
        # 單一 case 的 run_capture 只算 liveness（常數腳本就能過）
        assert compute_status({"a.py": {"kind": "run_capture", "cases": [{}]}}) == "verified_liveness"
        assert compute_status({"a.py": {"kind": "run_capture",
                                        "cases": [{}, {}]}}) == "verified_independent"
        # 純形狀的 pptx 沒有 input 導出的字面值 → liveness
        assert compute_status({"a.pptx": {"kind": "pptx_outline", "slides": 3}}) == "verified_liveness"
        assert compute_status({"a.pptx": {"kind": "pptx_outline",
                                          "titles": {"set": ["X"]}}}) == "verified_independent"
        # file_exists 單獨當唯一 spec → 不算驗過（三種假解一個都擋不住）
        assert compute_status({"a.txt": {"kind": "file_exists"}}) == "not_available"
        assert compute_status({}) == "not_available"

    def test_bare_run_capture_is_not_available(self):
        """裸 run_capture（沒 cases 也沒 pattern）沒有 oracle → not_available。

        迴歸：50 題長跑裡 7 題 run_capture 的 spec 只有 {kind, path, from_reference}，
        checker 在 re.compile(spec["pattern"]) 掛掉、fail-closed 記成 verified=False，
        7 題全部被算進 verified 分母 → 64% 而非真實的 74%。
        """
        import sys as _s
        _s.path.insert(0, str(ROOT / "scripts"))
        from verify_runner import compute_status, _is_inert, _usable, _verdict

        bare = {"kind": "run_capture", "path": "s.py", "from_reference": True}
        assert _is_inert(bare)
        assert compute_status({"s.py": bare}) == "not_available"
        assert _usable({"s.py": bare}) == {}

        # 唯一有效 spec 之外還有裸 spec：裸的被濾掉，強度由剩下的決定
        assert compute_status({"s.py": bare,
                               "a.json": {"kind": "json_equals"}}) == "verified_independent"

        # 帶 cases 的一律不算 inert —— 「≥2 cases 才 independent」那條規則不受影響
        assert not _is_inert({"kind": "run_capture", "cases": [{}]})
        assert not _is_inert({"kind": "run_capture", "pattern": r"(?P<x>\d+)"})

    def test_not_available_never_becomes_a_verdict(self):
        """不變式：status == not_available ⇔ verified_success is None。

        「量不到」不是一個量測結果 —— 既不能當 True 也不能當 False。
        """
        import sys as _s
        _s.path.insert(0, str(ROOT / "scripts"))
        from verify_runner import _verdict

        assert _verdict(None, "not_available") is None
        assert _verdict(True, "not_available") is None    # 就算檢查通過也不算數
        assert _verdict(False, "not_available") is None   # ← 那 7 題原本走這裡
        assert _verdict(True, "verified_independent") is True
        assert _verdict(False, "verified_independent") is False
        assert _verdict(True, "verified_liveness") is True


# ── P3-5: provenance 邊 ─────────────────────────────────────────────

from evolution.provenance_edges import build_edges, apply_to_graph, W_FOLLOWS, W_REQUIRES  # noqa: E402
import networkx as nx  # noqa: E402


def _steps(pairs, path_id="p1"):
    return [{"task_id": f"{path_id}-{i}", "path_id": path_id, "path_pos": i,
             "produced_skills": [p], "skills_used": u}
            for i, (p, u) in enumerate(pairs)]


class TestProvenanceEdges:
    """P3 的失敗保險：不依賴共現統計，直接把課程路徑的順序落地成邊。"""

    def test_chain_of_five_yields_four_edges(self):
        """驗收條件：一條 5 題的路徑產生 ≥4 條 provenance 邊。"""
        recs = _steps([(f"s{i}", []) for i in range(5)])
        edges = build_edges(recs)
        assert len(edges) >= 4
        assert [(e.from_pos, e.to_pos) for e in edges] == [(0, 1), (1, 2), (2, 3), (3, 4)]

    def test_follows_upgrades_to_requires_when_actually_retrieved(self):
        """k+1 的 trace 真的檢索到 k 的技能 → 那不只是順序，是前置依賴。"""
        weak = build_edges(_steps([("a", []), ("b", ["unrelated"])]))
        assert weak[0].relation == "follows" and weak[0].weight == W_FOLLOWS
        strong = build_edges(_steps([("a", []), ("b", ["a"])]))
        assert strong[0].relation == "requires" and strong[0].weight == W_REQUIRES

    def test_falls_back_to_skills_used_when_nothing_produced(self):
        """一步沒抽出新技能就斷鏈的話，5 題路徑常常只剩 1-2 條邊。"""
        recs = [{"path_id": "p", "path_pos": 0, "produced_skills": [], "skills_used": ["x"]},
                {"path_id": "p", "path_pos": 1, "produced_skills": ["y"], "skills_used": []}]
        assert [(e.source, e.target) for e in build_edges(recs)] == [("x", "y")]

    def test_records_without_path_id_ignored(self):
        assert build_edges([{"task_id": "t", "skills_used": ["a"]}]) == []

    def test_multiple_paths_do_not_cross_link(self):
        recs = _steps([("a", []), ("b", [])], "p1") + _steps([("c", []), ("d", [])], "p2")
        pairs = {(e.source, e.target) for e in build_edges(recs)}
        assert pairs == {("a", "b"), ("c", "d")}

    def test_out_of_order_records_are_sorted(self):
        recs = _steps([("a", []), ("b", []), ("c", [])])
        recs.reverse()
        assert [(e.from_pos, e.to_pos) for e in build_edges(recs)] == [(0, 1), (1, 2)]

    def test_apply_skips_nodes_not_in_graph(self):
        g = nx.DiGraph(); g.add_node("a")
        rep = apply_to_graph(g, build_edges(_steps([("a", []), ("ghost", [])])))
        assert rep.edges_added == 0 and rep.skipped_missing_node == 1

    def test_apply_never_downgrades_requires_to_follows(self):
        g = nx.DiGraph(); g.add_nodes_from(["a", "b"])
        recs = _steps([("a", []), ("b", ["a"])], "p1") + _steps([("a", []), ("b", [])], "p2")
        apply_to_graph(g, build_edges(recs))
        assert g.edges["a", "b"]["relation"] == "requires"

    def test_edge_carries_provenance_for_honest_reporting(self):
        """論文上要能區分 provenance-derived 與統計推論的邊。"""
        g = nx.DiGraph(); g.add_nodes_from(["a", "b"])
        apply_to_graph(g, build_edges(_steps([("a", []), ("b", [])], "pX")))
        d = g.edges["a", "b"]
        assert d["provenance"] == "curriculum_path" and d["path_id"] == "pX"


class TestGraphSerializerKeepsAttributes:
    """[P2-0] 8-key 白名單會把 provenance / parent_skills 靜默丟掉。"""

    def test_unknown_node_and_edge_attrs_survive_roundtrip(self, tmp_path):
        import parse_graph_index as pgi
        g = nx.DiGraph()
        g.add_node("a", tier="active", utility=0.5, evidence_task_ids=["T-1"])
        g.add_node("b", tier="active", utility=0.5)
        g.add_edge("a", "b", relation="follows", weight=0.4,
                   provenance="curriculum_path", path_id="p1")
        out = tmp_path / "GI.md"
        pgi.graph_to_index_md(g, str(out))
        g2 = pgi.build_graph(pgi.parse_graph_index(str(out)))
        assert g2.nodes["a"]["evidence_task_ids"] == ["T-1"]
        assert g2.edges["a", "b"]["provenance"] == "curriculum_path"
        assert g2.edges["a", "b"]["path_id"] == "p1"


# ── P3-3: macro 連回 parent ─────────────────────────────────────────

from evolution.graph_contractor import add_composes_into_edges, backfill_existing_macros  # noqa: E402


class TestMacroComposesInto:
    """RF-1 的直接修補：收縮原本只 add_node，parent 是孤島時 macro 也是孤島。"""

    def test_adds_one_edge_per_parent(self):
        g = nx.DiGraph(); g.add_nodes_from(["a", "b", "macro-a-b"])
        assert add_composes_into_edges(g, "macro-a-b", ["a", "b"]) == 2
        for p in ("a", "b"):
            assert g.edges[p, "macro-a-b"]["relation"] == "composes_into"
            assert g.edges[p, "macro-a-b"]["weight"] == 1.0

    def test_macro_no_longer_isolated(self):
        g = nx.DiGraph(); g.add_nodes_from(["a", "b", "macro-a-b"])
        assert g.degree("macro-a-b") == 0
        add_composes_into_edges(g, "macro-a-b", ["a", "b"])
        assert g.degree("macro-a-b") == 2

    def test_frontmatter_fields_filled(self):
        """linked_nodes 原本一直是空 list，檔案自述跟圖對不起來。"""
        g = nx.DiGraph(); g.add_nodes_from(["a", "b", "macro-a-b"])
        add_composes_into_edges(g, "macro-a-b", ["a", "b"])
        assert g.nodes["macro-a-b"]["parent_skills"] == ["a", "b"]
        assert g.nodes["macro-a-b"]["linked_nodes"] == ["a", "b"]

    def test_parent_not_in_graph_is_skipped(self):
        g = nx.DiGraph(); g.add_nodes_from(["a", "macro-a-b"])
        assert add_composes_into_edges(g, "macro-a-b", ["a", "ghost"]) == 1

    def test_backfill_is_idempotent(self):
        g = nx.DiGraph()
        g.add_nodes_from(["a", "b"])
        g.add_node("macro-a-b", parent_skills=["a", "b"])
        first = backfill_existing_macros(g)
        second = backfill_existing_macros(g)
        assert first["edges_added"] == 2 and second["edges_added"] == 0

    def test_invariant_edges_equal_twice_macro_count(self):
        """P3-3 驗收：composes_into 邊數 == 2 × 收縮次數。"""
        g = nx.DiGraph()
        for i in range(3):
            g.add_nodes_from([f"p{i}a", f"p{i}b"])
            g.add_node(f"macro-{i}", parent_skills=[f"p{i}a", f"p{i}b"])
        backfill_existing_macros(g)
        ci = [1 for _, _, d in g.edges(data=True) if d.get("relation") == "composes_into"]
        macros = [n for n in g.nodes if str(n).startswith("macro-")]
        assert len(ci) == 2 * len(macros)
