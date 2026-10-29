---
description: Bootstrap skill for experiment-first change and innovation accounting. Write the hypothesis, metric, threshold and pass check before the work; decide persevere, tune or pivot from the reading. Replaced by its node-backed skill on node_experiment_record_compute and node_innovation_accounting_reducer, under the factory plan; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - experiment
  - innovation-accounting
  - bootstrap
author: omninode
---

# Lean Experiment First (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It records and
decides nothing: it asks you to do by hand the baseline, the tune step and the decision that the
innovation accounting loop will do mechanically. It is replaced by its node-backed skill when that
skill comes online.

**Replaced by** the node-backed experiment-first skill on `node_experiment_record_compute` (plan task T-L7: the
experiment record, written first and enforced at dispatch) and `node_innovation_accounting_reducer` (T-L6: the baseline,
tune, hold, pivot-or-persevere loop), with T-L5 (`node_actionable_metrics_compute`, actionable metrics registry), T-L8
(`node_value_stream_compute`, lead time per station and the seven wastes) and T-L9 (the one-page view generated from the
records). These tasks have no child ticket yet; they sit under the factory plan and are proposed in the plan, so check their
status first. **Replace this skill with the node-backed skill when T-L6 and T-L7 land.**

## The practice

Write down what a change should do, and how you will read it, before you make the change. Decide to keep, tune or drop it from the reading, never from the author's belief.

## When to use

When you change a mechanism (a gate, a node, a routing rule, a brief shape) and
claim that it makes the line faster, cheaper or better.

## Steps by hand today

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

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | T-L7 (experiment record, enforced at dispatch) |
| 2 | T-L5 (actionable metrics registry), T-L6 (baseline) |
| 3 | no task yet |
| 4 | T-L6 (loop) |
| 5 | T-L6 (persevere, tune, hold, pivot) |
| 6 | T-L5 (guard metrics); T-L8 and T-L9 for lead time and the one-page view |

## Do not count as progress

Lanes dispatched, pull requests opened, tickets created, tokens spent with no
accepted outcome beside them, document length, and a green run that proves nothing.
A metric needs an outcome, cost or defect as its numerator, and accepted outcomes or
time as its denominator.

## What this skill cannot do

It cannot stop you from writing the hypothesis after the result, and few readings
are noise. The plan does not claim otherwise; hold when readings are few.
