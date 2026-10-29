---
description: Bootstrap skill for the andon stop. When a detector finds a defect of a known class, stop new work into that class, work the cause, restart only on a reading. Replaced by its node-backed skill on node_andon_stop_reducer; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - andon
  - jidoka
  - bootstrap
author: omninode
---

# Lean Andon Stop (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It enforces
nothing: it asks you to do by hand what the stop nodes will do on their own. It is replaced by its
node-backed skill when that skill comes online.

**Replaced by** the node-backed andon-stop skill on `node_andon_stop_reducer` (plan task T-A2: stop reducer,
class registry and `stop_gate`). The tasks behind it are T-A3 to T-A5 (the lab fill, the placement decision and the
worker-engine choice read the gate), T-A6 (detectors open and clear stops), T-A7 (swarm lanes), T-A8 (replay) and T-A9
(hash-chained stop record, `node_andon_stop_chain_compute`). **Replace this skill with the node-backed skill
when T-A2 to T-A7 are merged and deployed.**

## The practice

When a defect of a known class is found, new work into that class stops. One lane
works the cause until a check reads it fixed. Then the line resumes. Routing
around the defect and continuing to produce is the failure this skill exists to
prevent.

## When to use

A check, tick line or reviewer reports a defect that is a class and not a one-off:
a policy breach (a forbidden engine ran), a repository with no one landing its
pull requests, a host that keeps paging, a ruling whose live state has drifted, or
a seam whose two sides disagree.

## Steps by hand today

1. **Name the class and the key.** Class: engine policy, missing lander, host
   drift, ruling drift or seam mismatch. Key: the repository, host, engine or seam.
2. **Stop new work into that class.** Hold the class's new dispatches: write a hold
   on the ledger naming the class and key. Do not hold: the lane that works the
   cause, lanes that land or fix an already-open pull request, read-only lanes, and
   the merge of a pull request that is already armed.
3. **Name one swarm lane.** One lane works the cause. Record its id on the hold.
   Do not start a second lane on the same cause.
4. **Write the readback first.** The readback is a command whose output reads fixed
   or not fixed (a drift check, a merge in the repository, a policy dry run). Write
   it down before the fix, so the fix is judged by a reading and not by its author.
5. **Work the cause.** Run the five whys (`lean_five_whys`). The fix is code, a
   hook or a config field, never a sentence in a document.
6. **Restart on a reading.** Run the readback on two consecutive reads, counting
   only crossings after the fix merged. An unreadable result holds the stop; it
   never clears it. Release the hold only then.

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | T-A2 (class registry) |
| 2 | T-A3, T-A4, T-A5 (fill, placement and worker engine read the stop gate) |
| 3 | T-A7 (swarm lanes) |
| 4 | T-A6 (detectors open and clear stops) |
| 5 | T-L3 (closure for stops) |
| 6 | T-A6 (clear on readings), T-A9 (hash-chained stop record) |

## Guards

- A stop that stays open past four hours with no live swarm lane is itself a
  defect: raise it as a decision for the operator.
- More than five keys of one class in one pass is one stop for the class, not five.
- Production promotion is untouched. This stops development-lane and lab dispatch
  only, and never replaces the production approval gate.

## What this skill cannot do

It cannot refuse a dispatch. Nothing reads your hold except a person or a lane that
chooses to. If you skip the hold, nothing stops the line; that gap is the reason
T-A3 to T-A5 exist.
