---
description: Bootstrap skill for session recovery. After a restart or a usage-limit reset, rebuild state from the ledger and live reads before acting. No node-backed skill exists yet to replace it; replace it when one lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
tags:
  - lean
  - recovery
  - session
  - bootstrap
author: omninode
---

# Lean Session Recovery (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It restores
nothing for you: it asks you to rebuild by hand what a session lost, from the ledger and from live
reads, before you act. It is replaced by its node-backed skill when that skill comes online.

**Replaced by** no node-backed skill yet: the lean practices plan has no recovery task, so there is no node to name. The
nearest is T-A9 (`node_andon_stop_chain_compute`: the hash-chained, replay-verified stop record), which would
let a restart read the open stops from a record. A recovery task is to be ticketed under the factory plan. **Replace this skill
with the node-backed skill when a recovery task is merged and deployed.**

## The practice

A restarted session knows nothing it did not write down. Do not resume from memory
or from the last summary. Read the ledger for what was claimed, held and ruled, read
the live surfaces for what is true now, and only then act. The first action after a
restart is a reading.

## When to use

After a session restart, after a usage-limit reset, after a context compaction, and
whenever you pick up a lane that another session started.

## Steps by hand today

1. **Read the inbox and the holds.** A hold or a message addressed to you binds,
   whether or not it reached you before the restart.
2. **Read your own open claims.** Which of them have a terminal row, and which are
   still open. A claim with no live worker is dead; say so.
3. **Read the open stops.** Which classes are stopped and which lane works each.
4. **Read the live state of every item you were driving** (`lean_go_and_see`): the
   pull request head and its check-runs, the deployed tag, the process on the host.
   Do not trust the last note about it.
5. **Write the recovered state down.** One status row naming what you found, then
   continue the work, or stop if a hold says to.

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | no task yet |
| 2 | no task yet |
| 3 | T-A9 (stop record read on restart) |
| 4 | no task yet |
| 5 | no task yet |

## What this skill cannot do

It cannot tell you what a lane would have done. It restores a reading of the state,
not the lane's intent; if the intent is not on the ledger, ask for it.
