---
description: Refresh a generated status board by running the generator its overlay names, then prove the board's published timestamp advanced. Thin process interface — the overlay supplies the generator, the board and the publish surface; this skill supplies neither.
version: 1.0.0
mode: full
level: intermediate
debug: false
category: workflow
tags:
  - process
  - board
  - scheduled
  - overlay-configured
author: OmniClaude Team
composable: false
user_invocable: true
process_catalogue_row: plans_board_refresh
skill_kind: methodology
overlay_env: PLANS_BOARD_REFRESH_OVERLAY_PATH
args:
  - name: --intent
    description: "Session intent — quiet | normal | tick. Controls how much preflight output reaches the transcript."
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
---

# Plans board refresh

**Catalogue row**: `plans_board_refresh` · **Replacement**: none yet

This skill is a **temporary prose interface** over a process that already exists.
It is not the process and it owns no logic. Its whole job is that nobody has to
remember the generator's name and its arguments.

## What it wraps

The status-board generator named by the overlay. The generator, the board it
publishes, the repository it lives in and the command that runs it are **overlay
content** and appear nowhere in this file. A committed default here would be an
organization's process shipped in a public plugin.

## Overlay

Resolve the overlay from `PLANS_BOARD_REFRESH_OVERLAY_PATH`. **An unset or
unreadable variable is a hard stop**, not a fall back to a default — there is no
default, and a board refresh that ran against a guessed generator is worse than
one that did not run. Report the variable name and stop.

The overlay supplies:

| Field | What it holds |
| -- | -- |
| `generator_command` | the command that regenerates and publishes the board |
| `board_locator` | how to read the published board's timestamp back |
| `working_directory` | where the generator is run from |
| `cadence` | how often the process is expected to fire |

## Preflight, by intent

Run the session preflight first and let `--intent` decide what it prints:
`quiet` prints nothing but a blocker, `normal` prints one line per check with
its fix command, `tick` writes the same verdict to the run's own record and
nothing to the transcript. A blocked preflight stops the refresh; it does not
downgrade it.

## Verification contract

**The board's published timestamp advanced past the time this run started.**

Read the timestamp before the run and again after it, through `board_locator`,
and report both. A generator that exits zero having published nothing is the
failure this row exists for, so an unchanged timestamp is a **failure**, never a
no-op. Report the two timestamps even when they differ — the reader is checking
the delta, not taking a verdict.

## Mechanical replacement

**none yet.** This row is prose because the refresh is invoked from memory
today. The replacement is a scheduled trigger that fires the generator on its
cadence and writes a firing receipt before it does any work, so that "fired and
published nothing" is distinguishable from "nothing fired". When that exists,
this skill is deleted rather than kept alongside it.

## What this skill does NOT do

- Carry a generator command, a repository name, a path or a host in this file
- Edit the board, or publish anything the generator did not produce
- Report success from the generator's own exit code alone
