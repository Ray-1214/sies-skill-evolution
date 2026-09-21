---
name: data-serialization-roundtrip-verification
description: Implement functions for data serialization and deserialization, then
  verify integrity by performing a round-trip test (write then read) and asserting
  equality.
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
source_task_id: T-3db5923b
---

## Description

Implement functions for data serialization and deserialization, then verify integrity by performing a round-trip test (write then read) and asserting equality.

## Invocation Condition (Iσ)

- Task requires saving data to a persistent format and ensuring it can be retrieved without loss of information.

## Termination Condition (βσ)

- Data retrieved from storage matches the original input exactly through assertions.

## Strategy Steps (πσ)

1. Implement serialization logic (e.g., writing to JSON/CSV)
2. Implement deserialization logic (e.g., reading from JSON/CSV)
3. Include error handling for common I/O and parsing errors
4. Create a test case that writes data, reads it back, and uses assertions to verify equality

## Source

- Extracted from trace: T-3db5923b
- Extraction method: A3 general extraction
- Confidence: 0.95
