---
description: Bootstrap skill for mistake-proofing (poka-yoke). Make the wrong thing impossible or refused at the earliest station, and name the criteria a pull request proves. Replaced by its node-backed skill on node_lane_brief_pr_gate_compute; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - poka-yoke
  - bootstrap
author: omninode
---

# Lean Poka-yoke (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It refuses
nothing: it asks you to apply by hand the refusals that gates will apply at the earliest station. It
is replaced by its node-backed skill when that skill comes online.

**Replaced by** the node-backed poka-yoke skill on `node_lane_brief_pr_gate_compute` (plan task T-W3, with
T-P3 on the same node: a pull-request-opening brief carries a `Proves:` line, and the brief gate refuses it when the
line is absent or names a criterion the brief did not quote). The other gates behind it are T-S6 (the lane commit step
reports and retries instead of leaving staged work, `node_lane_commit_intent_compute`), T-S8 (a handoff for a repository
outside the controller's scope is refused, `node_pr_handoff_decision_compute`) and T-L1 (a closed list of
countermeasure kinds, so a prose countermeasure cannot be entered). **Replace this skill with the node-backed skill when
T-P3 is merged and deployed.**

## The practice

Make the wrong thing impossible, or refuse it at the earliest station, instead of
finding it downstream. A mistake caught at the brief costs minutes; the same
mistake caught after tested work sits staged costs the work.

## When to use

When you write or accept a brief, open a pull request, hand one off, or design a
countermeasure for a mistake that has happened once.

## Steps by hand today

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

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | T-P3 (brief gate) |
| 2 | T-P3 (`Proves:` line refused when absent) |
| 3 | T-S8 (out-of-scope handoff refused) |
| 4 | T-S6 (commit step reports and retries) |
| 5 | T-L1 (closed list of countermeasure kinds) |

## What this skill cannot do

It cannot tell whether a `Proves:` line is true. A semantic mismatch is not
machine-decidable, and the plan does not claim to catch one. It counts the
consequence instead: staged work that never landed, and pull requests with no
handoff.
