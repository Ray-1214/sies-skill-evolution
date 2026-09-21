---
name: data-analysis
description: "Analyze structured and unstructured data to extract patterns, trends, and statistical insights. Use when tasks involve datasets, statistics, trend detection, or data visualization."
version: "1"
author: "SIES"
tags: [analysis, statistics, data-science]
tier: active
utility: 0.50
frequency: 0
reinforcement: 0.00
cost: 0.18
domain: [analysis, research]
type: general
linked_nodes:
  - target: text-summary
    relation: sequential
    weight: 0.50
---

## Description

Analyze structured data (CSV, JSON, database query results) or unstructured data (text corpora) to extract statistical summaries, trend changes, anomaly detection, and correlation insights. Results are typically passed to text-summary for report generation.

## Initiation Conditions (Iσ)

- Task input contains datasets requiring analysis (tables, numerical data, time series)
- Need to derive conclusions or discover patterns from data
- Need to compare differences across multiple datasets
- Need to visualize data trends

## Termination Conditions (βσ)

- Success: Concrete verifiable analysis conclusions produced (with data evidence), charts generated if needed
- Failure: Data quality too poor for meaningful conclusions, or results contradict known facts

## Execution Policy (πσ)

1. Load data (pandas DataFrame as primary format)
2. Data quality check: missing value ratio, data types, outlier detection
3. Descriptive statistics: mean, median, std, percentiles, value_counts
4. Advanced analysis as needed (correlation, clustering, trend lines, hypothesis testing)
5. Generate visualization charts (matplotlib/seaborn)
6. Write structured conclusion: {findings: [...], confidence: 0-1, charts: [...]}

## Tool Dependencies

- `code_execution`: pandas, numpy, matplotlib, seaborn

## Graph Neighbors

- → text-summary: analysis conclusions need to be consolidated into readable reports
- ← web-search: raw data from search needs structured analysis
- ← file-io: datasets read from files enter the analysis pipeline

## Failure Lessons

(No historical lessons yet)

## Version History

- v1: Initial creation (manual)
