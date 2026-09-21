#!/usr/bin/env python3
"""verify_case_studies.py — W13 case study binary verdict (W13 Day 5-6).

對 5 個 W13 case study 對 baseline + improved JSON 對跑字面 PASS / PARTIAL / FAIL，
輸出 docs/w13_case_study_verdict.md。

設計約束：
  - pass criterion 在代碼裡 hardcoded（每 CS 一個 verify 函數），不 runtime parse
    docs/w13_case_study_expected.md。expected.md 為 pre-registered reference。
  - PARTIAL 是 post-hoc category 抓 expected.md criterion miscalibration，
    不放寬 PASS。verdict.md 明確區分「字面 PASS」vs「PARTIAL」。
  - M4 統計用字面 PASS 數；PARTIAL 給論文 §7 lessons learned 用。
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


REQUIRED_FIELDS = ("candidates", "a2_recall_top6", "trace_steps_count")


@dataclass
class ConjunctResult:
    label: str
    description: str
    passed: bool
    actual: str


@dataclass
class Verdict:
    cs_id: str
    task: str
    literal_pass: bool
    final_verdict: str  # "PASS" | "PARTIAL" | "FAIL" | "INVALID"
    label: str
    criterion_text: str
    conjuncts: list[ConjunctResult]
    evidence: dict[str, object]
    error: str = ""


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def load_cs(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[verify_case_studies] ERROR loading {path}: {e}", file=sys.stderr)
        return None
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if missing:
        print(
            f"[verify_case_studies] ERROR {path}: missing fields {missing}",
            file=sys.stderr,
        )
        return None
    return data


def candidate_names(cs: dict) -> list[str]:
    return [c.get("name", "") for c in cs.get("candidates", [])]


def _check_stochastic_failure(
    baseline: dict, improved: dict, cs_id: str, task: str,
) -> Verdict | None:
    """Return INVALID Verdict if either side's agent_outcome is 'failure'.

    Stochastic agent failures invalidate the v1/v2 comparison for that CS
    (criteria assume both runs reached a complete success trace). Distinct
    from `make_invalid_verdict` which handles missing/malformed JSON.
    """
    if baseline.get("agent_outcome") == "failure":
        return Verdict(
            cs_id=cs_id, task=task,
            literal_pass=False, final_verdict="INVALID",
            label=(
                f"baseline stochastic failure (agent_outcome=failure, "
                f"steps={baseline.get('trace_steps_count')}); comparison undefined"
            ),
            criterion_text="(not evaluated — baseline run failed)",
            conjuncts=[],
            evidence={
                "baseline.agent_outcome": baseline.get("agent_outcome"),
                "baseline.trace_steps_count": baseline.get("trace_steps_count"),
                "baseline.candidates": candidate_names(baseline),
                "improved.agent_outcome": improved.get("agent_outcome"),
            },
        )
    if improved.get("agent_outcome") == "failure":
        return Verdict(
            cs_id=cs_id, task=task,
            literal_pass=False, final_verdict="INVALID",
            label=(
                f"improved stochastic failure (agent_outcome=failure, "
                f"steps={improved.get('trace_steps_count')}); comparison undefined"
            ),
            criterion_text="(not evaluated — improved run failed)",
            conjuncts=[],
            evidence={
                "baseline.agent_outcome": baseline.get("agent_outcome"),
                "improved.agent_outcome": improved.get("agent_outcome"),
                "improved.trace_steps_count": improved.get("trace_steps_count"),
                "improved.candidates": candidate_names(improved),
            },
        )
    return None


# ---------------------------------------------------------------------------
# Per-CS verify functions (criteria mirror docs/w13_case_study_expected.md)
# ---------------------------------------------------------------------------

def verify_cs1(baseline: dict, improved: dict) -> Verdict:
    """T12 two_sum — reuse 案."""
    inv = _check_stochastic_failure(baseline, improved, "CS-1", "T12 two_sum")
    if inv is not None:
        return inv
    b_cands = candidate_names(baseline)
    i_cands = candidate_names(improved)
    i_recall = improved.get("a2_recall_top6", [])

    c1 = ConjunctResult(
        "C1", "len(baseline.candidates) >= 1",
        len(b_cands) >= 1, f"len={len(b_cands)}",
    )
    c2 = ConjunctResult(
        "C2", "any('two-sum'/'pair-search' in baseline.candidates[].name)",
        any("two-sum" in n.lower() or "pair-search" in n.lower() for n in b_cands),
        f"baseline names={b_cands}",
    )
    c3 = ConjunctResult(
        "C3", "len(improved.candidates) <= 1",
        len(i_cands) <= 1, f"len={len(i_cands)}",
    )
    c4 = ConjunctResult(
        "C4", "any('hashmap' in improved.a2_recall_top6)",
        any("hashmap" in s.lower() for s in i_recall),
        f"a2_recall_top6={i_recall}",
    )
    conjuncts = [c1, c2, c3, c4]
    literal_pass = all(c.passed for c in conjuncts)

    label = ""
    if literal_pass:
        final = "PASS"
    else:
        partial_kw = ["hash", "search", "lookup", "mapping"]
        partial_hits = [n for n in i_cands if any(k in n.lower() for k in partial_kw)]
        if len(i_cands) >= 1 and partial_hits:
            final = "PARTIAL"
            label = (
                "v2 found new angle; expected.md hashmap criterion targeted "
                "a2_recall but v2 surfaced hashmap in candidates"
            )
        else:
            final = "FAIL"

    return Verdict(
        cs_id="CS-1", task="T12 two_sum",
        literal_pass=literal_pass, final_verdict=final, label=label,
        criterion_text=(
            "len(baseline.candidates) >= 1 AND "
            "any('two-sum'/'pair-search' in baseline.candidates) AND "
            "len(improved.candidates) <= 1 AND "
            "any('hashmap' in improved.a2_recall_top6)"
        ),
        conjuncts=conjuncts,
        evidence={
            "baseline.candidates": b_cands,
            "improved.candidates": i_cands,
            "improved.a2_recall_top6": i_recall,
        },
    )


def verify_cs2(baseline: dict, improved: dict) -> Verdict:
    """T24 email regex — cross-cluster compose 案."""
    inv = _check_stochastic_failure(baseline, improved, "CS-2", "T24 email regex")
    if inv is not None:
        return inv
    b_cands = candidate_names(baseline)
    i_cands = candidate_names(improved)

    c1 = ConjunctResult(
        "C1", "len(baseline.candidates) >= 2",
        len(b_cands) >= 2, f"len={len(b_cands)}",
    )
    c2 = ConjunctResult(
        "C2", "len(improved.candidates) <= 1",
        len(i_cands) <= 1, f"len={len(i_cands)}",
    )
    conjuncts = [c1, c2]
    literal_pass = all(c.passed for c in conjuncts)
    final = "PASS" if literal_pass else "FAIL"

    return Verdict(
        cs_id="CS-2", task="T24 email regex",
        literal_pass=literal_pass, final_verdict=final, label="",
        criterion_text="len(baseline.candidates) >= 2 AND len(improved.candidates) <= 1",
        conjuncts=conjuncts,
        evidence={
            "baseline.candidates": b_cands,
            "improved.candidates": i_cands,
        },
    )


def verify_cs3(baseline: dict, improved: dict) -> Verdict:
    """T34 N-queens — macro emergence 案."""
    inv = _check_stochastic_failure(baseline, improved, "CS-3", "T34 N-queens")
    if inv is not None:
        return inv
    b_cands = candidate_names(baseline)
    i_cands = candidate_names(improved)

    baseline_kw = [
        n for n in b_cands
        if any(k in n.lower() for k in ["backtrack", "recurs", "n-queens"])
    ]
    improved_kw = [
        n for n in i_cands
        if any(k in n.lower() for k in ["backtrack", "recurs"])
    ]

    c1 = ConjunctResult(
        "C1", "len(baseline_kw) >= 2 (kw=backtrack/recurs/n-queens)",
        len(baseline_kw) >= 2, f"baseline_kw={baseline_kw}",
    )
    c2 = ConjunctResult(
        "C2", "len(improved_kw) == 1 (kw=backtrack/recurs)",
        len(improved_kw) == 1, f"improved_kw={improved_kw}",
    )
    conjuncts = [c1, c2]
    literal_pass = all(c.passed for c in conjuncts)

    label = ""
    if literal_pass:
        final = "PASS"
    elif len(baseline_kw) >= 2 and len(improved_kw) == 0:
        final = "PARTIAL"
        label = "v2 over-suppression"
    elif len(baseline_kw) < 2 and len(b_cands) >= 2 and len(improved_kw) == 1:
        final = "PARTIAL"
        label = (
            "expected keyword too narrow; baseline produced 2 candidates "
            "but only 1 matches backtrack/recurs/n-queens keyword"
        )
    else:
        final = "FAIL"

    return Verdict(
        cs_id="CS-3", task="T34 N-queens",
        literal_pass=literal_pass, final_verdict=final, label=label,
        criterion_text=(
            "len([c in baseline.candidates if backtrack/recurs/n-queens in name]) >= 2 AND "
            "len([c in improved.candidates if backtrack/recurs in name]) == 1"
        ),
        conjuncts=conjuncts,
        evidence={
            "baseline.candidates": b_cands,
            "improved.candidates": i_cands,
            "baseline_kw_hits": baseline_kw,
            "improved_kw_hits": improved_kw,
        },
    )


def verify_cs4(baseline: dict, improved: dict) -> Verdict:
    """T42 list Python processes — sanity / retrieval health."""
    inv = _check_stochastic_failure(
        baseline, improved, "CS-4", "T42 list Python processes",
    )
    if inv is not None:
        return inv
    b_cands = candidate_names(baseline)
    i_cands = candidate_names(improved)
    b_recall = baseline.get("a2_recall_top6", [])
    i_recall = improved.get("a2_recall_top6", [])
    intersect = sorted(set(b_recall) & set(i_recall))

    c1 = ConjunctResult(
        "C1", "abs(len(baseline.candidates) - len(improved.candidates)) <= 1",
        abs(len(b_cands) - len(i_cands)) <= 1,
        f"|{len(b_cands)} - {len(i_cands)}| = {abs(len(b_cands) - len(i_cands))}",
    )
    c2 = ConjunctResult(
        "C2", "len(set(baseline.a2_recall_top6) & set(improved.a2_recall_top6)) >= 3",
        len(intersect) >= 3,
        f"intersection={intersect} (count={len(intersect)})",
    )
    conjuncts = [c1, c2]
    literal_pass = all(c.passed for c in conjuncts)
    final = "PASS" if literal_pass else "FAIL"

    return Verdict(
        cs_id="CS-4", task="T42 list Python processes",
        literal_pass=literal_pass, final_verdict=final, label="",
        criterion_text=(
            "abs(len(baseline.candidates) - len(improved.candidates)) <= 1 AND "
            "len(set(baseline.a2_recall_top6) & set(improved.a2_recall_top6)) >= 3"
        ),
        conjuncts=conjuncts,
        evidence={
            "baseline.candidates": b_cands,
            "improved.candidates": i_cands,
            "baseline.a2_recall_top6": b_recall,
            "improved.a2_recall_top6": i_recall,
            "recall_intersection": intersect,
        },
    )


def verify_cs5(baseline: dict, improved: dict) -> Verdict:
    """T50 Vigenère cipher — cumulative effect."""
    inv = _check_stochastic_failure(baseline, improved, "CS-5", "T50 Vigenère cipher")
    if inv is not None:
        return inv
    b_cands = candidate_names(baseline)
    i_cands = candidate_names(improved)
    i_recall = improved.get("a2_recall_top6", [])
    b_steps = baseline.get("trace_steps_count", 0)
    i_steps = improved.get("trace_steps_count", 0)

    keywords = ["cipher", "caesar", "algorithm-impl", "verification", "string", "character"]
    c3_hits = [s for s in i_recall if any(kw in s.lower() for kw in keywords)]

    c1 = ConjunctResult(
        "C1", "improved.trace_steps_count <= baseline.trace_steps_count",
        i_steps <= b_steps, f"improved={i_steps}, baseline={b_steps}",
    )
    c2 = ConjunctResult(
        "C2", "len(improved.candidates) <= len(baseline.candidates)",
        len(i_cands) <= len(b_cands),
        f"improved={len(i_cands)}, baseline={len(b_cands)}",
    )
    c3 = ConjunctResult(
        "C3", f"any keyword in improved.a2_recall_top6 (kw={keywords})",
        len(c3_hits) > 0, f"hits={c3_hits}",
    )
    conjuncts = [c1, c2, c3]
    literal_pass = all(c.passed for c in conjuncts)

    label = ""
    if literal_pass:
        final = "PASS"
    elif c2.passed and c3.passed and not c1.passed and (i_steps - b_steps) <= 1:
        final = "PARTIAL"
        label = (
            "step count criterion unfair when baseline=2 is floor; "
            "other conjuncts hold"
        )
    else:
        final = "FAIL"

    return Verdict(
        cs_id="CS-5", task="T50 Vigenère cipher",
        literal_pass=literal_pass, final_verdict=final, label=label,
        criterion_text=(
            "improved.trace_steps_count <= baseline.trace_steps_count AND "
            "len(improved.candidates) <= len(baseline.candidates) AND "
            "any(kw in improved.a2_recall_top6 for kw in "
            "cipher/caesar/algorithm-impl/verification/string/character)"
        ),
        conjuncts=conjuncts,
        evidence={
            "baseline.candidates": b_cands,
            "improved.candidates": i_cands,
            "baseline.trace_steps_count": b_steps,
            "improved.trace_steps_count": i_steps,
            "improved.a2_recall_top6": i_recall,
            "c3_hits": c3_hits,
        },
    )


VERIFY_FUNCS = [
    ("CS-1", verify_cs1),
    ("CS-2", verify_cs2),
    ("CS-3", verify_cs3),
    ("CS-4", verify_cs4),
    ("CS-5", verify_cs5),
]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def fmt_check(passed: bool) -> str:
    return "✓" if passed else "✗"


def make_invalid_verdict(cs_id: str, msg: str) -> Verdict:
    return Verdict(
        cs_id=cs_id, task="(invalid)",
        literal_pass=False, final_verdict="INVALID",
        label="", criterion_text="(not evaluated)",
        conjuncts=[], evidence={}, error=msg,
    )


def render_markdown(verdicts: list[Verdict]) -> str:
    lines: list[str] = []
    lines.append("# W13 Case Study Verdict\n")
    lines.append(
        "> Generated by scripts/verify_case_studies.py against pre-registered criteria\n"
        "> in docs/w13_case_study_expected.md. Pre-registered PASS criteria are\n"
        "> evaluated first; PARTIAL is a post-hoc category for criterion miscalibration\n"
        "> (not data manipulation). INVALID is a category for stochastic baseline or\n"
        "> improved agent failures (agent_outcome=failure) — the v1/v2 comparison\n"
        "> for that CS is undefined and excluded from the M4 denominator.\n"
    )

    lines.append("## Summary\n")
    lines.append("| CS | task | literal verdict | final verdict | label |")
    lines.append("|----|------|-----------------|---------------|-------|")
    for v in verdicts:
        if v.final_verdict == "INVALID":
            literal = "INVALID"
        else:
            literal = "PASS" if v.literal_pass else "FAIL"
        label_md = v.label if v.label else "—"
        lines.append(
            f"| {v.cs_id} | {v.task} | {literal} | {v.final_verdict} | {label_md} |"
        )
    lines.append("")

    total = len(verdicts)
    invalid_count = sum(1 for v in verdicts if v.final_verdict == "INVALID")
    eligible = total - invalid_count
    literal_pass = sum(1 for v in verdicts if v.literal_pass)
    incl_partial = sum(1 for v in verdicts if v.final_verdict in ("PASS", "PARTIAL"))
    lines.append(
        f"**Literal PASS: {literal_pass} / {eligible}** "
        f"(M4 threshold ≥ 3; INVALID excluded — {invalid_count}/{total} INVALID)"
    )
    lines.append(f"**Including PARTIAL: {incl_partial} / {eligible}**\n")

    for v in verdicts:
        lines.append(f"## {v.cs_id}: {v.task}\n")
        if v.final_verdict == "INVALID":
            msg = v.error or v.label or "(no detail)"
            lines.append(f"**Status**: INVALID — {msg}\n")
            if v.evidence:
                lines.append("**Evidence**:")
                for k, val in v.evidence.items():
                    lines.append(f"- `{k}`: {val}")
                lines.append("")
            lines.append("---\n")
            continue

        literal = "PASS" if v.literal_pass else "FAIL"
        lines.append(f"**Literal verdict**: {literal}  ")
        lines.append(f"**Final verdict**: {v.final_verdict}")
        if v.label:
            lines.append(f"  \n**Label**: {v.label}")
        lines.append("")
        lines.append(f"**Pre-registered criterion**: {v.criterion_text}\n")

        lines.append("**Evaluation**:")
        for c in v.conjuncts:
            lines.append(
                f"- {c.label}: {fmt_check(c.passed)}  {c.description} | {c.actual}"
            )
        lines.append("")

        lines.append("**Evidence**:")
        for k, val in v.evidence.items():
            lines.append(f"- `{k}`: {val}")
        lines.append("")
        lines.append("---\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-dir", required=True, type=Path)
    ap.add_argument("--improved-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    verdicts: list[Verdict] = []
    for cs_id, fn in VERIFY_FUNCS:
        b_path = args.baseline_dir / f"{cs_id}.json"
        i_path = args.improved_dir / f"{cs_id}.json"
        baseline = load_cs(b_path)
        improved = load_cs(i_path)
        if baseline is None or improved is None:
            verdicts.append(make_invalid_verdict(
                cs_id,
                f"missing or malformed JSON (baseline={b_path}, improved={i_path})",
            ))
            continue
        verdicts.append(fn(baseline, improved))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(verdicts), encoding="utf-8")

    summary_parts = [f"{v.cs_id}: {v.final_verdict}" for v in verdicts]
    total = len(verdicts)
    invalid_count = sum(1 for v in verdicts if v.final_verdict == "INVALID")
    eligible = total - invalid_count
    literal_pass = sum(1 for v in verdicts if v.literal_pass)
    incl_partial = sum(1 for v in verdicts if v.final_verdict in ("PASS", "PARTIAL"))
    print(
        f"[verify_case_studies] {', '.join(summary_parts)} | "
        f"Literal PASS: {literal_pass}/{eligible} | "
        f"Including PARTIAL: {incl_partial}/{eligible} | "
        f"INVALID: {invalid_count}/{total}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
