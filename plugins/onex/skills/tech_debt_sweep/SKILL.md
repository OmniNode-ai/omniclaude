---
description: Scan all Python repos for tech debt, deduplicate against existing tickets, create Linear epics and tickets by category
mode: full
version: "1.0.0"
level: advanced
debug: false
category: observability
tags: [tech-debt, code-quality, linear, sweep]
author: omninode
args:
  - name: repo
    description: "Scan a single repo only (e.g., omnibase_infra). Default: all Python repos"
    required: false
  - name: categories
    description: "Comma-separated category filter (e.g., type-ignore,skipped-tests). Default: all 6"
    required: false
  - name: dry_run
    description: "If true, report findings without creating tickets (default: false)"
    required: false
  - name: project
    description: "Linear project for new tickets (default: Active Sprint)"
    required: false
---

# Tech Debt Sweep

Scans all Python repos under `omni_home` for 6 categories of tech debt, deduplicates
findings against existing open Linear tickets, and creates one epic per category with
closeable tickets grouped by repo and top-level source directory.

**Announce at start:** "I'm using the tech-debt-sweep skill to scan for tech debt."

## Runtime Model

This skill is implemented as prompt-driven orchestration, not executable Python.
Python blocks in this document are pseudocode specifying logic and data shape, not
callable runtime helpers. The LLM executes the equivalent logic through Grep, Bash,
and Linear MCP tool calls, holding intermediate state in its working context.

## Usage

```
/tech-debt-sweep
/tech-debt-sweep --repo omnibase_infra
/tech-debt-sweep --categories type-ignore,skipped-tests
/tech-debt-sweep --dry_run true
/tech-debt-sweep --repo omnibase_infra --categories type-ignore --dry_run true
```
