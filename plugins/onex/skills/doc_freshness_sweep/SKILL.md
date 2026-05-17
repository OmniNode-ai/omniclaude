---
description: Scan documentation files across repos for broken references, stale content, and CLAUDE.md accuracy. Generates freshness reports and optionally creates Linear tickets for broken/stale docs.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: quality
tags:
  - documentation
  - freshness
  - scanning
  - quality
  - claude-md
  - cross-reference
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repo
    description: "Scan a single repo by name"
    required: false
  - name: --claude-md-only
    description: "Only check CLAUDE.md files (faster, used in close-out autopilot)"
    required: false
  - name: --broken-only
    description: "Only report broken references (skip stale)"
    required: false
  - name: --create-tickets
    description: "Create Linear tickets for broken/stale docs"
    required: false
  - name: --max-tickets
    description: "Max tickets to create per run (default: 10)"
    required: false
  - name: --dry-run
    description: "Report only, no ticket creation"
    required: false
---

# /onex:doc_freshness_sweep — Documentation Freshness Sweep

**Skill ID**: `onex:doc_freshness_sweep`
**Version**: 2.0.0
**Backing node**: `node_doc_freshness_sweep`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_doc_freshness_sweep`.

## What this skill does

Dispatches through `onex run-node node_doc_freshness_sweep`. The node owns repo
scanning, reference extraction, staleness detection, and ticket creation.
This shim contains no inline scanning logic.

**Announce at start:** "I'm using the doc-freshness-sweep skill."

## Dispatch

```bash
uv run onex run-node node_doc_freshness_sweep --input '{
  "repo": null,
  "claude_md_only": false,
  "broken_only": false,
  "create_tickets": false,
  "max_tickets": 10,
  "dry_run": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_doc_freshness_sweep`

Command topic: `onex.cmd.omnimarket.doc-freshness-sweep-start.v1`

Terminal event: `onex.evt.omnimarket.doc-freshness-sweep-completed.v1`
