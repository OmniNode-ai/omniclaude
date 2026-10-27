---
description: Prose stand-in for mistake-proofing, poka-yoke. Make the wrong thing impossible or refused at the earliest station, and name the criteria a pull request proves. Replaced by plan tasks T-P3, T-S6, T-S8 and T-L1; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - poka-yoke
  - prose-stand-in
author: omninode
---

# Lean Poka-yoke (prose stand-in)

This skill is a prose stand-in. It refuses nothing. It asks you to apply by hand the
refusals that gates will apply at the earliest station.

**Replaced by** the lean practices plan: T-P3 (a pull-request-opening
brief carries a `Proves:` line, and the brief gate refuses it when the line is
absent or names a criterion the brief did not quote), T-S6 (the lane commit step
reports and retries instead of leaving staged work), T-S8 (a handoff for a
repository outside the controller's scope is refused) and T-L1 (a closed list of
countermeasure kinds, so a prose countermeasure cannot be entered). **Delete this
skill when T-P3 is merged and deployed.**

## When to use

When you write or accept a brief, open a pull request, hand one off, or design a
countermeasure for a mistake that has happened once.

## The rule

Make the wrong thing impossible, or refuse it at the earliest station, instead of
finding it downstream. A mistake caught at the brief costs minutes; the same
mistake caught after tested work sits staged costs the work.

## Procedure

1. **Name the criteria before you start.** Quote the ticket's acceptance criteria
   in the brief. If the work does not match them, stop and fix the ticket or the
   brief now. Work that cannot claim its ticket's criteria cannot land.
2. **Add a `Proves:` line** to every brief that opens a pull request, listing the
   criteria by id, for example `Proves: AC1, AC3`. Every id must be among the
   criteria you quoted.
3. **Check the scope of the handoff.** Before handing a pull request off, confirm the
   repository is one the landing controller covers. If not, say so and route it.
4. **Never leave staged work.** Commit and push in the same step, report failure
   rather than stopping quietly, and retry once. Staged and uncommitted work is
   lost work.
5. **When you design a countermeasure, prefer refusal.** Order of preference: the
   state cannot be entered; a gate refuses it; a check reports it; a document says
   not to. Only the first three count. A sentence in a document is not a
   countermeasure.

## What this skill cannot do

It cannot tell whether a `Proves:` line is true. A semantic mismatch is not
machine-decidable, and the plan does not claim to catch one. It counts the
consequence instead: staged work that never landed, and pull requests with no
handoff.
