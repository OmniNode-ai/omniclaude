---
description: Recurring verification tick over dispatched lanes — name every stalled lane with the age of its last write, or prove a zero with a positive control. Thin process interface over the dispatch watchdog.
version: 1.0.0
mode: full
level: intermediate
debug: false
category: workflow
tags:
  - process
  - recurring
  - watchdog
  - overlay-configured
author: OmniClaude Team
composable: false
user_invocable: true
process_catalogue_row: overseer_verify_tick
skill_kind: methodology
overlay_env: OVERSEER_VERIFY_TICK_OVERLAY_PATH
args:
  - name: --intent
    description: "Session intent — quiet | normal | tick. Controls how much preflight output reaches the transcript."
    required: false
  - name: --stall-threshold-minutes
    description: integer arg
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
---

# Overseer verify tick

**Catalogue row**: `overseer_verify_tick` · **Replacement**: none yet

This skill is a **temporary prose interface**. The watchdog it wraps already
exists; what did not exist was a name for the recurring *process* of running it
and acting on the result, which is why this row was recorded as partial rather
than as present.

## What it wraps

The dispatch watchdog. Which lanes are in scope, how a lane's last write is
read, and where stall findings are recorded are **overlay content**.

## Overlay

Resolve the overlay with the shared resolver, the same search order every
overlay-configured skill uses:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" overseer_verify_tick
```

| Order | Location | Kind |
| -- | -- | -- |
| 1 | `OVERSEER_VERIFY_TICK_OVERLAY_PATH` | explicit pointer — a miss is a hard stop, never a fall-through |
| 2 | each root in `ONEX_SKILL_OVERLAY_ROOTS`, joined with `overseer_verify_tick/overlay.yaml` | discovered |

It prints the resolved path, or exits non-zero naming every location it
tried. **A non-zero exit is a hard stop**, not a fall back to a default —
there is no default. Report its standard error and stop.

| Field | What it holds |
| -- | -- |
| `lane_inventory_command` | how the live lane set is enumerated |
| `last_write_locator` | how a lane's most recent write is read |
| `positive_control_command` | the same enumeration against a lane known to be live |
| `stall_threshold_minutes` | the default age at which a lane counts as stalled |
| `finding_surface` | where a stall finding is recorded |

## Preflight, by intent

Run the preflight first, at the given intent.

## Verification contract

**Every stalled lane is named with the age of its last write, or a zero is
proven by a positive control against a lane known to be live.**

The tick has to add to or subtract from the live lane set, or say plainly why it
did neither. "Nothing stalled" is a legitimate outcome exactly once per run and
only with its control attached — an enumeration that silently returned nothing
produces the same sentence and means the opposite.

A stalled lane is **named**, with the age of its last write, and the finding is
recorded on `finding_surface`. It is not summarised as a count.

## Mechanical replacement

**none yet.** The replacement is a watchdog that runs on its own schedule,
writes a firing receipt before it enumerates, and refuses to emit a zero without
its control. That removes the two ways this row fails today: nobody ran it, and
somebody ran it against an enumeration that was broken.

## What this skill does NOT do

- Stop, restart or message any lane — it observes and records
- Report a zero without its positive control
- Match processes by command substring when acting on a finding; a stall is
  named by its own identifier, never by a pattern that matches its peers
- Name a lane, a host or a path in this file
