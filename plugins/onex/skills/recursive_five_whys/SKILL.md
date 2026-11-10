---
description: Bootstrap skill for root-cause finding by recursive five whys. Ask "why" one small evidence-backed step at a time, branching where a step has more than one cause, to a depth of five, and joining branches that reach the same cause. Use when a problem can be stated as one observed fact with a number and a time ("no pull request merged from 21:00Z to 03:00Z", not "merging is slow") and the cause is not yet known, for example stalled merges, a repeated red, a job that ended without pushing. Output is a cause tree with shared roots first, and a list of fixes where each fixable root has a countermeasure, an owner, a ticket and a measurement, and each outside cause has an ask and a stopgap.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
argument-hint: "<the problem as one observed fact with a number and a time>"
tags:
  - five-whys
  - root-cause
  - bootstrap
author: omninode
---

# Recursive five whys (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice: a way to find the root
causes of a problem by asking "why" one small step at a time, branching where a step has more than
one cause, until every branch ends at something we can fix or something outside our control. It is
run by hand first; a node that runs the same step, tree and fix rules over the team's records and
writes the cause tree itself replaces it once the process is proven. Nothing today runs it unprompted.

## Inputs

- **The problem**, stated as one observed fact with a number and a time. If the statement is a
  judgement ("merging is slow"), restate it as a reading before you start.
- **Where evidence lives**: the team's work record (tracker, change log), the pull request and CI
  state, run logs and reports, and host and broker readings.

## One step

Each step takes one fact and asks one question: **what directly caused this?**

1. Write the fact being explained.
2. List every direct cause you can find, at most three. A direct cause is the thing that, if it had
   not happened, this fact would not have happened.
3. For each cause, cite the evidence: a record entry (time and author), a log line, a check run, a
   reading, a file and line. A cause with no evidence is marked **unverified** and is not expanded
   further until someone finds evidence.
4. Classify each cause:
   - **Fixable root**: something we control, with a clear change that would prevent it. Stop here.
   - **Outside**: someone else's system or decision (another team's repository, the hosting
     provider, a vendor). Stop here and name who to ask.
   - **Deeper**: a cause that itself has causes. Make it the fact of a new step.

Keep each step small: one fact, one question, its evidence. That is what lets a small local model
answer it.

## The tree

- Start from the problem and run steps until every branch ends at a fixable root, an outside cause,
  or an unverified cause.
- Stop a branch at depth 5. If it is still "deeper" at depth 5, mark it **too deep**: that usually
  means the problem statement was too broad.
- When two branches reach the same cause, join them. **A cause reached by more than one branch is a
  shared root**, and shared roots come first.

## Fixes

For every fixable root:

- The **countermeasure**: the change that prevents the cause, written as a mechanism (a check, a
  test, a default, a guard), never as "be more careful".
- An **owner** and a **ticket**, made in the same act, so nothing found here is only reported.
- How we will **know it worked**: the measurement that shows the problem stopped, and when we read it.

For every outside cause: the ask, to whom, and what we do meanwhile so we are not blocked by it.

## Rules

- Evidence over memory. If you only remember it, it is unverified.
- Name the process causes as well as the technical ones. Ask "why did we not catch it?" at least
  once on every branch.
- No cause is "human error". Ask why the error was possible and why nothing stopped it.
- The output is fixes with owners, not a report.

## Output

1. The problem statement, as given.
2. The tree: each step as fact, causes, evidence, class; shared roots marked and listed first.
3. The fixes: one line per fixable root with countermeasure, owner, ticket, measurement and read
   date; one per outside cause with ask, recipient, stopgap.
4. Open fixes with no owner yet, named as such.

Make each ticket through the team's own ticket rules. A run that may not create tickets lists the
root under "open fixes with no owner yet" and asks whoever coordinates the work.
