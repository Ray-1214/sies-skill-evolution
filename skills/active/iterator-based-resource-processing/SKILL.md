---
name: iterator-based-resource-processing
description: Process large or unequal data streams using iterators and generators
  to maintain memory efficiency and handle mismatched lengths.
version: '1'
author: SIES-A3
tags: &id001
- software-engineering
- data-analysis
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

Process large or unequal data streams using iterators and generators to maintain memory efficiency and handle mismatched lengths.

## Invocation Condition (Iσ)

- Task involves merging, comparing, or processing multiple data sources (files, lists, streams) that may have different sizes.

## Termination Condition (βσ)

- All data sources are exhausted and the merged/processed output is produced.

## Strategy Steps (πσ)

1. Identify the core logic for combining data elements (e.g., interleaving, zipping, or appending)
2. Select an iterator-based tool (like itertools.zip_longest) to handle unequal lengths without loading everything into memory
3. Implement a generator or stream-based approach to process data line-by-line or element-by-element
4. Verify the logic with test cases covering equal and unequal input sizes

## Source

- Extracted from trace: T-747832fd
- Extraction method: A3 general extraction
- Confidence: 0.95
