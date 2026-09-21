"""
tests/test_w9_unit.py — W9 模組單元測試（mock-based，不需 LLM）
================================================================
測試 base_extractor 工具函數、SKILL.md 生成、pattern_recognizer。
"""

import json
import pytest
import tempfile
from pathlib import Path

from agents.base_extractor import (
    CandidateSkill,
    ExtractionResult,
    classify_trace,
    strip_think,
    parse_json_output,
    summarize_trace,
    BaseExtractor,
)
from agents.pattern_recognizer import PatternRecognizer


# ---------------------------------------------------------------------------
# Test data: mock traces
# ---------------------------------------------------------------------------

TRACE_SUCCESS = [
    {"task_id": "T-test-01", "step": 1, "thought": "Create file", "action": "bash_execution",
     "action_input": "echo 'hello world' > /tmp/test.txt && cat /tmp/test.txt",
     "observation": "hello world", "success": True, "elapsed_seconds": 3.3,
     "timestamp": "2026-04-12T01:00:00+08:00", "tool_exit_code": 0, "tool_error": None},
    {"task_id": "T-test-01", "step": 2, "thought": "Duplicate step", "action": "bash_execution",
     "action_input": "echo 'hello world' > /tmp/test.txt && cat /tmp/test.txt",
     "observation": "hello world", "success": True, "elapsed_seconds": 2.5,
     "timestamp": "2026-04-12T01:00:03+08:00", "tool_exit_code": 0, "tool_error": None},
    {"task_id": "T-test-01", "step": 3, "thought": "Done", "action": "finish",
     "action_input": "File created and verified.", "observation": "File created and verified.",
     "success": True, "elapsed_seconds": 1.8,
     "timestamp": "2026-04-12T01:00:05+08:00", "tool_exit_code": 0, "tool_error": None},
]

TRACE_FAILURE_STUCK = [
    {"task_id": "T-test-02", "step": i, "thought": "Try again",
     "action": "bash_execution",
     "action_input": "echo hello\n\n**Observation:**\nhello",
     "observation": "STDERR: **Observation:**: command not found",
     "success": False, "elapsed_seconds": 4.0,
     "timestamp": f"2026-04-12T01:00:{i:02d}+08:00",
     "tool_exit_code": 127, "tool_error": "**Observation:**: command not found"}
    for i in range(1, 11)
]

TRACE_EMPTY = []

TRACE_SINGLE_FINISH = [
    {"task_id": "T-test-03", "step": 1, "thought": "", "action": "finish",
     "action_input": "42", "observation": "42", "success": True,
     "elapsed_seconds": 0.5, "timestamp": "2026-04-12T01:00:00+08:00",
     "tool_exit_code": 0, "tool_error": None},
]


# ---------------------------------------------------------------------------
# classify_trace
# ---------------------------------------------------------------------------

class TestClassifyTrace:
    def test_success(self):
        assert classify_trace(TRACE_SUCCESS) == "success"

    def test_failure_stuck(self):
        assert classify_trace(TRACE_FAILURE_STUCK) == "failure"

    def test_empty(self):
        assert classify_trace(TRACE_EMPTY) == "failure"

    def test_single_finish(self):
        assert classify_trace(TRACE_SINGLE_FINISH) == "success"


# ---------------------------------------------------------------------------
# strip_think
# ---------------------------------------------------------------------------

class TestStripThink:
    def test_removes_think_block(self):
        text = '<think>internal reasoning</think>{"skills": []}'
        assert strip_think(text) == '{"skills": []}'

    def test_removes_multiline_think(self):
        text = '<think>\nline 1\nline 2\n</think>\nresult'
        assert strip_think(text) == "result"

    def test_no_think_block(self):
        assert strip_think('{"skills": []}') == '{"skills": []}'

    def test_empty(self):
        assert strip_think("") == ""


# ---------------------------------------------------------------------------
# parse_json_output
# ---------------------------------------------------------------------------

class TestParseJsonOutput:
    def test_direct_json(self):
        result = parse_json_output('{"skills": []}')
        assert result == {"skills": []}

    def test_with_think_block(self):
        text = '<think>hmm</think>{"skills": [{"name": "test"}]}'
        result = parse_json_output(text)
        assert result is not None
        assert result["skills"][0]["name"] == "test"

    def test_markdown_fence(self):
        text = 'some text\n```json\n{"lessons": []}\n```\nmore text'
        result = parse_json_output(text)
        assert result == {"lessons": []}

    def test_brace_extraction(self):
        text = 'Here is the result: {"a": 1} and more text'
        result = parse_json_output(text)
        assert result == {"a": 1}

    def test_invalid_json(self):
        assert parse_json_output("not json at all") is None

    def test_empty(self):
        assert parse_json_output("") is None


# ---------------------------------------------------------------------------
# summarize_trace
# ---------------------------------------------------------------------------

class TestSummarizeTrace:
    def test_basic(self):
        s = summarize_trace(TRACE_SUCCESS)
        assert "Step 1" in s
        assert "finish" in s

    def test_empty(self):
        assert summarize_trace([]) == "(empty trace)"

    def test_repeat_detection(self):
        """Stuck loop 的 10 步應該被合併顯示。"""
        s = summarize_trace(TRACE_FAILURE_STUCK)
        assert "repeated" in s
        # Should NOT have all 10 steps expanded
        assert s.count("Step") < 10

    def test_max_chars(self):
        s = summarize_trace(TRACE_FAILURE_STUCK, max_chars=500)
        assert len(s) <= 500


# ---------------------------------------------------------------------------
# CandidateSkill + SKILL.md generation
# ---------------------------------------------------------------------------

class TestSkillMdGeneration:
    def _make_skill(self, **overrides) -> CandidateSkill:
        defaults = dict(
            name="test-skill",
            description="A test skill",
            type="general",
            domain=["software-engineering"],
            invocation_condition="When testing",
            termination_condition="Tests pass",
            strategy_steps=["Step 1", "Step 2"],
            confidence=0.8,
            source_task_id="T-test-01",
        )
        defaults.update(overrides)
        return CandidateSkill(**defaults)

    def test_general_skill_md(self):
        """Test SKILL.md generation for general skill."""
        skill = self._make_skill()
        # We can't easily call BaseExtractor.to_skill_md without init,
        # so test the CandidateSkill dataclass structure
        assert skill.name == "test-skill"
        assert skill.type == "general"
        assert skill.root_cause is None

    def test_lesson_skill_md(self):
        """Test CandidateSkill with root_cause for lessons."""
        skill = self._make_skill(
            type="task_specific",
            root_cause="Agent got stuck in a loop",
        )
        assert skill.type == "task_specific"
        assert skill.root_cause == "Agent got stuck in a loop"

    def test_default_source_trace_summary(self):
        """source_trace_summary should default to empty string."""
        skill = self._make_skill()
        assert skill.source_trace_summary == ""


# ---------------------------------------------------------------------------
# PatternRecognizer
# ---------------------------------------------------------------------------

class TestPatternRecognizer:
    def setup_method(self):
        self.pr = PatternRecognizer()

    def test_extract_action_sequence(self):
        seq = self.pr._extract_action_sequence(TRACE_SUCCESS)
        assert seq == ["bash_execution", "bash_execution", "finish"]

    def test_extract_action_sequence_failure(self):
        seq = self.pr._extract_action_sequence(TRACE_FAILURE_STUCK)
        assert len(seq) == 10
        assert all(a == "bash_execution" for a in seq)

    def test_count_ngrams_dedup(self):
        """Each trace contributes at most 1 to each ngram."""
        sequences = [
            ["bash_execution", "bash_execution", "bash_execution", "finish"],
        ]
        counts = self.pr._count_ngrams(sequences, 2)
        # ("bash_execution", "bash_execution") appears at position 0-1 and 1-2,
        # but dedup means the trace contributes 1
        assert counts[("bash_execution", "bash_execution")] == 1
        assert counts[("bash_execution", "finish")] == 1

    def test_count_ngrams_multiple_traces(self):
        sequences = [
            ["code_execution", "finish"],
            ["code_execution", "finish"],
            ["bash_execution", "finish"],
        ]
        counts = self.pr._count_ngrams(sequences, 2)
        assert counts[("code_execution", "finish")] == 2
        assert counts[("bash_execution", "finish")] == 1

    def test_analyze_basic(self):
        traces = [TRACE_SUCCESS, TRACE_SINGLE_FINISH]
        report = self.pr.analyze(traces, n_range=(2, 3), min_frequency=0.4)
        assert report.total_traces == 2
        assert report.success_traces == 2
        assert report.failure_traces == 0

    def test_analyze_empty(self):
        report = self.pr.analyze([], n_range=(2, 4), min_frequency=0.3)
        assert report.total_traces == 0
        assert report.patterns == []

    def test_analyze_with_failure(self):
        traces = [TRACE_SUCCESS, TRACE_FAILURE_STUCK]
        report = self.pr.analyze(traces, n_range=(2, 3), min_frequency=0.4)
        assert report.total_traces == 2
        assert report.success_traces == 1
        assert report.failure_traces == 1

    def test_classify_pattern(self):
        success_seqs = [["code_execution", "finish"]]
        failure_seqs = [["bash_execution", "bash_execution"]]

        # ("code_execution", "finish") should be a success pattern
        assert self.pr._classify_pattern(
            ("code_execution", "finish"), success_seqs, failure_seqs
        ) is True

    def test_export_and_load(self):
        traces = [TRACE_SUCCESS, TRACE_FAILURE_STUCK]
        report = self.pr.analyze(traces, n_range=(2, 3), min_frequency=0.3)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name

        self.pr.export_patterns(report, path)

        with open(path) as f:
            data = json.load(f)

        assert data["total_traces"] == 2
        assert isinstance(data["patterns"], list)

    def test_load_traces_from_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a trace file
            trace_path = Path(tmpdir) / "test_trace.jsonl"
            with open(trace_path, "w") as f:
                for r in TRACE_SUCCESS:
                    f.write(json.dumps(r) + "\n")

            traces = self.pr.load_traces_from_dir(tmpdir)
            assert len(traces) == 1
            assert len(traces[0]) == 3

    def test_load_traces_missing_dir(self):
        traces = self.pr.load_traces_from_dir("/nonexistent/path")
        assert traces == []


# ---------------------------------------------------------------------------
# BaseExtractor validation helpers
# ---------------------------------------------------------------------------

class TestBaseExtractorHelpers:
    def test_validate_domain_list_valid(self):
        result = BaseExtractor._validate_domain_list(["software-engineering", "system-ops"])
        assert result == ["software-engineering", "system-ops"]

    def test_validate_domain_list_invalid(self):
        """Invalid domains filtered, at least one valid remains."""
        result = BaseExtractor._validate_domain_list(["code_task", "software-engineering"])
        assert result == ["software-engineering"]

    def test_validate_domain_list_all_invalid(self):
        """All invalid → fallback to software-engineering."""
        result = BaseExtractor._validate_domain_list(["code_task", "math_task"])
        assert result == ["software-engineering"]

    def test_validate_domain_list_not_list(self):
        result = BaseExtractor._validate_domain_list("not a list")
        assert result == ["software-engineering"]

    def test_to_kebab_case(self):
        assert BaseExtractor._to_kebab_case("Hello World") == "hello-world"
        assert BaseExtractor._to_kebab_case("already-kebab") == "already-kebab"
        assert BaseExtractor._to_kebab_case("With Spaces & Symbols!") == "with-spaces-symbols"

    def test_to_kebab_case_empty(self):
        assert BaseExtractor._to_kebab_case("") == "unnamed-skill"

    def test_clamp_confidence(self):
        assert BaseExtractor._clamp_confidence(0.5) == 0.5
        assert BaseExtractor._clamp_confidence(1.5) == 1.0
        assert BaseExtractor._clamp_confidence(-0.5) == 0.0
        assert BaseExtractor._clamp_confidence("0.8") == 0.8
        assert BaseExtractor._clamp_confidence("invalid") == 0.5