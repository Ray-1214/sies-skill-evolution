---
name: relational-data-merging-pipeline
description: Execute a data integration workflow by loading multiple datasets, performing
  a relational join on a common key, and exporting the unified result.
version: '1'
author: SIES-A3
tags: &id001
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
source_task_id: T-30ab97ec
---

## Description

Execute a data integration workflow by loading multiple datasets, performing a relational join on a common key, and exporting the unified result.

## Invocation Condition (Iσ)

- Task requires combining information from two or more separate data sources based on a shared attribute.

## Termination Condition (βσ)

- The joined dataset is successfully written to a file and the resulting row count is verified.

## Strategy Steps (πσ)

1. Define absolute paths for all input and output files to ensure environment independence
2. Load datasets into a data manipulation framework (e.g., pandas)
3. Perform a relational join (left, right, inner, or outer) using a specified common key
4. Export the resulting dataset to the target destination
5. Verify the operation by reporting a summary metric (e.g., row count)

## Source

- Extracted from trace: T-30ab97ec
- Extraction method: A3 general extraction
- Confidence: 0.95
