---
name: atomic-file-operation-verification
description: Execute a sequence of file operations (write, read, and compare) within
  a single execution block to ensure atomicity and immediate verification of data
  integrity.
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
source_task_id: T-6d6a2505
---

## 功能描述

Execute a sequence of file operations (write, read, and compare) within a single execution block to ensure atomicity and immediate verification of data integrity.

## 使用條件 (Iσ)

- When a task requires creating a file and ensuring its contents are correctly persisted.

## 終止條件 (βσ)

- The read content matches the original input and the operation is confirmed successful.

## 執行策略 (πσ)

1. Define the target file path and the expected content
2. Implement a write operation using a context manager to ensure proper file closure
3. Immediately perform a read operation on the same path
4. Compare the retrieved content against the original content using conditional logic
5. Report the success or failure of the verification

## 來源

- 提取自 trace: T-6d6a2505
- 提取方式: A3 general extraction
- 信心度: 0.95
