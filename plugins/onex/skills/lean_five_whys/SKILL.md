---
description: Bootstrap skill for the five-whys record. Each why carries a reading someone else can look up, and the chain ends in code. Replaced by its node-backed skill on node_failure_record_reducer and node_five_whys_check_compute, under the factory plan; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - five-whys
  - root-cause
  - bootstrap
author: omninode
---

# Lean Five Whys (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It validates
nothing: it asks you to produce by hand the record that the five-whys checker will validate. It is
replaced by its node-backed skill when that skill comes online.

**Replaced by** the node-backed five-whys skill (plan task T-L4, a thin shim that calls `node_five_whys_check_compute`)
on `node_failure_record_reducer` (T-P2, failure record reducer) and `node_five_whys_check_compute` (T-L1, record shape
and checker), with T-L2 (`node_evidence_ref_resolve_effect`, the evidence reference resolver) and T-L3 (closure for
stops and friction classes). These tasks have no child ticket yet; they sit under the factory plan and are proposed in the
plan, so check their status before relying on a date. **Replace this skill with the node-backed skill when T-L4 lands.**

For the investigation itself, use `systematic_debugging`; this skill governs the
record you leave behind.

## The practice

One record per case, with these parts:

- **Subject.** The stop or the friction class.
- **Whys, in order.** Each has a question, an answer and one evidence reference.
  The reference is a ledger row (timestamp, kind, lane), a receipt, a log line
  (file, line range, and a digest of those lines) or a command with its output and
  read time. It also states the assertion it supports, such as "this field equals
  this value".
- **Countermeasure.** A hook, check, node, contract field, overlay or gate, and the
  repository path in the pull request that merged it. A first occurrence may close
  as a hand fix; a second occurrence must become code.
- **Standard work.** The skill, brief or ruling the change touches, edited in the
  same pull request.
- **Readback.** The command and output showing the cause fixed.

## When to use

At the close of an andon stop, and for a friction class that has occurred twice or
cost more than a few minutes in total.

## Steps by hand today

1. **No reading, no why.** A why without a reference someone else can open is
   labelled inferred and cannot be the root cause. Run the command and paste the
   output. Do not fill a why from memory.
2. **Chain the questions.** Why n+1 asks about the answer of why n, by id. Five
   unrelated statements are not a chain.
3. **No hedged answers.** An answer containing "probably", "likely", "seems" or
   "maybe" is an unmeasured claim. Measure it, or label the why inferred.
4. **Five is the count, not the goal.** If the chain truly ends sooner, say why and
   stop. If the fifth answer is still a symptom, keep going.
5. **End in code.** A countermeasure that is a sentence in a document is not a
   countermeasure. Name the file that changes.
6. **Close on a reading.** The record is closed by the readback on consecutive
   reads, not by the author's say-so.

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | T-L2 (evidence reference resolver) |
| 2 | T-L1 (record shape and checker) |
| 3 | T-L1 (checker) |
| 4 | T-L1 (checker) |
| 5 | T-L1 (closed list of countermeasure kinds) |
| 6 | T-L3 (closure for stops and friction classes) |

## What this skill cannot do

It cannot judge whether an answer is the right cause, and neither will the checker.
The readback is what catches a well-evidenced wrong chain.
