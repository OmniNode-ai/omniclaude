---
description: Measure test coverage across all Python repos under omni_home, flag modules below threshold, and auto-create Linear tickets for coverage gaps
version: 4.0.0
mode: full
level: intermediate
debug: false
category: quality
tags:
  - coverage
  - testing
  - automation
  - linear
  - org-wide
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names to scan (default: all Python repos)"
    required: false
  - name: --target
    description: "Coverage target percentage (default: 50)"
    required: false
  - name: --dry-run
    description: Scan and report only -- no ticket creation
    required: false
  - name: --max-tickets
    description: "Maximum tickets to create per run (default: 20)"
    required: false
  - name: --force-rescan
    description: Ignore cache and re-run coverage scans
    required: false
---

# /onex:coverage_sweep — Test Coverage Sweep

**Skill ID**: `onex:coverage_sweep`
**Version**: 4.0.0
**Backing node**: `node_coverage_sweep`

## Changelog

- **4.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_coverage_sweep`.

## What this skill does

Dispatches through `onex run-node node_coverage_sweep`. The node owns repo discovery,
coverage measurement, gap detection, and ticket creation. This shim contains no
inline coverage logic.

**Announce at start:** "I'm using the coverage-sweep skill."

## Dispatch

```bash
uv run onex run-node node_coverage_sweep --input '{
  "repos": null,
  "target": 50,
  "dry_run": false,
  "max_tickets": 20,
  "force_rescan": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_coverage_sweep`

Command topic: `onex.cmd.omnimarket.coverage-sweep-start.v1`

Terminal events:
- `onex.evt.omnimarket.coverage-sweep-gap.v1`
- `onex.evt.omnimarket.coverage-sweep-completed.v1`
