---
description: Prose stand-in for experiment-first change and innovation accounting. Write the hypothesis, metric, threshold and pass check before the work; decide persevere, tune or pivot from the reading. Replaced by plan tasks T-L5 to T-L9; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - experiment
  - innovation-accounting
  - prose-stand-in
author: omninode
---

# Lean Experiment First (prose stand-in)

This skill is a prose stand-in. It records and decides nothing. It asks you to do by
hand the baseline, the tune step and the decision that the innovation accounting
loop will do mechanically.

**Replaced by** the lean practices plan: T-L5 (actionable metrics
registry), T-L6 (the baseline, tune, hold, pivot-or-persevere loop), T-L7 (the
experiment record, written first and enforced at dispatch), T-L8 (lead time per
station and the seven wastes) and T-L9 (the one-page view generated from the
records). **Delete this skill when T-L6 and T-L7 land.** These tasks are proposed in
the plan, so check their status first.

## When to use

When you change a mechanism (a gate, a node, a routing rule, a brief shape) and
claim that it makes the line faster, cheaper or better.

## Procedure

1. **Write the experiment record before the work.** One sentence naming the change
   and the metric it should move; the direction; the threshold as a number; the pass
   check as a command or test id; the guard metric; the named cohort of work; and the
   time you wrote it. Put it in the ledger or the pull request body before you start.
2. **Take a baseline first.** Read the same metric several times (the plan proposes
   five) before the change, with read times and sources. A baseline taken while an
   andon stop was open is not usable. With too few readings, write `unread`.
3. **Change one thing.**
4. **Read the same metric** over the same window length and the same cohort, in a
   window that does not overlap the baseline's.
5. **Decide, by the median of the readings.**
   - **Persevere**: it moved the good way by at least the threshold (the plan
     proposes 10 percent) and by more than the baseline's own range, with enough
     readings (three), and the guard did not worsen by more than its tolerance
     (five percent). The new reading becomes the next baseline.
   - **Hold**: too few readings, overlapping windows, a different cohort or an
     unreadable measurement. Decide nothing and do not count a tune.
   - **Tune**: readings suffice but the movement is small or the guard worsened.
     Make one more change.
   - **Pivot**: three tunes in a row failed. Ask the operator as one plain question
     with the readings; replace or drop the mechanism only after the answer.
6. **Guard every speed or cost gain** with the post-merge red rate, so a change
   cannot buy speed with worse quality.

## Do not count as progress

Lanes dispatched, pull requests opened, tickets created, tokens spent with no
accepted outcome beside them, document length, and a green run that proves nothing.
A metric needs an outcome, cost or defect as its numerator, and accepted outcomes or
time as its denominator.

## What this skill cannot do

It cannot stop you from writing the hypothesis after the result, and few readings
are noise. The plan does not claim otherwise; hold when readings are few.
