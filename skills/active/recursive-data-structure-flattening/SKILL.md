---
name: recursive-data-structure-flattening
description: Transform deeply nested hierarchical data structures into a flat key-value
  format using recursive traversal and key concatenation.
version: '1'
author: SIES-A3
tags: &id001
- data-analysis
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
source_task_id: T-e758e422
---

## Description

Transform deeply nested hierarchical data structures into a flat key-value format using recursive traversal and key concatenation.

## Invocation Condition (Iσ)

- When working with hierarchical formats like JSON, XML, or nested dictionaries that need to be converted into a single-level structure for easier processing or storage.

## Termination Condition (βσ)

- All nested levels have been traversed and mapped to a single-level dictionary with concatenated keys.

## Strategy Steps (πσ)

1. Define a recursive function that accepts the current object and a prefix string
2. Iterate through keys and values of the current object
3. If a value is a dictionary, call the function recursively with an updated prefix
4. If a value is a primitive, assign it to the flat dictionary using the accumulated prefix and current key
5. Return the final flattened dictionary

## Source

- Extracted from trace: T-e758e422
- Extraction method: A3 general extraction
- Confidence: 0.95
