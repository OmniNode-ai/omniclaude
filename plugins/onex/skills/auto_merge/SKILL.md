---
description: Merge a GitHub PR when all gates pass; proceeds automatically after CI is clean
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - github
  - merge
  - automation
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
inputs:
  - name: pr_number
    type: int
    description: GitHub PR number to merge
    required: true
  - name: repo
    type: str
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: strategy
    type: str
    description: "Merge strategy: squash | merge | rebase (default: squash)"
    required: false
  - name: gate_timeout_hours
    type: float
    description: "Wall-clock budget in hours for the CI readiness poll. Default: 24."
    required: false
  - name: delete_branch
    type: bool
    description: Delete branch after merge (default true)
    required: false
  - name: ticket_id
    type: str
    description: "Linear ticket identifier (e.g. OMN-1234) to mark Done after merge"
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/auto_merge.json"
args:
  - name: pr_number
    description: GitHub PR number to merge
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --strategy
    description: "Merge strategy: squash|merge|rebase (default squash)"
    required: false
  - name: --gate-timeout-hours
    description: Hours to wait for CI readiness (default 24)
    required: false
  - name: --no-delete-branch
    description: Don't delete branch after merge
    required: false
  - name: --ticket-id
    description: Linear ticket ID to mark Done after merge (e.g. OMN-1234)
    required: false
---

# /onex:auto_merge — Auto Merge Effect

**Skill ID**: `onex:auto_merge`
**Version**: 2.0.0
**Backing node**: `node_auto_merge_effect`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-8768). All logic in `node_auto_merge_effect`.
- **1.0.0** — Original (OMN-2525).

## What this skill does

Dispatches through `onex run-node node_auto_merge_effect`. The node owns CDQA gate
verification, CI readiness polling, merge execution, and Linear ticket closure.
This shim contains no inline polling or merge mutation logic.

**Announce at start:** "I'm using the auto-merge skill to merge PR #{pr_number}."

## Dispatch

```bash
uv run onex run-node node_auto_merge_effect --input '{
  "pr_number": <pr_number>,
  "repo": "<org/repo>",
  "strategy": "squash",
  "gate_timeout_hours": 24,
  "delete_branch": true,
  "ticket_id": null
}'
```

On non-zero exits, surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_auto_merge_effect`

Command topic: `onex.cmd.omnimarket.auto-merge-requested.v1`

Terminal event: `onex.evt.omnimarket.pr-merged.v1`
