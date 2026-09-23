---
description: Recurring read-only sweep of a project tracker for comments awaiting a reply. Drafts every reply to a file and posts nothing. Thin process interface — the overlay names the tracker, the query and where drafts land.
version: 1.0.0
mode: full
level: intermediate
debug: false
category: workflow
tags:
  - process
  - tracker
  - recurring
  - read-only
  - overlay-configured
author: OmniClaude Team
composable: false
user_invocable: true
process_catalogue_row: comment_sweep
skill_kind: methodology
overlay_env: COMMENT_SWEEP_OVERLAY_PATH
args:
  - name: --intent
    description: "Session intent — quiet | normal | tick. Controls how much preflight output reaches the transcript."
    required: false
  - name: --since
    description: "Window to sweep, as a duration. Defaults to the overlay's cadence."
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
---

# Comment sweep

**Catalogue row**: `comment_sweep` · **Replacement**: none yet

This skill is a **temporary prose interface** over the recurring comment sweep.
It is the largest measured token consumer of any process in the catalogue and it
is the one with no invocable name today, which is why it is a row.

## What it wraps

The recurring tracker-comment sweep. The tracker, the query that finds
unanswered comments, the identity whose replies are owed, and the directory
drafts land in are **overlay content**.

## Overlay

Resolve the overlay with the shared resolver, the same search order every
overlay-configured skill uses:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" comment_sweep
```

| Order | Location | Kind |
| -- | -- | -- |
| 1 | `COMMENT_SWEEP_OVERLAY_PATH` | explicit pointer — a miss is a hard stop, never a fall-through |
| 2 | each root in `ONEX_SKILL_OVERLAY_ROOTS`, joined with `comment_sweep/overlay.yaml` | discovered |

It prints the resolved path, or exits non-zero naming every location it
tried. **A non-zero exit is a hard stop**, not a fall back to a default —
there is no default. Report its standard error and stop.

| Field | What it holds |
| -- | -- |
| `tracker_read_command` | the read-only query that lists comments awaiting a reply |
| `positive_control_command` | the same query against an input known to return rows |
| `draft_directory` | where reply drafts are written |
| `cadence` | the default sweep window |

## Preflight, by intent

Run the preflight first at the given intent. The tracker-connectivity check is
the one that matters here: a sweep that cannot reach the tracker returns zero
rows and reads exactly like a clean inbox.

## Verification contract

**Replies are drafted to files, never posted, and the run is proven read-only by
a zero count of write calls — with a positive control on the read path.**

Both halves are required and they fail in opposite directions:

- **Read-only** is proven by the *absence* of a write. Report the count of write
  calls made against the tracker. It is zero, and a non-zero count is a defect
  in this skill, not a finding about the tracker.
- **A zero result is proven by a positive control.** Run
  `positive_control_command` in the same pass. If it returns no rows either, the
  sweep did not work and the empty inbox is not a finding. **Never suppress
  stderr on either command** — an errored query and an empty one are
  indistinguishable once the error is discarded.

## Mechanical replacement

**none yet.** The replacement is a scheduled trigger with a firing receipt, plus
a gate that refuses to report a zero without its control attached. Both are
mechanisms; neither exists. Until they do, this row's correctness rests on the
person running it reading this section, which is exactly the failure the
catalogue records.

## What this skill does NOT do

- Post, edit, resolve or react to anything on the tracker — **it writes nothing**
- Report an empty result without its positive control
- Discard the standard error of either command
- Name a tracker, a project, an identity or a path in this file
