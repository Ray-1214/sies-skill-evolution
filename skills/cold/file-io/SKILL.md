---
name: file-io
description: "Read, write, convert file formats, and manage project file structures. Use when tasks involve file operations, format conversions (CSV/JSON/YAML), or directory management."
version: "1"
author: "SIES"
tags: [engineering, data, file-management]
tier: active
utility: 0.50
frequency: 0
reinforcement: 0.00
cost: 0.08
domain: [engineering, data]
type: general
linked_nodes:
  - target: data-analysis
    relation: sequential
    weight: 0.45
---

## Description

Handle file read/write operations, format conversions (CSV↔JSON, TXT→MD, etc.), directory management, and file content search. This skill serves as infrastructure for other skills, providing persistent data access capabilities.

## Initiation Conditions (Iσ)

- Task requires reading specific format input files
- Need to persist processing results as files
- Need to manage or reorganize directory structures
- Need to search for specific content across many files

## Termination Conditions (βσ)

- Success: File operation complete, output file exists and is readable with correct format
- Failure: File not found, permission denied, format parsing error, or disk space exhausted

## Execution Policy (πσ)

1. Confirm target file path and required operation (read/write/convert/search)
2. Check file existence and permissions
3. Choose appropriate tool (Python pathlib/json/csv/yaml modules)
4. Execute operation; for writes, use temp file + rename pattern (prevent corruption)
5. Validate output: file size > 0, format is parseable

## Tool Dependencies

- `code_execution`: Python standard library for file operations

## Graph Neighbors

- → data-analysis: data files are read then analyzed
- ← code-execution: code execution results often need file persistence

## Failure Lessons

(No historical lessons yet)

## Version History

- v1: Initial creation (manual)
