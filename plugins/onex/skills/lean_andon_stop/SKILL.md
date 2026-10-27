---
description: Prose stand-in for the andon stop. When a detector finds a defect of a known class, stop new work into that class, work the cause, restart only on a reading. Replaced by plan tasks T-A2 to T-A9; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - andon
  - jidoka
  - prose-stand-in
author: omninode
---

# Lean Andon Stop (prose stand-in)

This skill is a prose stand-in. It exists only until the mechanical andon stop
exists. It replaces nothing that runs today and enforces nothing; it asks you to
do by hand what the stop nodes will do on their own.

**Replaced by** the andon-stop tasks of the lean practices plan:
T-A2 (stop reducer, class registry and `stop_gate`), T-A3 to T-A5 (the lab fill,
the placement decision and the worker-engine choice read the gate), T-A6 (detectors
open and clear stops), T-A7 (swarm lanes), T-A8 (replay) and T-A9 (hash-chained
stop record). **Delete this skill when T-A2 to T-A7 are merged and deployed.**

## When to use

A check, tick line or reviewer reports a defect that is a class and not a one-off:
a policy breach (a forbidden engine ran), a repository with no one landing its
pull requests, a host that keeps paging, a ruling whose live state has drifted, or
a seam whose two sides disagree.

## The rule

When a defect of a known class is found, new work into that class stops. One lane
works the cause until a check reads it fixed. Then the line resumes. Routing
around the defect and continuing to produce is the failure this skill exists to
prevent.

## Procedure

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
