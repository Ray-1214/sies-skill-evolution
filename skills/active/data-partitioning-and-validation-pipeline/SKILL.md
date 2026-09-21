---
name: data-partitioning-and-validation-pipeline
description: Process a dataset by validating individual records against specific type
  and presence constraints, then segregating them into separate files based on validity.
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
source_task_id: T-b032f2be
---

## Description

Process a dataset by validating individual records against specific type and presence constraints, then segregating them into separate files based on validity.

## Invocation Condition (Iσ)

- When a task requires filtering a dataset into 'valid' and 'invalid' subsets based on schema rules.

## Termination Condition (βσ)

- Data is successfully partitioned into designated files and summary statistics are produced.

## Strategy Steps (πσ)

1. Define strict validation rules for each field (e.g., type checking, existence)
2. Iterate through the source dataset once
3. Apply validation logic to each record
4. Append valid records to a success collection and invalid records to a failure collection
5. Write collections to their respective destination files
6. Output a summary count of the processed valid records

## Source

- Extracted from trace: T-b032f2be
- Extraction method: A3 general extraction
- Confidence: 0.95
