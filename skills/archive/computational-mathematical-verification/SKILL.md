---
name: computational-mathematical-verification
description: Solve mathematical problems by implementing a programmatic verification
  function and applying it over a defined range.
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
source_task_id: T-0fa7c189
---

## 功能描述

Solve mathematical problems by implementing a programmatic verification function and applying it over a defined range.

## 使用條件 (Iσ)

- Task requires finding counts, sums, or properties of numbers within a specific range

## 終止條件 (βσ)

- The programmatic result is obtained and verified against the problem constraints

## 執行策略 (πσ)

1. Define a helper function to test the specific property (e.g., primality, parity, divisibility)
2. Implement a loop or generator expression to iterate through the target range
3. Aggregate the results (count, sum, or list) using the helper function
4. Return the final calculated value

## 來源

- 提取自 trace: T-0fa7c189
- 提取方式: A3 general extraction
- 信心度: 0.9
