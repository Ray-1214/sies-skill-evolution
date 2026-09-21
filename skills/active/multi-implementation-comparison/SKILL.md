---
name: multi-implementation-comparison
description: Implement multiple distinct approaches to solve the same problem to provide
  options and verify consistency.
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
source_task_id: T-78a50d3b
---

## 功能描述

Implement multiple distinct approaches to solve the same problem to provide options and verify consistency.

## 使用條件 (Iσ)

- When a task requires a specific functionality that can be achieved through different algorithmic or syntactic methods.

## 終止條件 (βσ)

- Multiple valid implementations are provided and their outputs are compared.

## 執行策略 (πσ)

1. Identify different ways to solve the problem (e.g., slicing vs. iterative vs. built-in functions)
2. Implement each version independently
3. Execute all versions with the same input to verify identical results
4. Present the different approaches to the user

## 來源

- 提取自 trace: T-78a50d3b
- 提取方式: A3 general extraction
- 信心度: 0.9
