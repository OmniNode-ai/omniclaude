---
description: Batch create Linear tickets from a plan markdown file - parses phases/milestones, creates epic if needed, links dependencies
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - linear
  - tickets
  - planning
  - batch
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: plan-file
    description: Path to plan markdown file
    required: true
  - name: --project
    description: Linear project name
    required: false
  - name: --epic-title
    description: Title for epic (overrides auto-detection from plan)
    required: false
  - name: --no-create-epic
    description: Fail if epic doesn't exist (don't auto-create)
    required: false
  - name: --dry-run
    description: Show what would be created without creating
    required: false
  - name: --skip-existing
    description: Skip tickets that already exist (don't ask)
    required: false
  - name: --team
    description: "Linear team name (default: Omninode)"
    required: false
---

# /onex:plan_to_tickets — Batch Ticket Creation from Plan

**Skill ID**: `onex:plan_to_tickets`
**Version**: 2.0.0
**Backing node**: `node_plan_to_tickets`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_plan_to_tickets`.
- **1.0.0** — Original skill.

## What this skill does

Dispatches through `onex run-node node_plan_to_tickets`. The node owns plan parsing,
epic creation, ticket creation, and dependency linking. This shim contains no
inline parsing or Linear mutation logic.

**Announce at start:** "I'm using the plan-to-tickets skill."

## Dispatch

```bash
uv run onex run-node node_plan_to_tickets --input '{
  "plan_file": "<path>",
  "project": null,
  "epic_title": null,
  "no_create_epic": false,
  "dry_run": false,
  "skip_existing": false,
  "team": "Omninode"
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_plan_to_tickets`

Command topic: `onex.cmd.omnimarket.plan-to-tickets-start.v1`

Terminal event: `onex.evt.omnimarket.plan-to-tickets-completed.v1`
