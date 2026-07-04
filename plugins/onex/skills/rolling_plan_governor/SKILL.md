---
description: Maintain the canonical rolling seven-day execution plan (docs/plans/ROLLING_SEVEN_DAY_PLAN.md) as a governor, not a rewriter — reconcile the plan against the latest ledger (handoffs, live gh/Linear, commits, PRs, blockers, decisions), apply the smallest set of evidence-backed changes, preserve the §0 operating preamble and stable sections, and append a dated revision-log delta. Ledger wins for completed work; unfinished work is preserved unless there is evidence to remove it.
mode: full
version: 1.0.0
level: advanced
debug: false
category: planning
tags:
  - planning
  - rolling-plan
  - seven-day
  - governor
  - ledger-reconcile
  - minimal-churn
  - work-queue
author: OmniClaude Team
args:
  - name: --plan
    description: "Path to the canonical rolling plan (default: docs/plans/ROLLING_SEVEN_DAY_PLAN.md in $OMNI_HOME)"
    required: false
  - name: --ledger
    description: "Path(s) to the primary ledger input for this cycle — usually the latest session handoff (default: newest docs/handoff/*handoff*.md). Comma-separated for multiple."
    required: false
  - name: --dry-run
    description: "Emit the governor report and the proposed diff without writing the plan file or committing."
    required: false
  - name: --no-commit
    description: "Write the updated plan but do not stage/commit — leave it dirty for operator review."
    required: false
skill_kind: methodology
composable: true
boundary_exempt: true
---

# /onex:rolling_plan_governor — Rolling Project Plan Governor

**Skill ID**: `onex:rolling_plan_governor`
**Version**: 1.0.0

**Announce at start:** "I'm using the rolling_plan_governor skill."

You are the Rolling Project Plan Governor. Your responsibility is **not** to
rewrite the plan from scratch. It is to maintain an accurate, actionable,
seven-day rolling execution plan based on new evidence, producing the **smallest
set of changes** necessary to keep the plan true.

The canonical plan is `docs/plans/ROLLING_SEVEN_DAY_PLAN.md` in the `omni_home`
registry. It is the single driver of daily activity (memory
`feedback_rolling_seven_day_plan`). This skill is how that document stays
current between execution cycles.

---

## Invocation

```
/onex:rolling_plan_governor
/onex:rolling_plan_governor --ledger docs/handoff/2026-07-04-daytime-session-handoff.md
/onex:rolling_plan_governor --dry-run
```

Full execution steps live in `prompt.md` (five ordered phases). This document
defines the behavioral contracts.

---

## Inputs (all treated as views of the same project)

The ledger is the most recent evidence of what actually happened; the plan is
the intended execution path. Any combination may be supplied or discovered:

- The current plan (`--plan`) — intended execution path, includes the durable §0 preamble.
- The ledger (`--ledger`) — the latest handoff(s), a project activity log, or session notes.
- Live control-plane surfaces — `gh pr list/view/checks`, Linear (issue state), `git log`, `ssh` runtime probes.
- Completed work, PRs, commits, tickets, blockers, design decisions, notes, new requirements.
- A design doc, Linear/GitHub epic, milestone, specification, or backlog.

**Source-of-truth rule:** when the ledger and the plan disagree, **prefer the
ledger for completed work**, but **preserve unfinished work** unless there is
positive evidence it should be removed. Where the ledger itself makes a
probeable claim (a PR merged, a ticket Done, a lane healthy), the **live
surface** (`gh`/Linear/`ssh`) outranks both — a handoff body is a report, not a
truth surface (consistent with `/onex:handoff` behavior (a)).

---

## Behavioral Contracts

### (a) Governor, not author — minimal churn

The output is a **diff**, not a rewrite. Sections that do not need to change are
left byte-for-byte identical. Reformatting, re-ordering, or re-wording stable
prose that carries no new evidence is a violation. Every changed line must trace
to a specific input.

**Hard-fail `CHURN_UNJUSTIFIED`** if the diff touches a section with no
corresponding ledger evidence.

### (b) The §0 operating preamble is durable

`§0 HOW WE WORK` is the standing contract between operator and sessions. It is
**only** edited when the operator changes the operating model — never as a
side effect of a normal reconcile. If a cycle would touch §0, that edit must be
called out explicitly in the report's *Required Plan Changes* with the operator
statement that authorizes it.

**Hard-fail `PREAMBLE_MUTATED_WITHOUT_DIRECTIVE`** if §0 changes without a cited
operator directive.

### (c) Evidence-backed state refresh (§1)

`§1 Verified current state` must be refreshed from **live probes**, not from
copying the ledger's prose. Each refreshed claim carries its source inline:
an executed probe, or `[reported: <surface>]` for a projection/handoff-sourced
value that could not be re-probed this cycle. Unprobeable claims are prefixed
`[unverified]` and excluded from load-bearing state.

Stale state that the ledger contradicts is **removed or corrected**, not left to
accumulate. Example: if §1 says a release chain is "NOT executed" and the ledger
+ `gh`/PyPI show it merged and published, §1 is corrected to the true state.

### (d) Preserve unfinished work; prune only on evidence

Completed work is removed from the queue (§2). Unfinished work is **preserved**
unless the ledger shows it obsolete, superseded, or explicitly dropped. A task
absent from the latest ledger is **not** evidence of completion — carry it
forward. Removing a live task requires a positive signal (merged PR, Done
ticket, operator drop, superseded-by pointer).

**Hard-fail `WORK_DROPPED_WITHOUT_EVIDENCE`** if a §2 task is deleted with no
completion/obsolescence signal.

### (e) Work-queue shape = ranked work-streams, not day buckets

This project ships via parallel background agents in hours, not day-sequenced
human effort (memory `feedback_estimation` — never emit multi-day estimates).
The "updated seven-day plan" is therefore the **ranked WS work-queue** (§2:
`WS-0`, `WS-P`, `WS-1`, …), ordered by the priority ladder below — **not**
`Day 1…Day 7` buckets. The seven-day window bounds scope; it does not partition
tasks into calendar days.

Priority ladder for (re)ranking §2:

1. Unblock blocked work
2. Finish work already started
3. Reduce project risk
4. Preserve architectural integrity
5. Maximize forward progress

Re-order only when dependencies or blockers actually changed. Do not reshuffle
for cosmetics.

### (f) Dated revision-log delta (§6)

Every applied cycle appends **one** dated delta to `§6 Revision log` — never
edits a prior delta — summarizing: what the ledger cleared, what state §1 was
corrected to, what moved/entered/left §2, and any §3 decision resolutions. The
delta cites the ledger doc by path. Prior deltas are immutable history.

### (g) Decision queue hygiene (§3 / §4 / §5)

Resolved operator decisions are struck through with the decision and date
(`~~...~~ — DECIDED <date>: <ruling>`) and their consequences flow into §2 —
they are not deleted. New decisions surfaced by the ledger are appended to §3
(operator/code) or §4 (AWS/Daniyal, approval-gated — never acted on
unilaterally). Parked scope (§5) moves only on an explicit operator unpark.

### (h) Terminal write + commit (unless --dry-run/--no-commit)

The updated plan is the canonical rolling plan until the next cycle. On a normal
run: write the file, `git add docs/plans/ROLLING_SEVEN_DAY_PLAN.md` (plus any
superseded-plan tombstone), commit with an `OMN-XXXX`-tagged message, and report
the commit sha. The plan lives in `omni_home`'s own git tree (edited in place —
this is not a nested repo clone), so no worktree is required for the plan edit
itself. `--dry-run` prints the report + proposed diff only; `--no-commit` writes
but leaves the file dirty.

---

## Output Format (governor report — emitted to the operator)

The report is a **console artifact**, separate from the plan-file diff. Emit
exactly these sections (omit a section only when genuinely empty, and say so):

```
## Project Status
Overall health · current milestone · progress summary.

## Ledger Summary
Completed work · new discoveries · outstanding blockers · architectural changes.

## Required Plan Changes
Only changes actually required. Each: reason · impact · priority.
(If §0 or a parked section is touched, cite the authorizing operator directive.)

## Updated Work Queue (7-day window)
The ranked WS work-streams as re-cut (WS-0, WS-P, WS-1, …) — NOT day buckets.
Only the streams that changed need detail; unchanged streams: "unchanged".

## Risks
Highest-priority technical, architectural, and scheduling risks.

## Recommended Next Actions
Immediate actions before the next planning cycle.

## Assumptions
Every assumption made this cycle, explicitly (empty if none).
```

Then, unless `--dry-run`:

```
PLAN UPDATED — docs/plans/ROLLING_SEVEN_DAY_PLAN.md
window: <start> → <end>   re-cut: <UTC>
commit: <sha>   (or: NOT COMMITTED — --no-commit)
changed sections: <§ list>   churn: <+adds/-dels lines>
```

---

## Hard-Fail Summary

| Condition | Failure mode |
|-----------|-------------|
| Diff touches a section with no ledger evidence | `CHURN_UNJUSTIFIED` |
| §0 preamble changed without a cited operator directive | `PREAMBLE_MUTATED_WITHOUT_DIRECTIVE` |
| §2 task deleted with no completion/obsolescence signal | `WORK_DROPPED_WITHOUT_EVIDENCE` |
| A probeable ledger claim written into §1 without live confirmation or `[reported:]` | `STATE_UNCERTIFIED` |
| Plan emitted `Day 1…Day 7` day buckets | `WRONG_QUEUE_SHAPE` |
| Prior §6 revision delta edited instead of appended | `REVISION_LOG_MUTATED` |

---

## Anti-Patterns

| Anti-pattern | Rejection |
|---|---|
| Rewriting the whole plan "for clarity" | `CHURN_UNJUSTIFIED` — governor, not author |
| Copying handoff prose into §1 verbatim as fact | `STATE_UNCERTIFIED` — probe or `[reported:]` |
| Deleting a task because it fell off the latest handoff | `WORK_DROPPED_WITHOUT_EVIDENCE` |
| Partitioning work into calendar days | `WRONG_QUEUE_SHAPE` — WS-ranked queue |
| Editing §0 to "tidy" the operating model | `PREAMBLE_MUTATED_WITHOUT_DIRECTIVE` |
| Silently acting on a §4 AWS/Daniyal item | Approval-gated — surface it, never execute |

---

## Architecture

```
SKILL.md   → behavioral contracts (this file) — 8 governor behaviors, hard-fails
prompt.md  → exact execution steps (five ordered phases)
```

No Kafka topics; no node backend. This is a methodology skill: it reads the
plan + live surfaces, reasons over the delta, and writes the canonical plan.

## See Also

- `docs/plans/ROLLING_SEVEN_DAY_PLAN.md` — the canonical artifact this governs
- memory `feedback_rolling_seven_day_plan` — the operator directive that made the plan rolling
- memory `feedback_estimation` — no multi-day estimates (why the queue is WS-ranked)
- `/onex:handoff` — produces the ledger this skill consumes; shares the probe-not-prose discipline
- `/onex:ticket_plan` — Linear-sourced master backlog (a §2 input, not a substitute)
