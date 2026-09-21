---
name: data-validation-and-cleaning-pipeline
description: 'A systematic approach to processing structured data: inspect schema,
  validate field types, filter incomplete records, and export cleaned results.'
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
source_task_id: T-5592d2b8
---

## Description

A systematic approach to processing structured data: inspect schema, validate field types, filter incomplete records, and export cleaned results.

## Invocation Condition (Iσ)

- When tasked with cleaning or transforming structured datasets (JSON, CSV, etc.)

## Termination Condition (βσ)

- Data is validated, filtered, and written to a new destination with a summary of results.

## Strategy Steps (πσ)

1. Inspect the input file to confirm existence and understand the schema/structure
2. Sample the data to verify expected data types (e.g., int, float, str)
3. Implement validation logic to check for type correctness and presence of required fields
4. Filter out records that fail validation or contain missing values
5. Write the sanitized dataset to a new file using absolute paths
6. Output a summary metric (e.g., count of processed items) to confirm completion

## Source

- Extracted from trace: T-5592d2b8
- Extraction method: A3 general extraction
- Confidence: 0.95
