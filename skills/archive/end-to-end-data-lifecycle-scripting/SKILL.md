---
name: end-to-end-data-lifecycle-scripting
description: 'Develop a single script that encapsulates the entire data lifecycle:
  generation, persistence to disk, retrieval, and conditional aggregation.'
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
source_task_id: T-08ac17e7
---

## Description

Develop a single script that encapsulates the entire data lifecycle: generation, persistence to disk, retrieval, and conditional aggregation.

## Invocation Condition (Iσ)

- Task involves multiple sequential stages of data handling (creation, storage, and analysis)

## Termination Condition (βσ)

- Data is successfully processed and the final aggregate result is verified

## Strategy Steps (πσ)

1. Define the data schema and storage location
2. Implement a generation phase to create sample/input data
3. Implement a persistence phase to write data to a file format (e.g., CSV)
4. Implement a retrieval phase to read the file back into memory
5. Apply conditional logic to the retrieved data to produce the required metric

## Source

- Extracted from trace: T-08ac17e7
- Extraction method: A3 general extraction
- Confidence: 0.9
