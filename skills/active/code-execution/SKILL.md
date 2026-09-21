---
name: code-execution
description: "Write and execute Python/Shell scripts to solve computation, automation, data processing, and API interaction tasks. Use when precise calculation, repetitive operations, or programmatic solutions are needed."
version: "1"
author: "SIES"
tags: [engineering, automation, programming]
tier: active
utility: 0.50
frequency: 0
reinforcement: 0.00
cost: 0.20
domain: [engineering, automation]
type: general
linked_nodes:
  - target: file-io
    relation: sequential
    weight: 0.70
  - target: data-analysis
    relation: parallel
    weight: 0.45
---

## Description

Write Python or Shell scripts to solve tasks requiring computation, data transformation, API calls, or file operations. Leverages agent-zero's code_execution_tool to run code safely in a Docker sandbox. Agent-zero automatically creates subordinate agents for complex multi-step programming tasks.

## Initiation Conditions (Iσ)

- Task requires precise calculation or data transformation (LLM reasoning unreliable)
- Need to interact with external APIs (REST calls, database queries)
- Task involves repetitive operations (batch processing, automation scripts)
- Need to generate or modify code files

## Termination Conditions (βσ)

- Success: Code executes to completion with expected output (no uncaught exceptions)
- Failure: 3 fix iterations still produce runtime errors or output clearly wrong

## Execution Policy (πσ)

1. Analyze requirements, choose language (Python default, Shell for system ops)
2. Design program architecture (function decomposition, I/O format)
3. Write code using agent-zero's code_execution tool
4. Execute in Docker sandbox
5. Check output; if error, analyze error type and fix (max 3 iterations)
6. For complex tasks, delegate to subordinate agents (agent-zero hierarchy)

## Tool Dependencies

- `code_execution`: agent-zero core tool, supports Python/Shell/Node.js
- `communication`: for coordinating with subordinate agents on complex tasks

## Graph Neighbors

- → file-io: execution results often need to be persisted to files
- ⇄ data-analysis: data analysis often requires code, and vice versa
- ← web-search: code snippets or APIs found online need execution verification

## Failure Lessons

(No historical lessons yet)

## Version History

- v1: Initial creation (manual)
