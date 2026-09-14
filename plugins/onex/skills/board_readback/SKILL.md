---
description: Re-read a generated status board's own inputs immediately before the change that lands it, and quote the re-read in that change. Thin process interface — the overlay names the generator, its inputs and the landing surface.
version: 1.0.0
mode: full
level: intermediate
debug: false
category: workflow
tags:
  - process
  - board
  - readback
  - overlay-configured
author: OmniClaude Team
composable: false
user_invocable: true
process_catalogue_row: board_readback
skill_kind: methodology
overlay_env: BOARD_READBACK_OVERLAY_PATH
args:
  - name: --intent
    description: "Session intent — quiet | normal | tick. Controls how much preflight output reaches the transcript."
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
---

# Board readback

**Catalogue row**: `board_readback` · **Replacement**: none yet

This skill is a **temporary prose interface**. It owns no logic and it is
deleted when the mechanical replacement below exists.

## What it wraps

The readback path of the same status-board generator the refresh row runs. The
generator, its inputs, and the change that lands the readback are **overlay
content**.

The distinction from the refresh row is the direction of proof. The refresh row
asks *did the board move*. This row asks *does the board still agree with the
inputs it was generated from* — and asks it at the last possible moment, because
a board generated an hour ago and landed now is a board that has had an hour to
go stale.

## Overlay

Resolve `BOARD_READBACK_OVERLAY_PATH`. Unset or unreadable is a hard stop. There
is no default.

| Field | What it holds |
| -- | -- |
| `input_locators` | how to read each input the generator consumes |
| `board_locator` | how to read the generated board back |
| `landing_surface` | where the readback is quoted so a reviewer sees it |
| `working_directory` | where the readback is run from |

## Preflight, by intent

As every process row: run the preflight first, at the given intent. A blocker
stops the readback.

## Verification contract

**The generator's own inputs were re-read immediately before the merge, and the
re-read output is quoted in the change that lands it.**

Two things make this contract fail, and both look like success from the outside:

- a readback of a **cached** board, which proves the cache and nothing else;
- a re-read done early in the run and quoted at the end, with writes in between.

So the re-read is the **last** action before landing, and its raw output — not a
summary of it — goes into the landing surface. A reviewer must be able to
recompute the verdict from what is quoted.

## Mechanical replacement

**none yet.** The replacement is a gate on the landing surface that refuses the
change unless it carries a re-read newer than every input it names, anchored on
whole lines rather than a substring so that prose *describing* a readback cannot
satisfy it. Until that gate exists this row depends on the person running it,
which is the property the catalogue exists to retire.

## What this skill does NOT do

- Regenerate the board (that is the refresh row)
- Accept a cached read, or a summary of a read, as the readback
- Name a repository, a path or a host in this file
