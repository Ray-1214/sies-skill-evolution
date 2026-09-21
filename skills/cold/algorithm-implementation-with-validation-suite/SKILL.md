---
name: algorithm-implementation-with-validation-suite
description: Implement a specific algorithm and immediately validate it against a
  diverse suite of test cases including edge cases.
version: '1'
author: SIES-A3
tags: &id001
- software-engineering
tier: active
utility: 0.5
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-137ab363
---

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
