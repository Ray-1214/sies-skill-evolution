---
name: multi-modal-data-reporting-workflow
description: Execute a data processing workflow that produces multiple output formats
  including visualizations, structured text summaries, and specific protocol-compliant
  console outputs.
version: '1'
author: SIES-A3
tags: &id001
- data-analysis
- content-creation
tier: active
utility: 0.5
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-5cc0c20c
---

## Description

Execute a data processing workflow that produces multiple output formats including visualizations, structured text summaries, and specific protocol-compliant console outputs.

## Invocation Condition (Iσ)

- Task requires transforming raw data into various artifacts like charts, text reports, and machine-readable strings.

## Termination Condition (βσ)

- All required artifacts (visual, textual, and protocol-specific) are generated and saved to the target directory.

## Strategy Steps (πσ)

1. Load and inspect the source data to confirm schema
2. Perform aggregations required for both visual and textual reports
3. Generate a visualization (e.g., matplotlib chart) and save to a file
4. Generate a text-based summary and save to a file
5. Output a specific, single-line machine-readable string for downstream parsing

## Source

- Extracted from trace: T-5cc0c20c
- Extraction method: A3 general extraction
- Confidence: 0.9
