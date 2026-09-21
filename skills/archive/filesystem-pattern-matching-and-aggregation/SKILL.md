---
name: filesystem-pattern-matching-and-aggregation
description: Identify specific file types within a directory structure and perform
  quantitative analysis on the results.
version: '1'
author: SIES-A3
tags: &id001
- system-ops
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
source_task_id: T-76608f90
---

## 功能描述

Identify specific file types within a directory structure and perform quantitative analysis on the results.

## 使用條件 (Iσ)

- When a task requires finding files based on extensions, patterns, or names and calculating statistics about them.

## 終止條件 (βσ)

- A complete list of matching files and their total count is provided.

## 執行策略 (πσ)

1. Identify the target directory and file pattern (e.g., extension)
2. Use a filesystem library or shell command to scan for matches
3. Aggregate the results into a list and calculate the total count
4. Handle cases where no matches are found to avoid errors

## 來源

- 提取自 trace: T-76608f90
- 提取方式: A3 general extraction
- 信心度: 0.95
