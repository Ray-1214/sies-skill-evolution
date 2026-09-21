---
name: iterative-optimization-pattern
description: Progress from a naive, readable implementation to more efficient and
  idiomatic code versions.
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
source_task_id: T-36cf027b
---

## 功能描述

Progress from a naive, readable implementation to more efficient and idiomatic code versions.

## 使用條件 (Iσ)

- When implementing a logic-based function or algorithm

## 終止條件 (βσ)

- An optimized version is implemented and verified against the baseline

## 執行策略 (πσ)

1. Develop a 'brute-force' or highly explicit version to establish correctness
2. Identify bottlenecks or verbosity in the initial version
3. Refactor using language-specific optimizations (e.g., step parameters in range, comprehensions)
4. Validate that the optimized version produces identical output to the baseline

## 來源

- 提取自 trace: T-36cf027b
- 提取方式: A3 general extraction
- 信心度: 0.9
