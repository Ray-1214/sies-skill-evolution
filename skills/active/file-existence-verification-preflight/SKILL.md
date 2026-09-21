---
name: file-existence-verification-preflight
description: Verify the existence and path of input files using shell commands before
  attempting complex data processing to prevent runtime errors.
version: '1'
author: SIES-A3
tags: &id001
- system-ops
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
source_task_id: T-a2e68ca5
---

## Description

Verify the existence and path of input files using shell commands before attempting complex data processing to prevent runtime errors.

## Invocation Condition (Iσ)

- When a task involves reading files from specific, potentially volatile, or absolute directory paths.

## Termination Condition (βσ)

- The existence and accessibility of the target file are confirmed.

## Strategy Steps (πσ)

1. Identify the absolute path of the required input file
2. Use a shell command (e.g., ls, stat) to verify the file exists
3. Proceed to processing only after confirmation

## Source

- Extracted from trace: T-a2e68ca5
- Extraction method: A3 general extraction
- Confidence: 0.95
