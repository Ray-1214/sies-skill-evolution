---
name: self-contained-functional-verification
description: Implement a core logic function and immediately verify it by generating
  a controlled, synthetic test environment.
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
source_task_id: T-30012234
---

## Description

Implement a core logic function and immediately verify it by generating a controlled, synthetic test environment.

## Invocation Condition (Iσ)

- When developing a new utility function that requires validation against specific requirements.

## Termination Condition (βσ)

- The function produces the expected output when run against a manually verified sample input.

## Strategy Steps (πσ)

1. Develop the core logic based on functional requirements
2. Create a temporary/synthetic input file or data structure that mimics real-world usage
3. Execute the function against the synthetic input
4. Compare the actual output against a manually calculated expected result

## Source

- Extracted from trace: T-30012234
- Extraction method: A3 general extraction
- Confidence: 0.9
