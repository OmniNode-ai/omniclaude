---
description: Prose stand-in for the five-whys record. Each why carries a reading someone else can look up, and the chain ends in code. Replaced by plan tasks T-P2, T-L1 to T-L4; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - five-whys
  - root-cause
  - prose-stand-in
author: omninode
---

# Lean Five Whys (prose stand-in)

This skill is a prose stand-in. It validates nothing. It asks you to produce by
hand the record that the five-whys checker will validate.

**Replaced by** the lean practices plan: T-P2 (failure record reducer),
T-L1 (record shape and checker), T-L2 (evidence reference resolver), T-L3 (closure
for stops and friction classes) and T-L4 (a thin five-whys skill shim, which takes
this skill's place). **Delete this skill when T-L4 lands.** The T-L tasks are
proposed in the plan, so check their status before relying on a date.

For the investigation itself, use `systematic_debugging`; this skill governs the
record you leave behind.

## When to use

At the close of an andon stop, and for a friction class that has occurred twice or
cost more than a few minutes in total.

## The record

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

## Rules to apply to yourself

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

## What this skill cannot do

It cannot judge whether an answer is the right cause, and neither will the checker.
The readback is what catches a well-evidenced wrong chain.
