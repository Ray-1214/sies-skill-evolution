---
name: requirement-driven-implementation
description: Implement a function by first decomposing complex requirements (like
  case-insensitivity or whitespace handling) into specific preprocessing and logic
  steps.
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
source_task_id: T-82a09c6b
---

## Description

Implement a function by first decomposing complex requirements (like case-insensitivity or whitespace handling) into specific preprocessing and logic steps.

## Invocation Condition (Iσ)

- When a task involves implementing a function with specific constraints or formatting rules

## Termination Condition (βσ)

- The implementation satisfies all specified constraints and passes initial tests

## Strategy Steps (πσ)

1. Decompose requirements into discrete logical components (e.g., preprocessing, core logic)
2. Implement a preprocessing step to normalize input data according to constraints
3. Develop the core algorithm on the normalized data
4. Verify the implementation against the original requirements

## Source

- Extracted from trace: T-82a09c6b
- Extraction method: A3 general extraction
- Confidence: 0.9
