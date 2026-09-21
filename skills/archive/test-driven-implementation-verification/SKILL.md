---
name: test-driven-implementation-verification
description: Implement a core logic function and immediately validate it against multiple
  diverse test cases including edge cases.
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
source_task_id: T-2819339e
---

## Description

Implement a core logic function and immediately validate it against multiple diverse test cases including edge cases.

## Invocation Condition (Iσ)

- When writing a new function or algorithm that requires high reliability.

## Termination Condition (βσ)

- The implementation passes all predefined test cases, including boundary conditions.

## Strategy Steps (πσ)

1. Develop the core logic based on requirements
2. Define a suite of test cases (standard, edge, and boundary cases)
3. Execute tests and compare actual output against expected output
4. Refine implementation if any test case fails

## Source

- Extracted from trace: T-2819339e
- Extraction method: A3 general extraction
- Confidence: 0.9
