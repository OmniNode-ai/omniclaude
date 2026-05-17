---
description: Orchestrate full Linear housekeeping — triage ticket status, organize orphans into epics, then sync MASTER_TICKET_PLAN.md. Human checkpoint between triage and apply.
mode: full
version: 2.0.0
level: intermediate
debug: false
category: workflow
tags:
  - linear
  - housekeeping
  - triage
  - epics
  - documentation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: --team
    description: "Linear team name to scope housekeeping (default: Omninode)"
    required: false
  - name: --dry-run
    description: "Report only, no mutations"
    required: false
---

# /onex:linear_housekeeping — Linear Housekeeping Orchestrator

**Skill ID**: `onex:linear_housekeeping`
**Version**: 2.0.0
**Backing node**: `node_linear_triage`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). Chains through node_linear_triage.
- **1.0.0** — Original skill.

## What this skill does

Dispatches through `onex run-node node_linear_triage`. The node owns full triage
(status sweep, orphan detection, epic organization, plan sync). This shim contains
no inline Linear query or mutation logic.

**Announce at start:** "I'm using the linear-housekeeping skill for a full ticket audit."

## Dispatch

```bash
uv run onex run-node node_linear_triage --input '{
  "team": "Omninode",
  "dry_run": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_linear_triage`

Command topic: `onex.cmd.omnimarket.linear-triage-start.v1`

Terminal event: `onex.evt.omnimarket.linear-triage-completed.v1`
