---
name: macro-algorithm-implementation-with-automated-verification-algorithm-implementation-with-validation-suite
description: Macro-skill composed of 'algorithm-implementation-with-automated-verification'
  and 'algorithm-implementation-with-validation-suite'. These two skills frequently
  co-occur in successful traces (support=0.32, lift=3.09) and are merged into a single
  composite skill.
version: '1'
author: SIES-Phi-iii
tags: &id001
- software-engineering
tier: active
utility: 0.2994
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: phi_iii_contraction
parent_skills:
- algorithm-implementation-with-automated-verification
- algorithm-implementation-with-validation-suite
---

<!-- Generated from contraction of: [algorithm-implementation-with-automated-verification, algorithm-implementation-with-validation-suite] on 2026-05-17T09:30:09.708360+08:00 (support=0.32, lift=3.09) -->

## Description

This macro-skill combines 'algorithm-implementation-with-automated-verification' and 'algorithm-implementation-with-validation-suite'. Use it when both component skills would naturally apply.

---

## Component Skill A: algorithm-implementation-with-automated-verification

## Description

Implement a core algorithm and immediately follow it with a test suite that validates the logic across varying input scales and edge cases.

## Invocation Condition (Iσ)

- Task requires implementing a specific algorithm or data structure

## Termination Condition (βσ)

- Algorithm is implemented and passes tests for multiple input sizes/scenarios

## Strategy Steps (πσ)

1. Implement the core logic of the algorithm
2. Develop a test utility to generate diverse test cases (e.g., varying list sizes, edge cases)
3. Execute the test suite to verify correctness across all generated scenarios
4. Summarize implementation details and verification results

## Source

- Extracted from trace: T-49708acd
- Extraction method: A3 general extraction
- Confidence: 0.95

---

## Component Skill B: algorithm-implementation-with-validation-suite

## Description

Implement a specific algorithm and immediately validate it against a diverse suite of test cases including edge cases.

## Invocation Condition (Iσ)

- Task requires implementing a specific logic, algorithm, or data structure from scratch.

## Termination Condition (βσ)

- Algorithm is implemented and passes all required test scenarios.

## Strategy Steps (πσ)

1. Implement the core logic of the algorithm
2. Incorporate optimizations if applicable (e.g., early exit flags)
3. Define a test suite covering standard, edge (empty/null), and boundary (reversed/sorted) cases
4. Execute tests and verify outputs against expected results

## Source

- Extracted from trace: T-137ab363
- Extraction method: A3 general extraction
- Confidence: 0.95
