---
name: separate-action-input-from-protocol
description: Action input must contain ONLY the executable command. Never embed protocol
  elements (Thought/Action/Observation headers) inside the tool input.
version: '1'
author: SIES-A3
tags: &id001
- software-engineering
- system-ops
tier: active
utility: 0.5
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: task_specific
linked_nodes: []
skill_source: a3_extraction
source_task_id: T-ab-05-markdown
---

## 功能描述

Action input must contain ONLY the executable command. Never embed protocol elements (Thought/Action/Observation headers) inside the tool input.

## 使用條件 (Iσ)

- Agent is using bash_execution or code_execution tools

## 終止條件 (βσ)

- Action input contains only the intended command with no protocol markup

## 執行策略 (πσ)

1. Before executing, verify action_input contains ONLY the command, no **Thought:**, **Action:**, **Observation:** text
2. If a tool returns errors about unknown commands that look like protocol headers, the action_input is contaminated
3. On repeated identical failures, change approach completely instead of retrying the same input

## 失敗根因

LLM embedded the entire ReAct protocol response (markdown Thought/Action/Observation markup) inside action_input, causing bash to execute markup headers as commands

## 來源

- 提取自 trace: T-ab-05-markdown
- 提取方式: A3 task_specific extraction
- 信心度: 0.95
