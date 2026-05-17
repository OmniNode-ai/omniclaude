---
description: Create a single Linear ticket from args, contract file, or plan milestone with conflict resolution
mode: full
version: 2.0.0
level: basic
debug: false
category: workflow
tags:
  - linear
  - tickets
  - automation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: title
    description: Ticket title (mutually exclusive with --from-contract, --from-plan)
    required: false
  - name: --from-contract
    description: Path to YAML contract file
    required: false
  - name: --from-plan
    description: Path to plan markdown file
    required: false
  - name: --milestone
    description: Milestone ID when using --from-plan (e.g., M4)
    required: false
  - name: --repo
    description: Repository label (e.g., omniclaude, omnibase_core)
    required: false
  - name: --parent
    description: Parent issue ID for epic relationship (e.g., OMN-1800)
    required: false
  - name: --blocked-by
    description: Comma-separated issue IDs that block this ticket
    required: false
  - name: --team
    description: "Linear team name (default: Omninode)"
    required: false
  - name: --dry-run
    description: Show what would be created without creating
    required: false
---

# /onex:create_ticket — Single Ticket Creation

**Skill ID**: `onex:create_ticket`
**Version**: 2.0.0
**Backing node**: `node_create_ticket`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_create_ticket`.
- **1.0.0** — Original skill.

## What this skill does

Dispatches through `onex run-node node_create_ticket`. The node owns contract parsing,
conflict resolution, and Linear ticket creation. This shim contains no inline Linear
mutation logic.

**Announce at start:** "I'm using the create-ticket skill."

## Dispatch

```bash
uv run onex run-node node_create_ticket --input '{
  "title": "<title or null>",
  "from_contract": null,
  "from_plan": null,
  "milestone": null,
  "repo": null,
  "parent": null,
  "blocked_by": null,
  "team": "Omninode",
  "dry_run": false
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_create_ticket`

Command topic: `onex.cmd.omnimarket.create-ticket-start.v1`

Terminal event: `onex.evt.omnimarket.create-ticket-completed.v1`
