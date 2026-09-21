---
name: integrated-implementation-and-test-suite
description: Develop a core logic function and a comprehensive unit test suite within
  a single execution cycle to ensure immediate verification.
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
source_task_id: T-e9906738
---

## Description

Develop a core logic function and a comprehensive unit test suite within a single execution cycle to ensure immediate verification.

## Invocation Condition (Iσ)

- When tasked with writing a specific function or algorithm that requires verification of correctness.

## Termination Condition (βσ)

- The implementation passes all defined unit tests, including edge cases.

## Strategy Steps (πσ)

1. Define the core logic using appropriate data structures to handle constraints (e.g., sets for uniqueness)
2. Construct a unit test suite covering standard inputs, duplicates, and edge cases
3. Execute both implementation and tests in a single environment
4. Verify test results before concluding the task

## Source

- Extracted from trace: T-e9906738
- Extraction method: A3 general extraction
- Confidence: 0.95
