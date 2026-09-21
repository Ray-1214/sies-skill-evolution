---
name: algorithm-implementation-with-test-suite
description: Implement a specific algorithm and immediately follow it with a structured
  test suite that verifies multiple scenarios (success, boundary, and failure cases).
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
source_task_id: T-2df9132e
---

## 功能描述

Implement a specific algorithm and immediately follow it with a structured test suite that verifies multiple scenarios (success, boundary, and failure cases).

## 使用條件 (Iσ)

- Task requires writing a specific function, algorithm, or logic component.

## 終止條件 (βσ)

- The implementation is verified against multiple test cases including boundary conditions.

## 執行策略 (πσ)

1. Define the core logic of the algorithm with appropriate documentation
2. Create a test harness that compares actual results against expected outputs
3. Test multiple scenarios: middle elements, boundary elements (start/end), and missing elements
4. Report status (PASS/FAIL) for each test case

## 來源

- 提取自 trace: T-2df9132e
- 提取方式: A3 general extraction
- 信心度: 0.95
