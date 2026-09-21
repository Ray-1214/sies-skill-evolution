---
name: test-driven-implementation-pattern
description: Develop a core function and immediately validate it using a comprehensive
  unit testing suite including edge cases.
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
source_task_id: T-747832fd
---

## Description

Develop a core function and immediately validate it using a comprehensive unit testing suite including edge cases.

## Invocation Condition (Iσ)

- When implementing a logic-heavy function or algorithm where correctness is critical.

## Termination Condition (βσ)

- All unit tests, including edge cases, pass successfully.

## Strategy Steps (πσ)

1. Define the function signature and core logic
2. Create a test suite using a framework like unittest
3. Include test cases for standard inputs, empty inputs, and mismatched input sizes
4. Execute tests and verify the output matches expected results

## Source

- Extracted from trace: T-747832fd
- Extraction method: A3 general extraction
- Confidence: 0.9
