---
description: Bootstrap skill for a retrospective on one coding session. Reads the session's primary sources (its transcript and the ledger rows it wrote), sorts each finding into navigation, missing automated check or standard, and prefers a deterministic check for any mechanical error. Each finding is written as a friction record through the friction-record skill, and a missing check also gets one ticket through the ticket node. Use after a session where agents lost time, repeated a mistake, or acted on a reading nobody checked. Adapted from the retro skill of github.com/mattpocock/skills (MIT).
mode: full
version: 1.0.0
level: intermediate
debug: false
category: process
bootstrap: true
skill_kind: methodology
argument-hint: "[session id or lane name; default: the current session]"
tags:
  - retro
  - retrospective
  - friction
  - bootstrap
author: omninode
---

<!--
Adapted from the `retro` skill in github.com/mattpocock/skills (skills/engineering/retro),
used under the MIT licence of that repository. The copyright and permission notice follow
as given and apply to the adapted text.

MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->

# Retro (bootstrap)

A retrospective on one coding session. You are not judging the session's result. You are looking
for changes to the agents' **environment** that make the next run cheaper: a pointer that would
have saved a search, a check that would have refused a mistake, a standard a reviewer should hold.

This is a bootstrap skill: the hand-run form of the practice. It holds no friction format, no
threshold and no ticket rule. Those belong to the friction skills it calls (see "Where each
finding goes"), so a change to them reaches retro without an edit here.

## How retro relates to the friction skills

- `friction-record` (the omni plugin) writes one friction row per item on the rolling work ledger,
  in the shape the ledger's friction guard enforces, with a ticket and a cost. It owns the row
  shape and the rule that a second occurrence files a ticket.
- `friction_triage` (this plugin) reads the friction registry and escalates surfaces that cross
  its threshold into tickets. It owns the threshold.
- `record_friction` (this plugin) is the older skill that appends to that registry. The ledger
  row is the surface that is enforced and read, so retro does not write there instead of the ledger.
- `retro` is the step before all three: it looks at a whole session, finds the items worth
  recording, and decides what kind each one is. It then hands each item to the skill that owns the
  write. It is not a weekly team retrospective (the Friday stand-up section is that); it reads
  one session's own sources.

If retro would need a field or a threshold those skills lack, say so in the pull request that
changes retro. Do not add it here.

## Steps

### 1. Name the session and read its primary sources

The session is the one the user names. With no name, it is the current session. Two sources are
primary:

- **The transcript.** Find it with what the harness gives you: the `session-resume` skill says how
  to open a session by its id, and a lane's own result file or report names its session. Never
  copy a transcript path from another host into a finding; say how to find it.
- **The ledger rows the session wrote.** Rows carry `lane=`, `ticket=` and a timestamp. Read them
  with the ledger readers (`/omni:ledger-ask`, or `/omni:ledger-catchup` for a recent window) by
  lane name and date. A finding needs a row or a transcript turn you can cite by its timestamp and
  lane. A finding with neither is written from the reporter's own description, and the finding
  says so: an event that no row records is itself something to sort.

### 2. Look for findings in these categories

Sort every finding into exactly one of three kinds.

**Navigation.** The agent took long to find something a pointer would have shown. Look at how
easy it was to find the right files, hidden dependencies between files, and whether a **navigation
pointer** (a line in a steering file, a skill description, a doc link) would have shortened the
search. Use it when the session spent a long time locating a piece of information, or when a
decision was recorded somewhere a later session would not look.

**Missing automated check.** An error a check could have refused: a lint, a type check, a test, a
hook, a CI job, a file-location linter, a freshness check on a reading. Before you propose one,
read the repository's own check command and its CI workflow. If a check already exists but is
unwired, skipped or silently broken, that is the finding, not a new check. A repository with no
guardrail at all (no pre-commit hook and no CI job running its lint, type check or tests) is
itself a finding: an unchecked repository is a standing missed opportunity, not a neutral default.

**Standard.** A judgement the reviewer should hold: cross-file consistency, "matches the
surrounding style", anything no check could ever substitute for. Use it when the review stage failed
to catch a mistake that needs judgement, or when an existing standard should be removed or
clarified.

**Classify a mechanical error first.** A mechanical error is a fixed syntactic pattern, a banned
API, an import shape, a file-location rule, or a reading used without an age check. For any
mechanical error, build a deterministic check, whichever of a lint rule, a hook, a CI job or a test
is cheapest for the repository's language and existing guardrails. Prefer building the check over
writing a rule. Reserve written standards for real judgement calls. A rule a check could enforce,
written as prose, is the weaker fix and the reviewer will keep missing it.

### 3. Check the environment for waste

These are not kinds of their own. Each one changes what you write in a finding, so look for them
while you sort:

- **Steering files carry navigation, not rules.** The files pushed into every agent's context
  (the repository's top-level instructions) should hold pointers to other files. A rule that grew
  there belongs in a check (a missing automated check) or in the reviewer's standards (a standard).
  A line that does not change what an agent does is a no-op; propose deleting it when the file is
  large.
- **Tool economy.** Note an expensive tool call or a token-heavy command a cheaper one would
  replace, such as reading a whole log where a filter would do.
- **Information access.** Note a crucial fact the agent could not see: a log nobody teed, a
  service it could not read. Giving read access is a fix too, and it usually files as a
  navigation or missing-check finding.

### 4. Remember the two stages

All work has an implementation stage and a review stage. The implementation agent carries the most
context pressure: it explores, writes and debugs. The review agent receives a diff and needs no
exploration, so it is the place to impose standards. Put a standard in the review stage, not in
the implementation agent's instructions. Put a check where it refuses the mistake before either
stage spends time on it.

### 5. Present the candidates, most severe first

Present the findings in order of severity: cost in lane time, how often it recurred, whether it
reached a merge. For each give the kind, the reason for the kind, the evidence (a row or a turn,
by timestamp and lane), and the write it leads to.

## Where each finding goes

Retro writes every finding through the skill that owns the write, one call per item:

1. **Every finding becomes a friction record.** Invoke `friction-record` with the item. It writes
   the ledger row, applies its own shape and cost rules, and adds the pointer in the skill whose
   procedure hit the friction. Run its own duplicate search first and cite an existing row rather
   than writing a second one for the same defect.
2. **A missing automated check also gets one ticket**, one per missing check and never two on one
   subject. Create it through the ticket node (`onex ticket create`) by way of the `create-ticket`
   skill, which owns the parent, the Gate line and the criteria rules. That skill also owns when a
   first occurrence is only a friction row; follow it. If your brief grants no authority to mint
   a ticket, record that in the friction record and name who files it.
3. **Navigation and standard findings** stay friction records. `friction_triage` turns a surface
   that keeps recurring into a ticket by its own threshold. A standard is then put to the reviewer's
   standards by the ticket that follows, not by an edit made during the retro.

Retro itself writes no ledger row about a session other than the one it was invoked for, and
makes no change to a check, a steering file or a standard. It reports and records.

## Worked example

A retro of a long orchestration session, run from the ledger rows the session left. Hosts and
repositories are described by role. Each finding carries what happened, its kind, why that kind,
and the write that follows (text only; this example writes no row and no ticket).

### Finding 1: parked bottom-layer lines

**What happened**: Between 09:06Z and the afternoon the hourly prove-running pass wrote 112
blocked rows covering 20 distinct pull requests, mostly on the lowest layers of the platform.
Each row's owner cell read as parked under the layer rule, with "no step taken" and, in several,
a note of the step the line would need (a dev roll that builds an image at or after the merge)
that was cut off mid-word. The same blocked row came back every hour. Nothing in a row points to
where the parking is recorded or what releases it.

**Kind**: navigation

**Why this kind**: No check erred; the parking was a deliberate ruling. The cost was that a later
session met 112 near-identical blocked rows and had to dig for the ruling that explained them. A
pointer in the row (the ruling's timestamp and the ticket that releases the line), in a cell that
is not cut off, would have shown it at once.

**Would be written**: One friction record naming the repeated, truncated parked rows, with the
correct move "carry the ruling timestamp and the releasing ticket in a cell that is not
truncated". No ticket: this is not a missing check.

### Finding 2: a stale swap reading that kept lanes off a lab host

**What happened**: One status row in the session reads a lab host's swap use ("swap is 74
percent used so it needs 2") and holds that host's lane cap low on the strength of it. The row
gives the figure but not the time it was taken. No row records that the reading was stale, or
which lanes it kept off the host: the finding rests on the operator's description of the session,
and that absence is part of it. Nothing wrote the reading's age down, so nothing could refuse it.

**Kind**: missing automated check

**Why this kind**: Acting on a reading with no age is a mechanical error. A deterministic check
would have refused it: placement ignores a capacity or swap reading older than a stated limit and
reads it again. Writing "check that the reading is fresh" as a rule would leave the same gap.

**Would be written**: One friction record, and one ticket for the check: a placement check that
refuses a reading with no timestamp or one past its age limit, with a test built from the row
above as its fixture.

### Finding 3: hosts never added to the lane pool

**What happened**: Late in the session a lab host read about 2 percent CPU with most of its
memory free and its GPU idle. A credential for it sat in the pool's token store and it ran CI
runners, but it was not among the hosts remote lanes are placed on. The lane sent to find out why
was told to check three places (the pool overlay, the capacity advertisement, a cap of zero). A
lane that later tried to read the host could not.

**Kind**: missing automated check

**Why this kind**: A census of the hosts the lab declares against the hosts the lane pool lists
would have caught the omission the day the host was declared. That is a fixed comparison of two
lists, so it is mechanical. A written note to "remember to add new hosts to the pool" would not
catch it.

**Would be written**: One friction record, and one ticket for the census check: declared hosts
against pool hosts, failing when a declared host is neither in the pool nor listed with a stated
reason.

## Rules

- One session per retro. A finding about a different session is another retro.
- Cite by what can be re-read: a ledger row by its leading timestamp and lane, a transcript turn,
  a pull request, a ticket. Never a ledger line number, which a roll renumbers.
- Write the kind and the reason for it for every finding. A finding with no reason for its kind
  is a guess.
- Keep person names, host names and private repository names out of a finding that is bound for
  a public file; describe them by role.
- Present candidates to the user. Do not apply a fix during the retro.
