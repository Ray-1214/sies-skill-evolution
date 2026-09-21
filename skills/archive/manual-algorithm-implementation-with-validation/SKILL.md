---
name: manual-algorithm-implementation-with-validation
description: Implement a core logic manually by avoiding high-level built-ins, followed
  by a structured test suite covering various data distributions.
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
source_task_id: T-189b1aeb
---

## 功能描述

Implement a core logic manually by avoiding high-level built-ins, followed by a structured test suite covering various data distributions.

## 使用條件 (Iσ)

- When a task requires implementing a fundamental algorithm or logic without relying on standard library shortcuts.

## 終止條件 (βσ)

- The implementation passes a suite of tests including positive, negative, and edge case scenarios.

## 執行策略 (πσ)

1. Define the core logic using basic control structures (loops, conditionals)
2. Identify and implement handling for edge cases (e.g., empty inputs, single-element lists)
3. Develop a test suite covering diverse data patterns (ascending, descending, mixed signs)
4. Verify the custom implementation against expected outputs

## 來源

- 提取自 trace: T-189b1aeb
- 提取方式: A3 general extraction
- 信心度: 0.95
