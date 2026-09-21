---
name: test-driven-verification
description: Validate code correctness by running a series of expected input-output
  pairs through the implementation before finalizing.
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
source_task_id: T-4e2fc4c3
---

## 功能描述

Validate code correctness by running a series of expected input-output pairs through the implementation before finalizing.

## 使用條件 (Iσ)

- Task involves writing code that must adhere to specific logical rules

## 終止條件 (βσ)

- All test cases (standard, boundary, and edge cases) return expected results

## 執行策略 (πσ)

1. Identify key input categories (small primes, composites, edge cases like 0 or 1)
2. Execute the function against these inputs
3. Compare actual output against expected output
4. Iterate on the implementation if any test fails

## 來源

- 提取自 trace: T-4e2fc4c3
- 提取方式: A3 general extraction
- 信心度: 0.85
