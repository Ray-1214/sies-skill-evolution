---
name: web-search
description: "Search the web for real-time information, verify facts, and gather multi-source perspectives. Use when the task requires external up-to-date data or cross-validation of claims."
version: "1"
author: "SIES"
tags: [research, information-retrieval, real-time]

# Paper Definition 2 extended fields (ignored by agent-zero, used by SIES evolution engine)
tier: active
utility: 0.50
frequency: 0
reinforcement: 0.00
cost: 0.15
domain: [research, analysis]
type: general
linked_nodes:
  - target: data-analysis
    relation: sequential
    weight: 0.60
  - target: text-summary
    relation: sequential
    weight: 0.55
  - target: code-execution
    relation: sequential
    weight: 0.40
---

## Description

Search the web for the latest information, verify facts, or collect multiple perspectives on a topic. This skill is the entry point for most research tasks. Results are typically passed to data-analysis or text-summary for downstream processing.

## Initiation Conditions (Iσ)

- Task requires external real-time information (events after knowledge cutoff)
- Local knowledge base or working memory is insufficient
- Cross-validation from multiple independent sources is needed

## Termination Conditions (βσ)

- Success: Target information found with ≥2 independent source cross-validation
- Failure: 3+ search iterations yield no relevant results or all results contradict each other

## Execution Policy (πσ)

1. Extract 2-3 key search queries from the task description (try both English and task-language)
2. Execute search using agent-zero's knowledge tool (SearXNG backend)
3. Evaluate source credibility for each result (official > academic > news > forum)
4. Extract key facts and annotate with source URLs
5. If results are insufficient, refine keywords and retry (max 3 rounds)
6. Output structured summary: {facts: [...], sources: [...], confidence: 0-1}

## Tool Dependencies

- `knowledge`: agent-zero built-in SearXNG search tool
- `code_execution`: if full page content scraping is needed

## Graph Neighbors

- → data-analysis: raw data often needs structured analysis after retrieval
- → text-summary: multiple search results need consolidation
- → code-execution: code snippets or APIs found need execution verification

## Failure Lessons

(No historical lessons yet)

## Version History

- v1: Initial creation (manual)
