---
name: algorithm-implementation-with-automated-verification
description: Implement a core algorithm and immediately follow it with a test suite
  that validates the logic across varying input scales and edge cases.
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
source_task_id: T-49708acd
---

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
