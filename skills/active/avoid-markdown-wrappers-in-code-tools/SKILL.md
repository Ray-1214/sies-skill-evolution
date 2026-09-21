---
name: avoid-markdown-wrappers-in-code-tools
description: Do not include Markdown code fences (e.g., ```python) inside the input
  of a code execution tool. The tool expects raw source code only.
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

Do not include Markdown code fences (e.g., ```python) inside the input of a code execution tool. The tool expects raw source code only.

## 使用條件 (Iσ)

- When using code_execution or any tool that executes a programming language directly

## 終止條件 (βσ)

- The code executes successfully without SyntaxError related to non-code characters

## 執行策略 (πσ)

1. Strip all Markdown formatting (```python, ```) from the code string before passing it to the tool
2. Verify that the first character of the tool input is a valid code character (e.g., a letter, digit, or comment symbol)
3. If a SyntaxError occurs on line 1, check for hidden formatting characters

## 失敗根因

The agent included Markdown syntax (```python) within the tool's action input, causing the Python interpreter to fail on the first line.

## 來源

- 提取自 trace: T-ab-03-markdown
- 提取方式: A3 task_specific extraction
- 信心度: 1.0
