---
name: exploratory-data-schema-discovery
description: Perform initial inspection of raw data files using shell commands to
  determine schema, data types, and file structure before writing processing logic.
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
source_task_id: T-e2ada571
---

## Description

Perform initial inspection of raw data files using shell commands to determine schema, data types, and file structure before writing processing logic.

## Invocation Condition (Iσ)

- When starting a task that involves processing unknown or semi-structured files

## Termination Condition (βσ)

- The schema and sample content of all input files are clearly understood

## Strategy Steps (πσ)

1. List directory contents to confirm file existence
2. Use 'head' or similar tools to inspect the first few rows of each file
3. Identify column names, delimiters, and data formats (e.g., timestamps, numeric types)
4. Map relationships between different input files (e.g., join keys)

## Source

- Extracted from trace: T-e2ada571
- Extraction method: A3 general extraction
- Confidence: 0.95
