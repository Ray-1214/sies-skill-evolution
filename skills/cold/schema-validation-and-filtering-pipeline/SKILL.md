---
name: schema-validation-and-filtering-pipeline
description: Implement a data processing pipeline that reads structured data, validates
  each entry against specific type and key constraints, filters out non-compliant
  records, and persists the cleaned dataset.
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
source_task_id: T-6cd0c89e
---

## Description

Implement a data processing pipeline that reads structured data, validates each entry against specific type and key constraints, filters out non-compliant records, and persists the cleaned dataset.

## Invocation Condition (Iσ)

- When tasked with cleaning or normalizing structured datasets (JSON, CSV, etc.) based on strict schema requirements.

## Termination Condition (βσ)

- Cleaned data is written to the target destination and a summary of processed records is provided.

## Strategy Steps (πσ)

1. Define the target schema with specific key names and expected data types (e.g., int, float)
2. Load the source data into a traversable structure
3. Iterate through the collection, applying a validation check for both key existence and type correctness
4. Collect valid records into a new collection
5. Write the valid collection to a new file using the specified path
6. Output a summary metric (e.g., count of valid rows)

## Source

- Extracted from trace: T-6cd0c89e
- Extraction method: A3 general extraction
- Confidence: 0.95
