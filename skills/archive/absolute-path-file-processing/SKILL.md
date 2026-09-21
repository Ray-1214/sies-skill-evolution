---
name: absolute-path-file-processing
description: Execute file operations by explicitly using absolute paths to ensure
  reliability regardless of the current working directory.
version: '1'
author: SIES-A3
tags: &id001
- software-engineering
- system-ops
tier: active
utility: 0.5
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-0d6a8dcb
---

## Description

Execute file operations by explicitly using absolute paths to ensure reliability regardless of the current working directory.

## Invocation Condition (Iσ)

- When working in environments where the current working directory is uncertain or when multiple specific directories are involved.

## Termination Condition (βσ)

- File operations (read/write/verify) are completed using the specified absolute paths.

## Strategy Steps (πσ)

1. Identify the required absolute directory paths from the task description
2. Verify the existence of input files using absolute paths
3. Construct full absolute paths for both input and output files in the implementation logic
4. Execute file transformations using these absolute paths

## Source

- Extracted from trace: T-0d6a8dcb
- Extraction method: A3 general extraction
- Confidence: 0.95
