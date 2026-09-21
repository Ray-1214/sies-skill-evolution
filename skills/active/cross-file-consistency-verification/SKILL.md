---
name: cross-file-consistency-verification
description: Verify that summary statistics or aggregated metrics in one file accurately
  reflect the granular data contained in another file.
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
source_task_id: T-d4f1ca68
---

## Description

Verify that summary statistics or aggregated metrics in one file accurately reflect the granular data contained in another file.

## Invocation Condition (Iσ)

- When a task requires checking if a summary report, dashboard, or aggregate file matches the source of truth data.

## Termination Condition (βσ)

- A definitive PASS/FAIL status is determined by comparing calculated metrics against reported metrics.

## Strategy Steps (πσ)

1. Inspect the structure and content of both the source data file and the summary file
2. Implement a script to parse the source data and programmatically recalculate the expected aggregate metrics
3. Parse the summary file to extract the reported metrics using regex or string parsing
4. Compare the recalculated metrics with the reported metrics using a tolerance for floating-point errors
5. Log the comparison results and output a final status

## Source

- Extracted from trace: T-d4f1ca68
- Extraction method: A3 general extraction
- Confidence: 0.9
