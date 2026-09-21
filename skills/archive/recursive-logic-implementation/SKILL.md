---
name: recursive-logic-implementation
description: Implement a mathematical or computational problem using a recursive function
  structure with a defined base case and recursive step.
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
source_task_id: T-9db51558
---

## Description

Implement a mathematical or computational problem using a recursive function structure with a defined base case and recursive step.

## Invocation Condition (Iσ)

- The problem can be broken down into smaller, identical sub-problems (e.g., factorials, Fibonacci, tree traversals).

## Termination Condition (βσ)

- The function correctly handles the base case and returns the expected value for the target input.

## Strategy Steps (πσ)

1. Define a function that accepts the target parameter
2. Establish a base case to prevent infinite recursion (e.g., n=0 or n=1)
3. Implement the recursive step where the function calls itself with a modified parameter
4. Execute the function with the specific input and print/return the result

## Source

- Extracted from trace: T-9db51558
- Extraction method: A3 general extraction
- Confidence: 0.95
