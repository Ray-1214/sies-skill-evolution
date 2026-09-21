---
name: prevent-protocol-leakage-into-tool-input
description: Ensure that the tool input contains only the executable content. Never
  include 'Observation:', 'Thought:', or other ReAct protocol headers inside the tool
  call.
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
type: task_specific
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-ab-03-markdown
---

## 功能描述

Ensure that the tool input contains only the executable content. Never include 'Observation:', 'Thought:', or other ReAct protocol headers inside the tool call.

## 使用條件 (Iσ)

- When the agent is constructing a tool call that requires a specific script or command

## 終止條件 (βσ)

- The tool input contains only the logic required to solve the task, with no meta-commentary or protocol headers

## 執行策略 (πσ)

1. Review the tool input to ensure it does not contain text intended for the agent's own thought process
2. Separate the 'what to do' (logic) from the 'what happened' (observation) by ensuring the tool only receives the former
3. On repeated SyntaxErrors, check if the error message points to non-code text like '**Observation:**'

## 失敗根因

The agent attempted to include its own expected output/observations (e.g., '**Observation:**') inside the Python script, leading to syntax errors.

## 來源

- 提取自 trace: T-ab-03-markdown
- 提取方式: A3 task_specific extraction
- 信心度: 0.95
