---
description: Bootstrap skill for the line board, the visual management of the lean family. List every line and plan in progress with its stage, its owner lane or none, and for every line that is not moving the cause in one sentence with the ledger row, check or read behind it. Replaced by its node-backed skill on node_factory_floor_effect's lines operation; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - visual-management
  - andon
  - status
  - bootstrap
author: omninode
---

# Lean Line Board (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It enforces
nothing: it asks you to do by hand what the factory floor nodes will do on their own, from the
readers that already exist. It adds no reader. It is replaced by its node-backed skill when that
skill comes online.

**Replaced by** the node-backed line board skill on `node_factory_floor_effect` (its `lines`
operation, rendered from the record `node_factory_floor_compute` writes every five minutes). The
tasks behind it are T3 (facts and source health forwarded by the effect), T4 (every line in
progress is a line), T5 (stage counts and stop kinds with evidence), T6 (the `lines` operation),
T7 (the reply check refuses a status reply without a real board stamp) and T9 (the board at session
start). **Replace this skill with the node-backed skill when T3 to T7 are merged and deployed and
the runtime proof of T8 passes.**

## The practice

A line is one thing in progress: a plan, a goal row, a ruling that someone must start, a piece of
work with a lane or a pull request but no plan, or a factory process that must run. Each line shows
where it is (its stage), who is on it (its owner, or none), and, when it is not moving, why, with the
row that proves it. A line that is not moving is stopped on the board. A hand-off, a merge that is
not running, a lane that ended partial, a blocker that names a person with no ask behind it, and a
source that could not be read are each their own state. None of them is progress.

The surprise this exists to prevent is the one where a fact was on the ledger, the pull request
watcher or a tick's output before anyone was surprised by it, and nothing put it in one list. Read
the board before any status reply and quote its time. A reply that says a line is fine, building,
optional or blocked on a person is checked against the board's stop for that line.

## When to use

- Before any status reply about what is in progress, stopped or blocked, and at session start.
- When a report says a line is blocked on a person, or that something is optional, and you have not
  read the row that says so.
- When a hand-off, a merge or a lane's end is the last thing you know about a line.
- When a factory process (the lab fill, a tick, the publish) has run and you cannot say what it did.

Stopped lines are not fixed here. A stopped line shows its andon cause (`lean_andon_stop`), and where
no cause row exists the cause is a why-chain, not a label (`lean_five_whys`). Where a surprise came
from a crossing between two stations, read the seam (`lean_seam_read`). Read the live surface and
not the account of it (`lean_go_and_see`).

## Steps by hand today

Locations come from the environment variables and contract keys the nodes use, never from a path
written down here: `OMNI_HOME`, `ONEX_PLANS_KB_PATH`, `ONEX_LEDGER_PATH`, the deployment overlay
`ONEX_SKILL_OVERLAY_ROOTS` for `node_factory_floor_effect`, and the `runtime.sources` keys of that
node's contract (`watcher_relpath`, `plans_today_dir`, `plans_today_file`, `linear_snapshot_glob`,
`output.relpath`). The eight dependencies below are the only inputs. Write the time you read each
one.

1. **Write the health of each dependency.** One header entry per dependency: its read time, its age,
   and one of `read`, `read-empty`, `stale` or `unread`, with the cause when it is not `read`.
   - the plans clone at its fetched head (each plan file and task manifest the lines name; a plan
     that failed to read is `unread` with its path and cause, never only "plan file not found");
   - the pull request watcher state (older than 90 minutes is `stale`);
   - the ledger window (`/omni:ledger-catchup 24` and the TERMINAL, RULING, RELEASE and ask rows;
     older than 30 minutes is `stale`);
   - the newest plans-today output (older than 1440 minutes is `stale`);
   - the Linear snapshot plans-today wrote (older than 1440 minutes is `stale`);
   - the running evidence, as the published factory floor record reports it
     (`sources.running_evidence_read`; false is `unread`; older than 60 minutes is `stale`);
   - the required contexts per repository, as the queue-status tick saved them (older than 120
     minutes is `stale`);
   - the goal file in the plans clone (older than 1440 minutes is `stale`).
   Also write the age of the published floor record and of the throughput tick record, which carry
   the held causes. An unread source is written as unread. It is never "fine" and never a zero.
2. **List the lines, by class, and write the coverage line.** Take the lines in this order and keep
   a line that is in two classes once, at the lower number:
   1. a declared floor line (the overlay's `plan_path_contains`; the floor record's lines);
   2. a plan plans-today selected (dated in 14 days, an In Progress ticket, or an open pull request);
   3. an open row of the goal file;
   4. a RULING of the last 14 days whose ticket or plan maps to no line above;
   5. a live CLAIM, or a TERMINAL in the window, whose ticket's work is not yet running and maps to
      no line above, and any open pull request or In Progress ticket that maps to none;
   6. a factory process the overlay declares under `processes` (the lab fill, the throughput tick,
      the floor publish, the queue-status tick, the pull request watcher, the landing controller).
   The coverage line says which classes you could read in full. When the plans-today output is
   older than its bar, write "UNREAD: plan selection from <time>"; when none was ever read, write
   "UNREAD: plan selection, lines unknown". Never write a count that looks complete when a class is
   not.
3. **For each line write its stage counts, its owner and `ruled_by`.** Stage comes from per-task
   evidence only: `planned` (no live CLAIM, no pull request), `building` (a live CLAIM, no pull
   request), `pr-open`, `merged` (every pull request the task names is merged), `running` (merged,
   and a deploy receipt or adoption row exists for each merge), or `unread`. A recorded `done`, a
   terminal outcome or a closed ticket proves no stage. A pull request closed without merging proves
   no stage. Owner is the live lane holding a CLAIM on a line ticket, or `none`. `ruled_by` lists the
   RULING ids that name the line.
4. **Walk the stop kinds in order and write each stop with its evidence and its cause.** A line may
   carry several. Each stop is one sentence and a row, check or read behind it:

   | Kind | When | Evidence |
   | -- | -- | -- |
   | `unread` | a source the line depends on is unread, errored or older than its bar | the source health entry |
   | `andon` | a HOLD in force, a failed gate, a red pull request, a ledger stop | the floor's reason and its row or check (`lean_andon_stop`) |
   | `lane-ended-blocked` | any TERMINAL in the window for a task of the line has outcome blocked, and nothing resolved that task after it | the TERMINAL's first clause or its hand-over MSG's |
   | `lane-ended-partial` | the same with outcome partial | the same |
   | `handed-off-unmerged` | a TERMINAL `outcome=handed-off` or a STATUS `handed-off=` and no merge of the pull request it names is proven | the row and the watcher record |
   | `merged-not-running` | a task is `merged` and not `running` | the merge and the running evidence read |
   | `held-with-real-red` | a pull request held by a review gate also fails a context that is required for its repository | the context names and the required-contexts read |
   | `release-at-old-head` | a RELEASE row's head differs from the watcher's head of that pull request | both rows |
   | `blocked-on-person` | a blocker sentence names a role and an ask to that role about the same ticket or pull request has no answer | the ask row |
   | `person-blocker-unverified` | the same blocker and no unanswered ask to that role about that subject exists | the row that named the role |
   | `ruled-not-started` | a RULING of 14 days names the line and no CLAIM that names the ruling's ticket or cites its id follows | the RULING row |
   | `process-did-nothing` | a process's last three run records at its interval all match its did-nothing form (for the lab fill, `eligible=0` with free slots) | the run rows |
   | `idle` | no movement in 24 hours and no owner | the newest row naming the line |

   Every stop that is not `unread` either cites a cause row (a CORRECTION, FRICTION or TERMINAL that
   names the line's ticket or process and says why) or is written "cause not recorded: run
   `lean_five_whys`". A sentence that names a person's role as the blocker is `blocked-on-person`
   only with the open ask behind it; without one it is `person-blocker-unverified`.
5. **Print the board in this order.** A header with each of the eight dependencies, its read time
   and age, UNREAD where it applies, and the coverage line. Then stopped lines first, oldest stop
   first; then building lines with no owner, then owned; then planned; then lines whose every task
   runs, one short row each. Each line prints: id, name, class, stage counts, owner, `ruled_by`, and
   one row per stop with its sentence, evidence and cause. A stopped line with a working lane reads
   "stopped, <lane> working on it", never "building".
6. **For a stop, show its andon cause, and where no cause row exists run `lean_five_whys`.** The
   cause of a stop is a chain of whys ending in a row or a check, not a label.
7. **Read the board before any status reply and quote its time.** A reply that names a line by its
   id, name, ticket or pull request uses the board's words for that line. A reply that says
   "everything is fine", "nothing is blocked" or "all green" is false while any line has a stop or
   any dependency is `stale` or `unread`.

Worked cases, each with the board's required print (private names are replaced by their kind):

- A delegated review that was never wired into the gate although its lanes ended "handed off":
  `lane-ended-partial` with the hand-over sentence, and `handed-off-unmerged` for every hand-off whose
  merge is not proven. Never a building or merged count for those items.
- A fill that ran and sent nothing for hours: `process-did-nothing` on the process line since the
  first of the consecutive runs, with the run count and the free slots; the fix a lane handed off is
  `handed-off-unmerged`; the cause is "cause not recorded: run `lean_five_whys`" until a cause row
  exists.
- Tasks reported blocked on a person when they were not: the line's real stop (the red check). A
  sentence that names the person's role with no open ask is `person-blocker-unverified`.
- A move described as optional after a ruling made it required: the line carries `ruled_by` and is
  `ruled-not-started` until a CLAIM names the ruling.
- Review-held pull requests that also carry a real required red: `held-with-real-red` naming the other
  required contexts; a pull request held only by the gate shows `andon` alone; a red on a context that
  is not required shows no `held-with-real-red`.
- A fix that sat green for hours on a RELEASE row written at an older head: `release-at-old-head`
  naming both heads and the time the old release was written.

## Factory task per step

Each step above is replaced by this task of the lean line board plan.

| Step | Factory task |
| -- | -- |
| 1 | T3 (facts and source health forwarded by the floor effect) |
| 2 | T4 (every line in progress is a line in the floor compute) |
| 3 | T5 (stage counts from per-task evidence) |
| 4 | T5 (the thirteen stop kinds with evidence) |
| 5 | T6 (the `lines` operation renders the board from the record) |
| 6 | T5 (cause rows and "cause not recorded") |
| 7 | T7 (the reply check refuses a status reply without a real board stamp), T9 (the board at session start) |

## Guards

- The board shows stops. It does not open or clear them, and it does not dispatch a lane.
- A stop with no row, check or read behind it is not written. If you cannot name the evidence, the
  line is `unread` with the cause.
- A line is never moved past what its evidence proves. A merged task that is not running is
  `merged-not-running`, not progress.
- Production promotion is untouched.

## What this skill cannot do

It cannot refuse a status reply, and it cannot keep the board current: it is read by hand at a
moment, so it names its read times and goes stale. Until the reply check and the five-minute record
exist, nothing makes a report agree with the board except you reading it first.
