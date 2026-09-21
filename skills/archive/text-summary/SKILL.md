---
name: text-summary
description: "Summarize, consolidate, and rewrite text content into structured reports or concise summaries. Use when the final deliverable is a written document, report, email, or condensed overview."
version: "1"
author: "SIES"
tags: [research, creative, writing]
tier: active
utility: 0.50
frequency: 0
reinforcement: 0.00
cost: 0.12
domain: [research, creative]
type: general
linked_nodes: []
---

## Description

Consolidate long texts, multi-source data, and analysis conclusions into structured summaries or reports. This skill often serves as the final step in a task chain, compressing outputs from previous skills into a human-readable deliverable.

## Initiation Conditions (Iσ)

- Need to compress large amounts of text to a specified length
- Need to consolidate information from multiple sources into a unified report
- Need to rewrite technical content for a specific audience
- Final deliverable is a text document (report/email/documentation)

## Termination Conditions (βσ)

- Success: Summary contains all key information, meets length requirements, logically coherent
- Failure: Missing key information, too long/short, introduces factual errors not in source

## Execution Policy (πσ)

1. Inventory all input materials (outputs from multiple skills, raw documents, search results)
2. Extract 3-5 core points from each material
3. Deduplicate and consolidate: merge overlapping points, flag conflicting information
4. Organize by logical structure (chronological / importance / causal chain)
5. Draft within target length ±10%
6. Self-review: factual accuracy, logical coherence, key point coverage

## Tool Dependencies

- Primarily relies on LLM capabilities, usually no external tools needed
- `code_execution`: if handling very long texts (segment-then-merge strategy)

## Graph Neighbors

- ← web-search: multiple search results need summary consolidation
- ← data-analysis: analysis conclusions need to be written as readable reports

## Failure Lessons

(No historical lessons yet)

## Version History

- v1: Initial creation (manual)
