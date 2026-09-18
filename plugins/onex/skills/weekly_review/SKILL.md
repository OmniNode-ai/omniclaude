---
description: Produce a weekly work review for one person against a declared rubric. The rubric —
  roles, criteria, anchors, score bands, identity sources, output location and trend measures — is
  supplied entirely by a contract overlay; this skill owns the method, never the content.
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - review
  - rubric
  - overlay
  - read-only
author: OmniClaude Team
composable: false
args:
  - name: --person
    description: "Primary identity handle for the person being reviewed"
    required: true
  - name: --role
    description: "A role_id declared by the rubric overlay"
    required: true
  - name: --window
    description: "Review window as <start>..<end>, ISO dates"
    required: true
  - name: --prior
    description: "Path to the previous review for this person, for the trend read"
    required: false
skill_kind: methodology
# A methodology skill, not a dispatcher: its six steps are a method a reviewer
# follows, and the only computation anywhere in it is one band lookup. There is
# no node for the steps to delegate to, because scoring a person is judgement
# and this skill deliberately produces no verdict. The declaration rests on
# that reason alone and names no sibling skill: this comment used to cite one,
# that skill was later retired, and an exemption justified by pointing at
# another surface stops being justified the moment that surface is deleted.
boundary_exempt: true
---

# /onex:weekly_review — one person, one window, one rubric

A weekly work review is a personnel document. It is read-only work: send no message, comment on no
ticket, comment on or review no pull request, push nothing. Write the declared output files and
stop.

This skill owns the **method**: identity resolution, controlled collection, scoring against declared
anchors, the trend read, and what may appear in which output file. It owns **no rubric content**.
Roles, criteria, anchor texts, score bands, identity sources, the output location and the trend
measures all come from a contract overlay. Nothing about any particular organization, code host,
tracker or chat product is built into this skill or its defaults.

## The rubric is base plus overlay

Same mechanism as every other contract overlay here. A committed base declares the structure and
supplies no content; an overlay supplies the content; the two are deep-merged with the overlay
winning, and the merged mapping validates into one model.

- **Base**: `weekly_review_base.yaml`, packaged beside the loader module in
  `omniclaude.skills.weekly_review`. It declares structure only.
- **Overlay selector**: the `WEEKLY_REVIEW_OVERLAY_PATH` environment variable. It names a file. It
  never carries rubric content.
- **Loader**: `omniclaude.skills.weekly_review.load_weekly_review_rubric`.

**Where the overlay comes from is the operator's answer, not this skill's.** No overlay ships here
and none is discovered. The selector takes an absolute path to a file the reviewer already has, and
an organization that keeps its rubric in a private repository points the selector into that clone.
If you do not know which file to name, that is the question to ask before the run, not a gap to fill
with a guess.

**Fail-fast, first step, before anything else.** Resolve `WEEKLY_REVIEW_OVERLAY_PATH` and stop if it
is unset, empty, or names a file that does not exist. Report the variable by name and stop. There is
no default overlay and no fallback rubric: a bare base declares no role, no criterion, no identity
source and no output location, and `assert_resolved` refuses it. A review scored against an empty
rubric and written to an undeclared location is worse than no review.

```
uv run python -c "from omniclaude.skills.weekly_review import load_weekly_review_rubric as L; \
r = L(); print(r.rubric_version, [x.role_id for x in r.roles])"
```

Then resolve `--role` against the overlay's declared roles. An unknown role stops the run and the
message lists the roles the overlay actually declares. Read the role's `rubric_document` before
scoring: it is the human-readable standard, and it is authoritative wherever it and the overlay
transcription disagree. Resolve that pointer with `rubric.resolve_rubric_document(role_id)` and
open it. A transcription carries less than the standard it transcribes, and this document is the
whole of the mitigation for that, so a pointer you cannot open is a stop, not a note.

## Step 1 — resolve every identity, exactly one match each

For every `identity_source` the overlay declares, run its `resolve_command` for `--person` and
record what identifies the person on that surface and how it resolved.

**One match means one exact match on the source's declared `match_field`, not one row returned.**
A resolve command that searches returns near matches for an unambiguous handle: three logins
sharing a prefix is not an ambiguous identity, and stopping there is a false stop. Narrow the rows
to those whose `match_field` equals `--person` exactly, then apply the rule below. Record both
numbers: how many rows came back, and the one that matched exactly.

- Zero exact matches, or more than one: **stop and say so**. Never guess, never pick the likeliest.
- A source marked `required: false` that returns nothing is recorded as absent, not as zero
  activity.

## Step 2 — control every source before trusting a count

Before any count is believed, run the source's declared `positive_control` — the same query shape
against an identity known to be busy — and confirm it returns many rows.

- A zero from a query that has not been controlled is an **unverified query**, not an absence.
- **Never suppress stderr on a counting command.** A command that errors with its stderr discarded
  returns zero rows and reads exactly like a clean bill of health.
- Count matching event nodes, never a timeline total. A total ignores type filters and inflates the
  number, and an inflated count of that kind reads as a process failure that never happened.
- **Window every count to `--window`, including event nodes.** An event attached to an artifact
  created inside the window can itself fall outside it. Filter on each event's own timestamp, not on
  the artifact's. An unwindowed count reads as a real number and is wrong in the direction that
  makes the person look worse.
- **Follow the cursor on every paged source.** A search that returns exactly one page has not said
  there is no second page. Page until the source says the listing is exhausted, and if it cannot,
  record the result as a sample of a stated size rather than as the whole window.
- State every sample size. Never imply an exhaustive read that did not happen.

## Step 3 — collect the window

Collect only what the overlay's criteria say to read. Each criterion carries `what_to_read`; that is
the collection instruction, and it is the overlay's, not this skill's.

Record, for each countable criterion, the single number its `measure` names. Record, for every
criterion, candidate deciding artifacts: the quote, run, commit, ticket or readback that would
settle it.

A measure that could not be collected is reported as **not measured**. It is never reported as the
lowest score. An uncollected measure is a gap in the review, not a finding about the person.

## Step 4 — score

For a criterion with no `measure`, read the five anchor texts and pick the one the evidence meets.

For a countable criterion, call `criterion.base_score(value, sample_size=n)`. The bands are
exhaustive and non-overlapping, so the value lands in exactly one and two reviewers get the same
base score from the same number.

**The sample size is a required argument and it is written beside the score.** A ratio of 0.0 from
six observations and a share of 0.09 from eighty-six both land in a band, and only one of them can
carry a score. Where the sample is too thin to support the band it lands in, report the criterion
as **not measured at this sample size**, give the raw numbers, and say so — that is a gap in the
review, not a finding about the person.

Then, and only with named evidence:

- Apply `promotion_to_five` **from the top band only**, via
  `criterion.promoted_score(base, condition_met=...)`. A promotion is a step off the top of the
  bands, not a bypass of them: a base below the top band is returned unchanged even when the
  condition holds, because a promotion clause that lifts any base to five makes the bands
  decorative. If the evidence warrants more than the band gives, say so as a stated override.
- Apply any `caps` entry whose condition is met; a cap overrides the band downward.
- If the written anchor is met on its literal text but the evidence reads higher or lower, **state
  the override** in that criterion's section with the reason. Stating the override is better than
  quietly inflating or quietly deflating the rubric.

Every criterion names **one deciding artifact**. If no single artifact decided it, say the score is
not yet supported rather than picking one.

Label every claim fact, inference or speculation. A fact cites an artifact. An inference says what
it rests on. Speculation is marked as speculation or it is cut.

State the honest limits rather than implying them. Where a source cannot answer a question, name the
question it cannot answer. Where a count is impossible, say the score rests on named instances
instead, and say in which direction that biases it.

Report volume — merges, lines, commits — as context, in a paragraph that says in terms that it is
not progress.

## Step 5 — trend against the prior review

Read `--prior` if given, otherwise the most recent prior file for this person in the overlay's
`output_directory`. State the direction of every `trend_measure` with both numbers. With no prior
file, say this is the baseline window and give the numbers without a trend.

Close by saying plainly whether the window trends toward what the role needs or away from it, and
name two things that would change the reading inside one more window. Both must be checkable.

## Step 6 — write the declared output files

Write one file per `output_files` entry, into the overlay's `output_directory`, using its
`filename_template` with the window end date and the person's identifier.

**Check every target before writing any of them.** Call
`rubric.resolve_output_paths(person=..., date=...)` first and look at each path. Stop the run if a
target file already exists, and say which one: that file is the previous review, it is what step 5 reads the trend
against, and a run that writes over it destroys the baseline the next run needs. Re-running a window
deliberately is a decision for the reviewer to make with the old file in hand, never something a
write does silently.

**Resolve the output directory before writing anything, and never against the working directory.**
Every path an overlay declares is anchored one of two ways: absolute, or carrying `${VAR}`
references the reviewing environment supplies. Call `rubric.resolve_output_directory()`; it refuses
a bare relative path and an unset variable by name, because resolving against wherever the run
happened to start would put a personnel document in a plausible-looking wrong place with no error.
The same rule and the same refusal apply to a role's `rubric_document`, via
`rubric.resolve_rubric_document(role_id)` — and the two anchor on different variables, because the
reviews and the role standards they are scored against do not live in the same place.

Each entry declares its `voice`, what it `may_contain` and what it `must_not_contain`. The
must-not-contain list is the half that matters: it is what keeps a score out of a file meant for the
person and a private note out of a shared one. Check each written file against its own list before
finishing, and rewrite rather than shipping a violation.

**A length bound in `voice` is a real constraint and nothing measures it for you.** Where an entry
states a word range, count the words of the file you actually wrote and cut until it complies.
Writing long and trimming afterwards costs several passes; write to the bound.

Write every declared file every run. A file meant for the person is never skipped and never replaced
by handing them a file written for someone else.

## What this skill does NOT do

- Carry any rubric content, role name, criterion, anchor or band of its own. All of it is overlay.
- Produce a verdict from raw collection output. The only computation is a band lookup; the judgement
  is the reviewer's and is recorded with its evidence.
- Write anything outside the overlay's `output_directory`.
- Send, comment, review or push anything, on any surface.
- Score the absence of peer code review given. That is a policy question for the overlay's criteria,
  never an assumption of the method.

## Related

- **Rubric contract**: `omniclaude.skills.weekly_review.ModelWeeklyReviewRubric`
- **Loader**: `omniclaude.skills.weekly_review.load_weekly_review_rubric`
- **Base rubric**: `weekly_review_base.yaml`, packaged beside the loader
- **Overlay selector**: `WEEKLY_REVIEW_OVERLAY_PATH`
