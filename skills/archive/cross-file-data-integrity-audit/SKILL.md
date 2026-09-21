---
name: cross-file-data-integrity-audit
description: Verify data consistency between a source dataset and a processed report
  by calculating and comparing aggregate metrics.
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
source_task_id: T-ef30bc3a
---

## Description

Verify data consistency between a source dataset and a processed report by calculating and comparing aggregate metrics.

## Invocation Condition (Iσ)

- When a task requires ensuring that transformations or reports accurately reflect the original source data.

## Termination Condition (βσ)

- A comparison between source and target metrics is completed and the result is logged.

## Strategy Steps (πσ)

1. Identify and locate the source data file and the target report file
2. Develop a script to extract and aggregate key metrics (e.g., sums, counts) from both files
3. Compare the aggregated results to determine if they match within an acceptable tolerance
4. Record the audit outcome (SUCCESS/FAILURE) to a designated log file
5. Output the final status in the required format

## Source

- Extracted from trace: T-ef30bc3a
- Extraction method: A3 general extraction
- Confidence: 0.95
