---
name: algorithm-implementation-with-test-harness
description: Implement a core algorithm and immediately wrap it in a test harness
  that checks multiple inputs (including edge cases) to verify correctness.
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
source_task_id: T-4163614b
---

## 功能描述

Implement a core algorithm and immediately wrap it in a test harness that checks multiple inputs (including edge cases) to verify correctness.

## 使用條件 (Iσ)

- Task requires implementing a specific algorithm or logic function

## 終止條件 (βσ)

- The algorithm passes a suite of test cases including standard and boundary values

## 執行策略 (πσ)

1. Define the core logic/algorithm function
2. Create a test suite that iterates through multiple target values
3. Compare actual results against expected results for each test case
4. Report status (PASS/FAIL) for each test case

## 來源

- 提取自 trace: T-4163614b
- 提取方式: A3 general extraction
- 信心度: 0.95
