---
name: write-read-verify-cycle
description: A fundamental data integrity pattern involving writing data to a persistent
  medium, reading it back, and performing a comparison to ensure accuracy.
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
source_task_id: T-78461a67
---

## 功能描述

A fundamental data integrity pattern involving writing data to a persistent medium, reading it back, and performing a comparison to ensure accuracy.

## 使用條件 (Iσ)

- When a task involves data persistence, file I/O, or state changes that must be confirmed.

## 終止條件 (βσ)

- The retrieved data matches the original input exactly.

## 執行策略 (πσ)

1. Write the target data to the specified destination
2. Read the data back from the destination into a temporary variable
3. Compare the retrieved data against the original source of truth
4. Report success or failure based on the comparison

## 來源

- 提取自 trace: T-78461a67
- 提取方式: A3 general extraction
- 信心度: 0.95
