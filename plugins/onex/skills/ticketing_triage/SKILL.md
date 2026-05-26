---
description: Dispatch-only wrapper for Linear ticket triage node
mode: full
version: 2.0.0
level: intermediate
debug: false
category: workflow
tags:
  - linear
  - triage
  - housekeeping
  - tickets
  - prs
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
composable: true
inputs:
  - name: threshold_days
    type: int
    description: Tickets updated within this many days are "recent" and get PR-verified (default 14)
    required: false
  - name: dry_run
    type: bool
    description: Assess and report without writing any changes to Linear (default false)
    required: false
outputs:
  - name: skill_result
    type: TriageReport
    description: "Written to $ONEX_STATE_DIR/state/ticketing-triage/{run_id}.yaml"
---

# /onex:ticketing_triage — Linear Ticket Triage

**Skill ID**: `onex:ticketing_triage`
**Version**: 2.0.0
**Backing node**: `node_linear_triage`

## Changelog

- **2.0.0** — Thinned to dispatch-only shim (OMN-12200). Delegates to node_linear_triage.
- **1.0.0** — Original inline skill with Phases 1-6 algorithm.

## What this skill does

Dispatches through `onex run-node node_linear_triage`. The node owns full triage
(status sweep, orphan detection, epic organization, plan sync). This shim contains
no inline Linear query or mutation logic.

**Announce at start:** "I'm using the ticketing-triage skill to assess ticket health."

## Dispatch

```bash
uv run onex run-node node_linear_triage --input '{
  "threshold_days": 14,
  "dry_run": false
}'
```

Pass `threshold_days` and `dry_run` through from skill invocation args. On non-zero exits,
surface the `SkillRoutingError` JSON envelope directly; do not produce prose.

## Wire Schema

Contract target: `node_linear_triage`

Command topic: `onex.cmd.omnimarket.linear-triage-start.v1`

Terminal event: `onex.evt.omnimarket.linear-triage-completed.v1`

## Composable Output

The `TriageReport` is written to `$ONEX_STATE_DIR/state/ticketing-triage/{run_id}.yaml`
by the backing node and the path is returned as output.

The `orphaned_tickets` list from the TriageReport is the input to `ticketing-epic-org`.

## See Also

- `@_lib/contracts/helpers.md` — TicketContract, TriageReport schemas
- `ticketing-epic-org` skill — consumes orphaned_tickets from this report
- `linear-housekeeping` skill — orchestrates triage → epic-org → ticket-plan --sync
- `ticket-plan --sync` — uses triage output for MASTER_TICKET_PLAN.md sync
