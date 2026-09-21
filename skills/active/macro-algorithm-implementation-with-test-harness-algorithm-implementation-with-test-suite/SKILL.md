---
name: macro-algorithm-implementation-with-test-harness-algorithm-implementation-with-test-suite
description: Macro-skill composed of 'algorithm-implementation-with-test-harness'
  and 'algorithm-implementation-with-test-suite'. These two skills frequently co-occur
  in successful traces (support=0.48, lift=1.92) and are merged into a single composite
  skill.
version: '1'
author: SIES-Phi-iii
tags: &id001
- software-engineering
tier: active
utility: 0.3488
frequency: 0
reinforcement: 0.0
cost: 0.0
domain: *id001
type: general
linked_nodes: []
skill_source: phi_iii_contraction
parent_skills:
- algorithm-implementation-with-test-harness
- algorithm-implementation-with-test-suite
---

<!-- Generated from contraction of: [algorithm-implementation-with-test-harness, algorithm-implementation-with-test-suite] on 2026-04-28T23:43:44.857413+08:00 (support=0.48, lift=1.92) -->

## Description

This macro-skill combines 'algorithm-implementation-with-test-harness' and 'algorithm-implementation-with-test-suite'. Use it when both component skills would naturally apply.

---

## Component Skill A: algorithm-implementation-with-test-harness

## 功能描述

Implement a core algorithm and immediately wrap it in a test harness that checks multiple inputs (including edge cases) to verify correctness.

## 使用條件 (Iσ)

- Task requires implementing a specific algorithm or logic function

## 終止條件 (βσ)

- The algorithm passes a suite of test cases including standard and boundary values

## 執行策略 (πσ)

1. Define the core logic/algorithm function
2. Create a test suite that iterates through multiple target values
3. Compare actual results against expected results for each test case
4. Report status (PASS/FAIL) for each test case

## 來源

- 提取自 trace: T-4163614b
- 提取方式: A3 general extraction
- 信心度: 0.95

---

## Component Skill B: algorithm-implementation-with-test-suite

## 功能描述

Implement a specific algorithm and immediately follow it with a structured test suite that verifies multiple scenarios (success, boundary, and failure cases).

## 使用條件 (Iσ)

- Task requires writing a specific function, algorithm, or logic component.

## 終止條件 (βσ)

- The implementation is verified against multiple test cases including boundary conditions.

## 執行策略 (πσ)

1. Define the core logic of the algorithm with appropriate documentation
2. Create a test harness that compares actual results against expected outputs
3. Test multiple scenarios: middle elements, boundary elements (start/end), and missing elements
4. Report status (PASS/FAIL) for each test case

## 來源

- 提取自 trace: T-2df9132e
- 提取方式: A3 general extraction
- 信心度: 0.95
