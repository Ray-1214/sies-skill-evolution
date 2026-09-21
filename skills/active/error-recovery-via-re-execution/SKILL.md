---
name: error-recovery-via-re-execution
description: When a tool execution or parsing error occurs, re-evaluate the state
  and re-execute the successful logic to ensure a clean final output.
version: '1'
author: SIES-A3
tags: &id001
- software-engineering
- planning
tier: active
utility: 0.5
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-4163614b
---

## 功能描述

When a tool execution or parsing error occurs, re-evaluate the state and re-execute the successful logic to ensure a clean final output.

## 使用條件 (Iσ)

- A previous step failed due to parsing errors or unexpected tool behavior despite logic being correct

## 終止條件 (βσ)

- The task is successfully completed or the error is bypassed through re-execution

## 執行策略 (πσ)

1. Identify if the failure was due to logic or a system/parsing error
2. If logic was correct but parsing failed, re-run the successful logic block
3. Verify the output of the re-executed step
4. Proceed to finish once a valid output is generated

## 來源

- 提取自 trace: T-4163614b
- 提取方式: A3 general extraction
- 信心度: 0.85
