---
name: linear-housekeeping
description: Orchestrate full Linear housekeeping — triage ticket status, organize orphans into epics, then sync MASTER_TICKET_PLAN.md. Human checkpoint between triage and apply.
version: 1.0.0
category: workflow
tags:
  - linear
  - housekeeping
  - triage
  - epics
  - documentation
author: OmniClaude Team
---

# Linear Housekeeping

## Overview

Parent skill that chains `linear-triage` → human review checkpoint → `linear-epic-org`
→ `ticket-plan-sync` into a single coherent workflow.

**Announce at start:** "I'm using the linear-housekeeping skill for a full ticket audit."

**Imports:** `@_lib/contracts/helpers.md`

## Quick Start

```
/linear-housekeeping
/linear-housekeeping --dry-run        # preview all changes, write nothing
/linear-housekeeping --threshold 7   # use 7-day staleness threshold (default 14)
/linear-housekeeping --skip-triage   # skip triage, go straight to epic-org + sync
/linear-housekeeping --sync-only     # only run ticket-plan-sync (fastest)
```

## Workflow Phases

```
Phase 1: linear-triage      (assess + mark done tickets)
          ↓
          Human checkpoint  (review TriageReport, confirm stale flags)
          ↓
Phase 2: linear-epic-org    (group orphans into epics, human gate for ambiguous)
          ↓
Phase 3: ticket-plan-sync   (regenerate or patch MASTER_TICKET_PLAN.md)
          ↓
         Done
```

---

## Phase 1: Triage

Dispatch linear-triage:

```
Skill("linear-triage", args="--threshold-days {threshold}")
```

On completion, display the TriageReport summary.

**If `--dry-run`:** pass `--dry-run` to linear-triage. Continue to Phase 2 without pause.
**Otherwise:** pause for human review.

### Human Checkpoint (after triage)

Present the summary and ask:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Triage complete. Review before continuing:

✅ Marked done:  {N} tickets (applied)
⚠️  Stale flags: {K} tickets (not applied — see below)
🔗 Orphans:      {M} tickets (will be addressed in Phase 2)

STALE TICKETS FLAGGED (review needed):
{list of stale tickets with age and recommendation}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Continue to Phase 2 (epic organization)?
Type "y" to continue, "stop" to exit, or review stale tickets first.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Stale ticket handling:** The user may ask to archive/cancel specific stale tickets
during this review. Handle those immediately via Linear MCP before proceeding to Phase 2.

---

## Phase 2: Epic Organization

If triage found orphaned tickets (or `--skip-triage` was used with known orphans):

```
Skill("linear-epic-org", args="--triage-report {report_path}")
```

`linear-epic-org` handles its own human gate for ambiguous groupings. See that skill
for the full interaction flow.

If no orphans found, skip Phase 2 with a note:
```
Phase 2: No orphaned tickets found — skipping epic organization.
```

---

## Phase 3: Ticket Plan Sync

After triage and epic-org are complete (tickets marked done, epics created), the
MASTER_TICKET_PLAN.md will be out of sync. Always run sync as the final step.

```
Skill("ticket-plan-sync")
```

Mode is auto-selected by ticket-plan-sync based on file age. Pass `--mode full` after
a session with many changes to ensure a clean state.

---

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Pass through to all three sub-skills. No Linear writes, no file writes. |
| `--threshold N` | Set staleness threshold in days (default 14). Passed to linear-triage. |
| `--skip-triage` | Skip Phase 1. Jump to Phase 2 (epic-org) and Phase 3 (sync). |
| `--sync-only` | Skip Phases 1 and 2. Only run ticket-plan-sync. |
| `--no-epic-org` | Skip Phase 2. Run triage → sync without epic organization. |
| `--full-sync` | Pass `--mode full` to ticket-plan-sync (force full regeneration). |

---

## Recommended Cadence

| Frequency | Command |
|-----------|---------|
| Weekly | `/linear-housekeeping` — full triage + org + sync |
| Daily / after PR merges | `/linear-housekeeping --sync-only` — refresh the doc |
| After epic sprint planning | `/linear-housekeeping --no-epic-org` — triage + sync |
| New project start | `/linear-housekeeping --full-sync` — clean slate |

---

## Example Session

```
> /linear-housekeeping

I'm using the linear-housekeeping skill for a full ticket audit.

Phase 1: Running linear-triage (threshold: 14 days)...
[triage runs, marks OMN-2068 done, flags 4 stale tickets, finds 7 orphans]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Triage complete. Review before continuing:
✅ Marked done:  1 ticket  (OMN-2068 — FK scan, PR merged)
⚠️  Stale flags: 4 tickets  (age >30d, recommend review)
🔗 Orphans:      7 tickets  (will be addressed in Phase 2)

STALE TICKETS:
  OMN-1452  (89d)  omniintelligence  → recommend: review_and_close
  OMN-407   (95d)  omnibase_core     → recommend: keep_open
  OMN-554   (32d)  omnibase_core     → recommend: keep_open
  OMN-917   (61d)  omnibase_core     → recommend: review_and_close
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Continue to Phase 2?

> y

Phase 2: Running linear-epic-org (7 orphans)...
[epic-org presents groupings, user approves, 2 epics created]

Phase 3: Running ticket-plan-sync (patch mode)...
Updated 3 rows, added 2 new epic sections.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Housekeeping Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tickets marked done:   1
Epics created:         2
Tickets linked:        7
Doc rows updated:      3
Doc sections added:    2

Stale tickets (need your review): 4
  → Review and archive manually or rerun triage after decisions.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| linear-triage fails | Report error, stop. Do not proceed to Phase 2. |
| linear-epic-org fails | Report error. Skip to Phase 3 (sync still safe). |
| ticket-plan-sync fails | Report error. Triage and epic changes already applied in Linear — just retry `--sync-only`. |
| Linear API rate limit | Pause 60s, retry once. If still failing, save state and exit with resume instructions. |

---

## See Also

- `linear-triage` skill — Phase 1: status assessment
- `linear-epic-org` skill — Phase 2: epic organization
- `ticket-plan-sync` skill — Phase 3: doc sync
- `@_lib/contracts/helpers.md` — TicketContract, EpicContract schemas
- `docs/tracking/MASTER_TICKET_PLAN.md` — the output document
