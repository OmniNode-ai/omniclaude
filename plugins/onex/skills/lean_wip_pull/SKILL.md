---
description: Prose stand-in for per-repository work-in-progress limits and pull-first selection. Replaced by plan tasks T-W1 to T-W4; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - wip
  - pull
  - prose-stand-in
author: omninode
---

# Lean WIP Limit and Pull (prose stand-in)

This skill is a prose stand-in. It enforces nothing. It asks you to apply by hand
the limit and the pull order that the WIP gate and the slot assignment will apply
mechanically.

**Replaced by** the WIP tasks of the lean practices plan: T-W1 (WIP
gate reducer, overlay limits and reader), T-W2 (slot assignment with pull-first
order and the no-idle rule), T-W3 (the brief gate names the repositories a lane
opens pull requests in, and refuses past a limit) and T-W4 (flow measures).
**Delete this skill when T-W1 to T-W3 are merged and deployed.**

## When to use

Before you start or dispatch work that opens a pull request, and when choosing
what to pick up next.

## The idea

Work in progress that cannot land is waste. The open count rising while merges fall
means the line is pushing, not pulling. Keep the number of open, unlanded pull
requests per repository small, and take work from what blocks flow before the
backlog.

## Procedure

1. **Count WIP for the repository** you would open a pull request in: open pull
   requests including drafts, not merged and not in a merge queue. Read it from the
   pull request watcher state and print both the count with drafts and without.
2. **Compare to the limit.** Use the repository's recorded limit. If none is
   recorded, use your own best estimate and write it down: hours of landing times
   merges per hour, with a floor of three. A limit you cannot cite is a guess;
   label it as one.
3. **At or over the limit, do not open a new pull request.** Exempt work: reducing
   WIP (a cause fix, a controller fix, a land or review lane, work on an open
   unlanded pull request), read-only work, and the swarm lane of an andon stop.
4. **Pull in this order.**
   1. The cause of a stopped class.
   2. A missing lander or an unowned shared red.
   3. Pull requests held or red with no owner.
   4. The rest of the backlog, only for repositories under their limit.
   5. Work that opens no pull request.
   6. As a last resort, a pull-request-opening item at a limit.
5. **Never leave a slot idle.** A limit diverts the slot to work that opens no pull
   request: fixing bugs, running tests, experiments. When no such work exists, take
   the last-resort item and say so in your closing note.

## Measures to report

Merges per hour per repository, the open count and its trend, green-to-merged
time, pull requests held, and slots that took the last-resort item. Report what you
read and when; do not estimate a reading you did not take.

## What this skill cannot do

It cannot refuse a dispatch or read the watcher for you. The limit holds only as
long as every lane chooses to apply it.
