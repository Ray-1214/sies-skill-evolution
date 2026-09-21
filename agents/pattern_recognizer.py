"""
pattern_recognizer.py — Action 子序列共現分析 (W9)
===================================================
純統計方法，不需 LLM。供 W11 T3 觸發條件使用。

§6.3：「T3 觸發條件可以先用純統計方法（n-gram 共現計數），
不需要 LLM 參與。」

依賴：agents/base_extractor.py (classify_trace only), 無外部 lib

用法：
    from agents.pattern_recognizer import PatternRecognizer
    pr = PatternRecognizer()
    traces = pr.load_traces_from_dir("memory/episodic/")
    report = pr.analyze(traces, n_range=(2, 4), min_frequency=0.3)
    for p in report.patterns:
        print(p.sequence, f"freq={p.frequency:.0%}")
    pr.export_patterns(report, "data/patterns.json")
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.base_extractor import classify_trace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ActionPattern:
    """一個高共現的 action 子序列。"""
    sequence: tuple[str, ...]   # e.g. ("code_execution", "code_execution", "finish")
    count: int                  # 出現在多少條不同 trace 中
    frequency: float            # count / total_traces
    avg_position: float         # 首次出現的平均正規化位置 (0=開頭, 1=結尾)
    is_success_pattern: bool    # 主要出現在成功 trace 中


@dataclass
class PatternReport:
    """完整分析報告。"""
    total_traces: int
    success_traces: int
    failure_traces: int
    patterns: list[ActionPattern]
    most_common_actions: list[tuple[str, int]]


# ---------------------------------------------------------------------------
# PatternRecognizer
# ---------------------------------------------------------------------------

class PatternRecognizer:
    """
    純統計 n-gram 共現分析器。
    從多條 trace 提取高頻 action 子序列，作為 Macro-Skill 收縮候選。
    """

    def __init__(self):
        pass

    # ── 公開 API ──────────────────────────────────────────

    def analyze(
        self,
        traces: list[list[dict]],
        n_range: tuple[int, int] = (2, 4),
        min_frequency: float = 0.3,
    ) -> PatternReport:
        """分析多條 trace，找出高共現 action 子序列。"""
        if not traces:
            return PatternReport(
                total_traces=0, success_traces=0, failure_traces=0,
                patterns=[], most_common_actions=[],
            )

        # Classify traces
        success_traces = [t for t in traces if classify_trace(t) == "success"]
        failure_traces = [t for t in traces if classify_trace(t) == "failure"]
        total = len(traces)

        # Extract action sequences
        all_sequences = [self._extract_action_sequence(t) for t in traces]
        success_sequences = [self._extract_action_sequence(t) for t in success_traces]
        failure_sequences = [self._extract_action_sequence(t) for t in failure_traces]

        # Count all actions globally
        all_actions = Counter()
        for seq in all_sequences:
            all_actions.update(seq)
        most_common = all_actions.most_common(10)

        # Find patterns across all n values
        raw_patterns: dict[tuple[str, ...], int] = {}
        min_n, max_n = n_range

        for n in range(min_n, max_n + 1):
            counts = self._count_ngrams(all_sequences, n)
            for ngram, count in counts.items():
                freq = count / total
                if freq >= min_frequency:
                    raw_patterns[ngram] = count

        # Build ActionPattern objects
        patterns = []
        for seq, count in raw_patterns.items():
            freq = count / total
            avg_pos = self._calc_avg_position(traces, seq)
            is_success = self._classify_pattern(
                seq, success_sequences, failure_sequences
            )
            patterns.append(ActionPattern(
                sequence=seq,
                count=count,
                frequency=round(freq, 3),
                avg_position=round(avg_pos, 3),
                is_success_pattern=is_success,
            ))

        # Sort by frequency descending, then by sequence length descending
        patterns.sort(key=lambda p: (p.frequency, len(p.sequence)), reverse=True)

        return PatternReport(
            total_traces=total,
            success_traces=len(success_traces),
            failure_traces=len(failure_traces),
            patterns=patterns,
            most_common_actions=most_common,
        )

    def load_traces_from_dir(
        self, trace_dir: str, max_files: int = 100
    ) -> list[list[dict]]:
        """從目錄載入多條 trace，每個 .jsonl = 一條 trace。"""
        scan = Path(trace_dir)
        if not scan.exists():
            logger.warning(f"[PatternRecognizer] Directory not found: {trace_dir}")
            return []

        files = sorted(
            scan.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_files]

        traces = []
        for f in files:
            records = []
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
            except Exception as e:
                logger.warning(f"[PatternRecognizer] Error reading {f.name}: {e}")
                continue

            if records:
                traces.append(records)

        logger.info(f"[PatternRecognizer] Loaded {len(traces)} traces from {trace_dir}")
        return traces

    def export_patterns(self, report: PatternReport, output_path: str) -> Path:
        """匯出 pattern 報告為 JSON。"""
        data = {
            "total_traces": report.total_traces,
            "success_traces": report.success_traces,
            "failure_traces": report.failure_traces,
            "patterns": [
                {
                    "sequence": list(p.sequence),
                    "count": p.count,
                    "frequency": p.frequency,
                    "avg_position": p.avg_position,
                    "is_success_pattern": p.is_success_pattern,
                }
                for p in report.patterns
            ],
            "most_common_actions": report.most_common_actions,
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"[PatternRecognizer] Exported {len(report.patterns)} patterns to {path}")
        return path

    # ── 內部方法 ──────────────────────────────────────────

    def _extract_action_sequence(self, trace: list[dict]) -> list[str]:
        """從一條 trace 提取 action 序列，跳過空 action。"""
        return [
            r["action"].lower()
            for r in trace
            if r.get("action") and r["action"].strip()
        ]

    def _count_ngrams(
        self, sequences: list[list[str]], n: int
    ) -> Counter:
        """
        計算 n-gram 出現在多少條不同序列中（set 去重後計數）。
        避免單條 stuck-loop trace 灌水。
        """
        counter = Counter()
        for seq in sequences:
            if len(seq) < n:
                continue
            # Each sequence contributes at most 1 to each ngram
            seen = set()
            for i in range(len(seq) - n + 1):
                ngram = tuple(seq[i:i + n])
                seen.add(ngram)
            counter.update(seen)
        return counter

    def _calc_avg_position(
        self, traces: list[list[dict]], pattern: tuple[str, ...]
    ) -> float:
        """計算 pattern 首次出現的平均正規化位置。"""
        positions = []
        n = len(pattern)

        for trace in traces:
            seq = self._extract_action_sequence(trace)
            total_steps = len(seq)
            if total_steps < n:
                continue

            for i in range(total_steps - n + 1):
                if tuple(seq[i:i + n]) == pattern:
                    # Normalized position: 0.0 = start, 1.0 = end
                    positions.append(i / max(total_steps - 1, 1))
                    break  # only first occurrence

        if not positions:
            return 0.5
        return sum(positions) / len(positions)

    def _classify_pattern(
        self,
        pattern: tuple[str, ...],
        success_sequences: list[list[str]],
        failure_sequences: list[list[str]],
    ) -> bool:
        """判斷 pattern 主要出現在成功還是失敗 trace 中。"""
        n = len(pattern)

        def _count_in(sequences: list[list[str]]) -> int:
            count = 0
            for seq in sequences:
                if len(seq) < n:
                    continue
                for i in range(len(seq) - n + 1):
                    if tuple(seq[i:i + n]) == pattern:
                        count += 1
                        break
            return count

        s_count = _count_in(success_sequences)
        f_count = _count_in(failure_sequences)
        return s_count >= f_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    trace_dir = sys.argv[1] if len(sys.argv) > 1 else "./memory/episodic"
    output = sys.argv[2] if len(sys.argv) > 2 else "./data/patterns.json"

    pr = PatternRecognizer()
    traces = pr.load_traces_from_dir(trace_dir)

    if not traces:
        print(f"No traces found in {trace_dir}")
        sys.exit(1)

    report = pr.analyze(traces, n_range=(2, 4), min_frequency=0.2)

    print(f"\n=== Pattern Analysis ===")
    print(f"Traces: {report.total_traces} (success={report.success_traces}, failure={report.failure_traces})")
    print(f"\nMost common actions:")
    for action, count in report.most_common_actions:
        print(f"  {action}: {count}")

    print(f"\nPatterns (frequency >= 20%):")
    for p in report.patterns:
        tag = "✓" if p.is_success_pattern else "✗"
        print(f"  [{tag}] {' → '.join(p.sequence)}: "
              f"freq={p.frequency:.0%} ({p.count} traces), "
              f"avg_pos={p.avg_position:.2f}")

    pr.export_patterns(report, output)
    print(f"\nExported to {output}")