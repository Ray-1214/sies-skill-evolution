---
name: integrated-script-development
description: Combine multiple distinct requirements (file I/O, system metadata retrieval,
  and data formatting) into a single, cohesive, and error-handled script.
version: '1'
author: SIES-A3
tags: &id001
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
source_task_id: T-4e22c192
---

## 功能描述

Combine multiple distinct requirements (file I/O, system metadata retrieval, and data formatting) into a single, cohesive, and error-handled script.

## 使用條件 (Iσ)

- When a task requires performing several different operations that can be logically grouped into one execution flow.

## 終止條件 (βσ)

- All sub-requirements are implemented, tested, and produce a unified output.

## 執行策略 (πσ)

1. Decompose the task into individual sub-requirements
2. Design a single script that handles each requirement sequentially
3. Implement robust error handling (e.g., try-except blocks) for external dependencies like file paths
4. Aggregate results into a structured summary format

## 來源

- 提取自 trace: T-4e22c192
- 提取方式: A3 general extraction
- 信心度: 0.9
