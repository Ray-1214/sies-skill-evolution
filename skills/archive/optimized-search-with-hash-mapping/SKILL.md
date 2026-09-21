---
name: optimized-search-with-hash-mapping
description: Implement search or lookup problems by utilizing hash maps (dictionaries)
  to reduce time complexity from quadratic to linear.
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
source_task_id: T-537b65eb
---

## Description

Implement search or lookup problems by utilizing hash maps (dictionaries) to reduce time complexity from quadratic to linear.

## Invocation Condition (Iσ)

- When searching for pairs, complements, or specific values within a collection where performance is a concern.

## Termination Condition (βσ)

- A functional implementation is verified against multiple test cases.

## Strategy Steps (πσ)

1. Identify the target relationship (e.g., sum, difference, or equality)
2. Initialize a hash map to store visited elements and their indices
3. Iterate through the collection once, checking if the complement of the current element exists in the map
4. If found, return the indices; otherwise, add the current element to the map

## Source

- Extracted from trace: T-537b65eb
- Extraction method: A3 general extraction
- Confidence: 0.95
