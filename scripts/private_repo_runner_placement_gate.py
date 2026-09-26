#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Private repositories never run CI on GitHub-hosted Actions runners.

Operator ruling, 2026-09-14, firm: a PRIVATE repository's CI runs on the lab
fleet. GitHub-hosted runners are for PUBLIC repositories, where their minutes
are free. This gate is the mechanical half of that ruling (operating rule 5 --
a detection surface that is not a merge gate is advisory, and advisory checks
get ignored).

WHAT IT DECIDES, and the two ways of getting it wrong that it refuses.

Placement is read from each job's PARSED `runs-on`, never from whether a file
mentions a routing variable. A workflow may name the trusted seam in a comment
beside a job pinned to a literal, and a text-level count reads that job as
seam-driven when it answers to nothing. The reverse error is just as easy: a
job whose `runs-on` is an expression is not "unknown" -- it resolves, live, to
whatever the repository's own variable scopes currently hold, and that
resolution is the placement. So an expression is RESOLVED here against live
variables rather than skipped.

THE VISIBILITY IS RESOLVED LIVE. The rule is about private repositories, and a
hardcoded list of which repositories those are goes stale the first time
somebody flips one. Visibility comes from the GitHub API for the repository
under test; if it cannot be resolved, the gate FAILS CLOSED and says so,
because a gate that cannot tell whether the rule applies has not passed -- it
has not run.

FORK ISOLATION OUTRANKS THIS RULE, AND THE ORDER IS NOT A JUDGEMENT CALL.
The canonical selector sends a pull request opened from a fork to the public
runner class and everything else to the trusted seam. Both halves are required
in a private repository: this ruling says its CI does not run on hosted
runners, and fork isolation says untrusted code never reaches a fleet runner
that bind-mounts the lab credential directory. The routing node's contract
settles which yields -- only a CAPACITY reason may be reversed for a repository
that may not run hosted, never a trust reason such as fork isolation -- so a
hosted branch GUARDED BY A FORK TEST is the required placement, not a
violation, and it is exempt here.

The exemption is scoped to ONE CELL of the event matrix and cannot spread: it
applies to the arm selected when the event is a pull request (or a pull-request
review) whose head repository is a fork, and to nothing else. The arm an
ordinary same-repo pull request selects is judged on the ordinary terms, and so
is the arm a push, a dispatch or a schedule selects -- including when the guard
that reaches it is spelled as a fork test, which is precisely the case that
went unseen for nine days. A fork guard with nothing to fall back to is not
excused either: under every non-fork event its guard is false, no arm is
selected, `runs-on` evaluates to a falsy value, and the job cannot start, which
is reported as its own finding rather than passed over.

A `uses:` JOB IS JUDGED WHERE THE RUN IS BILLED, NOT WHERE THE WORKFLOW LIVES.
A job that calls a reusable workflow has no `runs-on` of its own, and the
called workflow's `runs-on` is evaluated in the CALLER's variable scopes, not
the defining repository's. Reading the placement in the repository that DEFINES
the workflow is therefore the wrong reading twice over: that repository is
usually public, where a hosted label is the correct answer, while the run the
label places is billed to the private caller. Measured on omnistream, whose
REQUIRED `kb-doc-gate` job calls a public reusable, resolves the trusted seam
in omnistream's own scope (no repository shadow, organisation value hosted),
lands on a hosted label in a private repository and does not start at all --
three seconds, no runner, no steps, failing every run since 2026-09-02 while
this gate reported the repository green.

So a `uses:` job is RESOLVED: the called workflow is fetched at the ref its
caller pins, each of its jobs' `runs-on` is resolved against the CALLER's
variables, and the verdict is reported against the caller's job. Nesting is
followed to GitHub's own limit and refused beyond it. A called workflow that
cannot be fetched, or whose jobs cannot be parsed, is a REFUSAL -- a gate that
cannot see where a required job lands has not passed, it has not run.

A mutable ref (`@main`, `@dev`, a tag) is RESOLVED rather than refused, and the
commit it resolved to is printed beside the verdict. Refusing it was considered
and rejected: the content at a mutable ref is exactly what the next run will
execute, so resolving it is the true reading, and four of the seven private
repositories pin a required gate that way today -- refusing them would take the
enforcement surface down over a supply-chain concern that is not this gate's
subject. What the printed commit buys is that a verdict can be re-derived: it
names the bytes it judged.

PLACEMENT IS DECIDED PER TRIGGER EVENT, BECAUSE A SELECTOR IS A FUNCTION OF THE
EVENT (OMN-18205 residual 4). A `runs-on` expression does not have one answer.
`A && X || Y` places the run on X or on Y depending on whether A holds, and A
is nearly always a question about the EVENT -- which means the same job lands
on a different runner class under a pull request than under a push. Reading the
arms without ever asking which event reaches them is the shape of blindness
this gate shipped with, and it had a measured cost: 21 expressions in
omninode_infra tested `github.event.pull_request.head.repo.full_name` against
`github.repository` with no event test in front of it. On any event carrying no
pull-request payload that field is null, the inequality holds, and the run took
the PUBLIC HOSTED arm. Every push, `workflow_dispatch`, `repository_dispatch`
and `schedule` run in a private repository with no hosted budget therefore
acquired no machine at all: empty `runner_name`, `labels: ["ubuntu-latest"]`,
zero steps. `main`-push CI was ungreenable for nine days (OMN-18616) while this
gate reported the repository green, because it exempted every one of those arms
on a textual fork-test match and never asked when the guard was true.

So each job's arms are now EVALUATED, once per event, against a fixed matrix of
event contexts -- and the guard is evaluated, not matched. The two spellings of
"is a fork" are no longer a regex carve-out: under a fork pull request the fork
guard is simply TRUE and the hosted arm it selects is exempt, and under a push
the same guard is TRUE for the wrong reason and the hosted arm it selects is a
FINDING. One mechanism, both readings, no list of blessed spellings to keep in
step with the estate.

THE EVALUATOR FAILS CLOSED ON ANY SHAPE IT CANNOT READ. It understands the
subset this estate writes: `&&`, `||`, `!`, `==`, `!=`, `contains()`,
`fromJSON()`, string and boolean literals, and the handful of `github.*`
context fields that decide routing. Anything else -- an ordering comparison, an
unmodelled context field, a function it has not been taught -- is a REFUSAL
naming the workflow and the job, never a pass. A gate that cannot tell which
arm an event reaches has not judged the job.

THE VERDICT IS SCOPED TO THE EVENTS THE WORKFLOW DECLARES, and that is a
deliberate narrowing rather than an oversight. A job cannot run under a trigger
its workflow does not carry, so a hosted resolution under an undeclared event
is latent, not live -- and the pull request that ADDS the trigger is judged by
this same gate at that moment, which is the mechanism rather than the hope.
`infra-consistency-check.yml`'s own comment had predicted the failure in those
exact terms: "Harmless while this workflow has only a pull_request trigger, and
a live defect the day somebody adds a push trigger." A latent cell is still
PRINTED, on every run, under LATENT -- visibility over the whole matrix,
enforcement over the declared subset. A workflow whose `on:` block declares an
event outside the fixed matrix is modelled with no pull-request payload, which
is the one property every non-pull-request event shares; a `workflow_call`
workflow is judged over the WHOLE matrix, because the event that reaches it is
whatever its caller fired and this gate cannot know it.

A JOB THAT CANNOT MOVE GETS A NAMED REASON, NOT A QUIET PIN. The escape hatch
is a per-job annotation in the workflow file recording WHY the fleet cannot
carry it and the ticket that will move it:

    # private-repo-hosted-ok: <reason> (<OMN-nnnnn>)

placed on the line immediately before, or anywhere inside, the job's mapping.
A bare pin with no annotation is the failure. There is no global allowlist
file and no `--force`: an allowlist is where exemptions go to stop being read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

# A label naming a GitHub-hosted image. Deliberately prefix-matched rather than
# enumerated: `ubuntu-latest`, `ubuntu-24.04`, `macos-15`, `windows-2025` and
# every future image name share these three stems, and an enumeration would go
# stale into a false green.
HOSTED_LABEL = re.compile(r"^(ubuntu|macos|windows)-", re.IGNORECASE)

ANNOTATION = re.compile(
    r"#\s*private-repo-hosted-ok:\s*(?P<reason>.+?)\s*\((?P<ticket>OMN-\d+)\)",
    re.IGNORECASE,
)

# The same marker WITHOUT the rest of the pattern on its line. A comment block
# wrapped across several lines puts the ticket on a line the annotation regex
# cannot reach, so the annotation reads as absent and the job is reported as a
# bare pin -- a correct verdict for an incomprehensible reason, and the author
# sees a gate that ignored the exemption they wrote. Detected separately so the
# failure names itself: an annotation is ONE line, reason and ticket together.
ANNOTATION_MARKER = re.compile(r"#\s*private-repo-hosted-ok:", re.IGNORECASE)

VAR_REF = re.compile(r"vars\.([A-Z0-9_]+)")
FALLBACK_FOR = "vars.{name}\\s*\\|\\|\\s*'(\\[[^']*\\])'"

# The two spellings a JOB-level `uses:` may take. A job-level `uses:` names a
# reusable WORKFLOW, never an action, so both forms carry a `.github/workflows`
# path -- anything else is a shape this gate has not been taught to read, and
# is refused rather than skipped.
USES_CROSS_REPO = re.compile(
    r"^(?P<slug>[^/]+/[^/]+)/(?P<path>\.github/workflows/[^@]+)@(?P<ref>.+)$"
)
USES_LOCAL = re.compile(r"^\./(?P<path>\.github/workflows/.+)$")

# A ref that names an immutable commit. Used only to decide whether the commit
# a mutable ref resolved to is worth printing -- never to refuse a ref.
SHA_REF = re.compile(r"^[0-9a-f]{40}$")

# GitHub evaluates at most four levels of nested reusable workflows. Past that
# a run would not execute, so a tree claiming to go deeper is malformed rather
# than merely large, and is refused.
MAX_NESTING = 4


class GateError(RuntimeError):
    """A condition under which the gate refuses to return a verdict."""


@dataclass(frozen=True)
class Finding:
    workflow: str
    job: str
    runs_on: str
    resolved: str
    why: str
    branch: str
    # The trigger events under which this placement is taken, comma-joined.
    # Named rather than summarised: "push, schedule" and "every event" are
    # different defects with different fixes, and a finding that says only
    # "hosted" sends the reader back to re-derive which trigger reaches it.
    events: str = ""
    # Empty for a job that declares its own `runs-on`. For a `uses:` job it
    # names the called workflow and the job inside it whose placement this
    # finding is about, so the report says WHERE to make the change -- which is
    # not the file the finding is reported against.
    via: str = ""


@dataclass(frozen=True)
class Branch:
    """One arm of a `runs-on` selector, with the guard that reaches it.

    `guard` is empty for the arm an expression falls through to. Whether that
    guard HOLDS is not a property of the arm -- it is a property of the event,
    so it is answered per event context by `_guard` rather than stored here.
    """

    guard: str
    labels: list[str]
    how: str

    @property
    def hosted(self) -> list[str]:
        return [label for label in self.labels if HOSTED_LABEL.match(label)]

    def describe(self) -> str:
        return f"guarded by `{self.guard.strip()}`" if self.guard else "default arm"


class _Missing:
    """GitHub's `null`: the value of a context field the event does not carry.

    A distinct sentinel rather than `None` because `None` is also what an unset
    Actions variable resolves to elsewhere in this file, and conflating "this
    event has no pull request" with "nobody set this variable" is how a gate
    reports the wrong reason for the right verdict.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "null"


MISSING = _Missing()

# The head-repository slug a FORK pull request carries. Any slug that is not
# the repository under test works; a readable one makes the report legible.
FORK_SLUG = "an-outside-contributor/fork-of-this-repository"


class _Ambiguous:
    """A context field whose value is real but not knowable from the tree."""

    __slots__ = ("matches",)

    def __init__(self, matches: bool) -> None:
        self.matches = matches

    def __repr__(self) -> str:
        return "<a branch name this gate cannot know>"


# Fields carrying a ref. Split by whether the event has a pull request: on a
# non-pull-request event `github.base_ref` and `github.head_ref` are empty,
# which IS knowable, while `github.ref` always carries a value and never is.
PULL_REQUEST_REF_FIELDS = ("github.base_ref", "github.head_ref")
ALWAYS_UNKNOWN_REF_FIELDS = ("github.ref", "github.ref_name", "github.ref_type")


@dataclass(frozen=True)
class EventContext:
    """One cell of the event matrix: what the `github.*` context holds.

    The model has exactly one dimension that decides routing in this estate --
    whether a pull-request payload is present and whether its head repository
    is a fork -- so `head` carries it in three states and every other event
    field is derived. Keeping it to one dimension is what makes the matrix
    honest: a richer model would invite the reader to believe cells it has not
    actually been taught to evaluate.
    """

    key: str
    event_name: str
    head: str  # "fork" | "self" | "absent"
    fork_exempt: bool
    why: str
    # How a REF-VALUED field that this gate cannot know resolves in this cell.
    # `github.base_ref` on a pull request is a real branch name, but which one
    # depends on the pull request, not on the repository -- so a static reading
    # cannot say whether `github.base_ref == 'dev'` holds. Rather than refuse a
    # shape the estate actually writes, or guess one answer, the cell is
    # SPLIT: the same event is evaluated once with such a comparison matching
    # and once with it not, and a hosted arm reachable under EITHER is a
    # finding. That is fail-closed in the direction that matters -- if some
    # pull request can reach the hosted arm, some pull request will.
    unknown_ref_matches: bool = False

    def head_field(self, name: str, slug: str) -> object:
        if self.head == "absent":
            return MISSING
        if name == "full_name":
            return FORK_SLUG if self.head == "fork" else slug
        return self.head == "fork"


# The fixed matrix. Ten of these eleven cells are the events named on OMN-18205
# residual 4; the two `pull_request_review` cells are added because the estate's
# own canonical guard names that event beside `pull_request` in its `contains()`
# list, and a matrix that never fires it would leave half of that guard
# unexercised.
EVENT_MATRIX: tuple[EventContext, ...] = (
    EventContext(
        "pull_request:fork",
        "pull_request",
        "fork",
        True,
        "a pull request opened from a fork -- the ONE cell where a hosted "
        "placement is required rather than forbidden, because fork isolation "
        "is a trust constraint and outranks the cost ruling",
    ),
    EventContext(
        "pull_request:base",
        "pull_request",
        "self",
        False,
        "an ordinary pull request whose head is a branch of this repository",
    ),
    EventContext(
        "pull_request_review:fork",
        "pull_request_review",
        "fork",
        True,
        "a review submitted on a pull request opened from a fork",
    ),
    EventContext(
        "pull_request_review:base",
        "pull_request_review",
        "self",
        False,
        "a review submitted on a same-repository pull request",
    ),
    EventContext("push", "push", "absent", False, "a push to a branch or tag"),
    EventContext(
        "workflow_dispatch",
        "workflow_dispatch",
        "absent",
        False,
        "a manual run from the Actions tab or the API",
    ),
    EventContext(
        "repository_dispatch",
        "repository_dispatch",
        "absent",
        False,
        "a cross-repository trigger -- the event behind the omniweb "
        "pin-drift job that acquired no runner at all",
    ),
    EventContext("schedule", "schedule", "absent", False, "a cron run"),
    EventContext(
        "merge_group", "merge_group", "absent", False, "a merge-queue evaluation"
    ),
    EventContext(
        "workflow_run",
        "workflow_run",
        "absent",
        False,
        "a run chained off another workflow completing",
    ),
    EventContext("release", "release", "absent", False, "a release being published"),
)


def _unreadable(fragment: str, where: str) -> GateError:
    return GateError(
        f"{where}: the runs-on guard fragment {fragment!r} is a shape this "
        "gate cannot evaluate, so which runner each trigger event selects is "
        "unknown. Placement is counted from the PARSED runs-on under every "
        "event, and a fragment that cannot be evaluated is not a job that is "
        "safely placed -- reporting it green is exactly the silence that left "
        "main-push CI ungreenable for nine days (OMN-18616). Teach the "
        "evaluator the shape, or spell the guard in one it already reads. "
        "THE GATE DID NOT RUN."
    )


def _strip_parens(text: str) -> str:
    """Remove balanced outer parentheses, quote-aware.

    Quote-aware because a JSON array literal inside `fromJSON('...')` may carry
    a parenthesis, and a naive strip would unbalance the fragment and then
    refuse a shape it can in fact read.
    """
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        quoted = False
        closes_early = False
        for index, char in enumerate(text):
            if char == "'":
                quoted = not quoted
            elif not quoted:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0 and index != len(text) - 1:
                        closes_early = True
                        break
        if closes_early or depth != 0:
            break
        text = text[1:-1].strip()
    return text


def _call_args(text: str, name: str) -> list[str] | None:
    """The argument fragments of `name(...)`, or None if this is not that call."""
    text = text.strip()
    prefix = f"{name}("
    if not text.lower().startswith(prefix) or not text.endswith(")"):
        return None
    inner = text[len(prefix) : -1]
    depth = 0
    quoted = False
    for char in inner:
        if char == "'":
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return None  # the trailing `)` closed something else
    if depth != 0 or quoted:
        return None
    return _split_top_level(inner, ",")


def _truthy(value: object) -> bool:
    """GitHub's truthiness: null, false, the empty string and 0 are falsy."""
    if isinstance(value, _Ambiguous):
        # A ref field read bare is a non-empty branch name, so it is truthy
        # whichever branch it names -- nothing ambiguous about that.
        return True
    if value is MISSING:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (int, float)):
        return value != 0
    return True


def _as_number(value: object) -> float:
    """GitHub's numeric cast, used when the two operand types do not match.

    Null casts to 0, a boolean to 0 or 1, a string to its numeric value or to
    NaN when it does not parse -- and the empty string to 0. NaN is never equal
    to anything, including itself, which is exactly the behaviour that makes
    `null != 'OmniNode-ai/omninode_infra'` hold.
    """
    if value is MISSING:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value.strip() == "":
            return 0.0
        try:
            return float(value.strip())
        except ValueError:
            return float("nan")
    return float("nan")


def _equal(left: object, right: object) -> bool:
    """GitHub's `==`: same types compare directly, mixed types cast to number.

    Strings compare case-INSENSITIVELY, which is GitHub's documented rule and
    not Python's. The mixed-type arm is where the whole OMN-18616 defect lives:
    on an event with no pull-request payload the head-repository field is null,
    which casts to 0, while a repository slug casts to NaN -- so the equality is
    false, the INEQUALITY holds, and the public hosted arm is selected on every
    push, dispatch and schedule.
    """
    if isinstance(left, _Ambiguous) or isinstance(right, _Ambiguous):
        ambiguous = left if isinstance(left, _Ambiguous) else right
        assert isinstance(ambiguous, _Ambiguous)
        return ambiguous.matches
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    if left is MISSING and right is MISSING:
        return True
    if isinstance(left, bool) and isinstance(right, bool):
        return left is right
    if isinstance(left, list) or isinstance(right, list):
        # GitHub compares arrays and objects by reference, so two distinct
        # literals are never equal. Nothing in this estate routes on one, and
        # guessing would be a silent answer to a question nobody asked.
        return False
    return _as_number(left) == _as_number(right)


def _value(fragment: str, context: EventContext, slug: str, where: str) -> object:
    """Resolve one operand against an event context, or refuse to guess."""
    fragment = _strip_parens(fragment)
    lowered = fragment.lower()

    if len(fragment) >= 2 and fragment.startswith("'") and fragment.endswith("'"):
        return fragment[1:-1]
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return MISSING
    if fragment.isdigit():
        return int(fragment)

    args = _call_args(fragment, "fromjson")
    if args is not None:
        if len(args) != 1:
            raise _unreadable(fragment, where)
        inner = _value(args[0], context, slug, where)
        if not isinstance(inner, str):
            raise _unreadable(fragment, where)
        try:
            return json.loads(inner)
        except json.JSONDecodeError as error:
            raise _unreadable(fragment, where) from error

    args = _call_args(fragment, "contains")
    if args is not None:
        if len(args) != 2:
            raise _unreadable(fragment, where)
        haystack = _value(args[0], context, slug, where)
        needle = _value(args[1], context, slug, where)
        if isinstance(haystack, list):
            return any(_equal(entry, needle) for entry in haystack)
        if isinstance(haystack, str) and isinstance(needle, str):
            return needle in haystack
        raise _unreadable(fragment, where)

    if lowered == "github.event_name":
        return context.event_name
    if lowered == "github.repository":
        return slug
    if lowered == "github.repository_owner":
        return slug.split("/", 1)[0]
    if lowered == "github.event.pull_request.head.repo.full_name":
        return context.head_field("full_name", slug)
    if lowered == "github.event.pull_request.head.repo.fork":
        return context.head_field("fork", slug)
    if lowered in PULL_REQUEST_REF_FIELDS:
        # Empty on every event with no pull request -- GitHub sets these to the
        # empty string there, which is knowable and is not ambiguous at all.
        if context.head == "absent":
            return ""
        return _Ambiguous(context.unknown_ref_matches)
    if lowered in ALWAYS_UNKNOWN_REF_FIELDS:
        return _Ambiguous(context.unknown_ref_matches)

    raise _unreadable(fragment, where)


def _term(fragment: str, context: EventContext, slug: str, where: str) -> bool:
    """Evaluate one conjunct of a guard to a boolean.

    A conjunct may itself be a parenthesised boolean expression -- the estate
    writes `((A && B) || (C && D))`, where splitting the outer disjunction
    leaves `(A && B)` as a single "conjunct" whose own `&&` sits at depth 1.
    Stripping its parentheses exposes that operator, so the fragment is handed
    back to `_guard` rather than parsed as a comparison. Without this the whole
    clause reached the equality split, produced three operands, and was REFUSED
    -- which is fail-closed but wrong, and it hid a live omnistream finding
    behind a refusal.
    """
    fragment = _strip_parens(fragment)
    if (
        len(_split_top_level(fragment, "||")) > 1
        or len(_split_top_level(fragment, "&&")) > 1
    ):
        return _guard(fragment, context, slug, where)
    if fragment.startswith("!") and not fragment.startswith("!="):
        return not _term(fragment[1:], context, slug, where)

    for operator, negate in (("!=", True), ("==", False)):
        parts = _split_top_level(fragment, operator)
        if len(parts) == 2:
            same = _equal(
                _value(parts[0], context, slug, where),
                _value(parts[1], context, slug, where),
            )
            return not same if negate else same
        if len(parts) > 2:
            raise _unreadable(fragment, where)

    # Ordering comparisons are refused rather than approximated: nothing in
    # this estate routes on one, so a fragment carrying one is a shape that
    # arrived without this gate being taught it.
    for operator in ("<=", ">=", "<", ">"):
        if len(_split_top_level(fragment, operator)) > 1:
            raise _unreadable(fragment, where)

    return _truthy(_value(fragment, context, slug, where))


def _guard(guard: str, context: EventContext, slug: str, where: str) -> bool:
    """Does the guard reaching an arm hold under this event?

    An empty guard is the arm the expression falls through to, which every
    event reaches, so it is true by construction.
    """
    guard = _strip_parens(guard)
    if not guard:
        return True
    for clause in _split_top_level(guard, "||"):
        if all(
            _term(conjunct, context, slug, where)
            for conjunct in _split_top_level(clause, "&&")
        ):
            return True
    return False


QUOTED = re.compile(r"'([^']*)'")


def _variants(
    context: EventContext, branches: list[Branch], refs: RefNames
) -> tuple[EventContext, ...]:
    """The cell, split in two when a guard reads a ref this gate cannot know.

    Split only when it changes something. The overwhelming majority of guards
    in this estate read the event name and the head repository, both of which
    are fully determined by the cell, and doubling every one of those rows
    would bury the ref-sensitive cases in noise.
    """
    text = " ".join(branch.guard for branch in branches).lower()
    if not any(
        field in text for field in PULL_REQUEST_REF_FIELDS + ALWAYS_UNKNOWN_REF_FIELDS
    ):
        return (context,)
    # The matching variant is only worth evaluating if some branch could
    # actually produce the match. Every quoted literal in the guard is offered
    # as a candidate -- over-inclusive on purpose, since an extra candidate can
    # only ADD the pessimistic variant, never remove it.
    if not refs.could_match(
        set(QUOTED.findall(" ".join(branch.guard for branch in branches)))
    ):
        return (
            replace(
                context,
                key=f"{context.key} (no branch can match the ref test)",
                unknown_ref_matches=False,
            ),
        )
    return (
        replace(context, key=f"{context.key} (ref matches)", unknown_ref_matches=True),
        replace(
            context,
            key=f"{context.key} (ref does not match)",
            unknown_ref_matches=False,
        ),
    )


def _select(
    branches: list[Branch], context: EventContext, slug: str, where: str
) -> int | None:
    """The index of the arm this event selects, or None if it selects none.

    GitHub's `||` returns the first truthy operand, and each operand is
    `guard && labels` whose value is the guard when the guard is falsy and the
    labels otherwise. A `fromJSON` of a non-empty array is always truthy, so
    the first arm whose guard holds is the one that places the run.
    """
    for index, branch in enumerate(branches):
        if _guard(branch.guard, context, slug, where):
            return index
    return None


def _needs_evaluation(branches: list[Branch]) -> bool:
    """Can any event place this job badly, whatever the guards turn out to mean?

    No, when no arm carries a hosted label AND some arm is unguarded: every
    event then lands on some arm and none of them is hosted. Asking the
    evaluator in that case can only produce a refusal over a guard shape that
    cannot change the verdict, and a gate that refuses what it need not judge
    gets switched off. Asked in one place so the verdict, the latent report and
    the matrix report cannot disagree about when evaluation is owed.
    """
    return any(branch.hosted for branch in branches) or not any(
        not branch.guard for branch in branches
    )


@dataclass(frozen=True)
class Placement:
    """A hosted placement (or a placement onto nothing), and when it is taken.

    `branch` is None for the second case: every guard false and no unguarded
    fallback, so `runs-on` evaluates to a falsy value and the job cannot start.
    """

    branch: Branch | None
    events: tuple[str, ...]
    reason: str

    def describe(self) -> str:
        return self.branch.describe() if self.branch else self.reason

    @property
    def labels(self) -> str:
        return ",".join(self.branch.labels) if self.branch else "(nothing)"

    @property
    def how(self) -> str:
        return self.branch.how if self.branch else "every guard false"


def _gh(
    args: list[str], env_name: str = "GH_TOKEN"
) -> subprocess.CompletedProcess[str]:
    """Run `gh`, optionally under a different token than the job token.

    The job token can read its own repository and nothing above it. Reading
    Actions VARIABLES, at either scope, needs the Variables permission, which a
    workflow cannot grant itself. That read is therefore made under
    `GH_TOKEN_VARIABLES` when a caller supplies one and under the job token
    otherwise -- which is the case that 403s, and is handled by failing closed
    at the point a value is actually needed rather than at startup.
    """
    env = os.environ.copy()
    token = os.environ.get(env_name)
    if token:
        env["GH_TOKEN"] = token
    return subprocess.run(
        ["gh", *args], check=False, capture_output=True, text=True, timeout=30, env=env
    )


def resolve_visibility(slug: str) -> str:
    """Live repository visibility. Never a list, never an inference."""
    result = _gh(["api", f"repos/{slug}", "--jq", ".visibility"])
    if result.returncode != 0:
        raise GateError(
            f"could not resolve the visibility of {slug} from the GitHub API "
            f"({result.stderr.strip()[:200]}). The rule applies to private "
            "repositories only, so a gate that cannot read visibility has not "
            "passed -- it has not run. THE GATE DID NOT RUN."
        )
    visibility = result.stdout.strip()
    if visibility not in {"public", "private", "internal"}:
        raise GateError(
            f"{slug} reported an unrecognised visibility {visibility!r}; "
            "failing closed. THE GATE DID NOT RUN."
        )
    return visibility


class Variables:
    """Repository variables layered over organisation variables, read LAZILY.

    A repo-scoped shadow overrides the organisation value, which is the whole
    trap in rule 14: flipping the org value while a shadow still holds the old
    one drains nothing, and the org readback looks correct. So both scopes are
    consulted -- but NEITHER is readable with the Actions job token. Reading
    Actions variables needs the Variables permission, which a workflow cannot
    grant itself through the `permissions:` key, and both scopes return HTTP
    403 without a supplied credential. Measured on seven live runs, 2026-09-16.

    Demanding that credential up front made the gate unrunnable in every
    repository, including the majority whose jobs pin labels as literals and
    never consult a variable at all. So every read is deferred to the point a
    NAME is looked up, and a repository whose placement is decided entirely by
    literals needs no credential.

    When a name IS looked up and the scope holding the answer cannot be read,
    that is a REFUSAL naming the credential -- never a silent fall through to
    the expression own literal default. Those are different facts: "unset"
    means the default applies, "unreadable" means nobody knows whether it does,
    and the organisation seam currently holds a hosted value, so falling
    through would turn the exact violation this gate exists to catch into a
    pass.
    """

    def __init__(self, slug: str) -> None:
        self._slug = slug
        self._org_name = slug.split("/", 1)[0]
        self._scopes: dict[str, dict[str, str] | None] = {}
        self._errors: dict[str, str] = {}

    @classmethod
    def from_fixture(cls, values: dict[str, str]) -> Variables:
        """A fully-resolved map, for TESTS only. CI never takes this path."""
        instance = cls("fixture/fixture")
        instance._scopes = {"repo": dict(values), "org": {}}
        return instance

    @staticmethod
    def _read(flag: str, target: str) -> dict[str, str]:
        result = _gh(
            ["variable", "list", flag, target, "--json", "name,value"],
            env_name="GH_TOKEN_VARIABLES",
        )
        if result.returncode != 0:
            raise GateError(result.stderr.strip()[:200])
        return {
            item["name"]: item["value"] for item in json.loads(result.stdout or "[]")
        }

    def _scope(self, which: str) -> dict[str, str] | None:
        if which not in self._scopes and which not in self._errors:
            flag, target = (
                ("--repo", self._slug) if which == "repo" else ("--org", self._org_name)
            )
            try:
                self._scopes[which] = self._read(flag, target)
            except GateError as error:
                self._errors[which] = str(error)
        return self._scopes.get(which)

    def _refuse(self, name: str, which: str) -> GateError:
        where = "this repository" if which == "repo" else "the organisation"
        return GateError(
            f"{name} is needed to resolve a runs-on expression and {where} "
            f"variable scope could not be read ({self._errors[which]}). An "
            "Actions job token cannot read Actions variables at either scope; "
            "pass a credential that can as the ACTIONS_VARIABLES_TOKEN secret. "
            "Guessing the expression own default instead would report a "
            "repository inheriting a hosted organisation value as green. "
            "THE GATE DID NOT RUN."
        )

    def get(self, name: str) -> str | None:
        """The value this repository resolves `name` to, or None if unset."""
        repo = self._scope("repo")
        if repo is None:
            raise self._refuse(name, "repo")
        if name in repo:
            return repo[name]
        org = self._scope("org")
        if org is None:
            raise self._refuse(name, "org")
        return org.get(name)


class RefNames:
    """The repository's live branch names, read LAZILY and once.

    Needed only to decide whether a comparison against a ref field is
    SATISFIABLE. `github.base_ref == 'dev'` selects a hosted arm in omnistream
    on paper, and omnistream has exactly one branch -- `main` -- so no pull
    request in that repository can ever reach it. Reporting it would be a
    finding about a run that cannot happen, and a gate that reports those is a
    gate people learn to scroll past.

    A hardcoded branch list would go stale the first time somebody cuts one, so
    this is a live read on the same terms as the visibility read. When it
    CANNOT be read the answer is the pessimistic one -- assume the comparison
    can match -- because an unreadable branch list must not turn a hosted
    placement into a pass.
    """

    def __init__(self, slug: str) -> None:
        self._slug = slug
        self._names: frozenset[str] | None = None
        self._readable = True

    @classmethod
    def from_fixture(cls, names: list[str]) -> RefNames:
        """A fixed branch list, for TESTS only. CI never takes this path."""
        instance = cls("fixture/fixture")
        instance._names = frozenset(names)
        return instance

    def names(self) -> frozenset[str] | None:
        """Every branch name, or None when the list could not be read."""
        if self._names is None and self._readable:
            result = _gh(
                [
                    "api",
                    f"repos/{self._slug}/branches",
                    "--paginate",
                    "--jq",
                    ".[].name",
                ],
                env_name="GH_TOKEN_VARIABLES",
            )
            if result.returncode != 0:
                self._readable = False
            else:
                self._names = frozenset(
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                )
        return self._names

    def could_match(self, literals: set[str]) -> bool:
        """Could a ref field equal any of these literals in this repository?"""
        names = self.names()
        if names is None:
            return True  # unreadable: assume it can, never assume it cannot
        return any(
            literal in names or literal.removeprefix("refs/heads/") in names
            for literal in literals
        )


class CalledWorkflows:
    """The source of every reusable workflow a caller job delegates to.

    Fetched at the ref the CALLER pins, because that is the content the run
    executes. Results are cached per `uses:` string: one reusable is typically
    called from several workflows in the same repository, and a gate that
    re-fetched per call site would turn a ten-second scan into a rate limit.

    The read uses GH_TOKEN_VARIABLES when a caller supplies one -- the same
    credential the variable reads use, which has cross-repository read -- and
    falls back to the job token, which can read only the caller's own
    repository. A read that fails is a REFUSAL naming what could not be
    fetched: the alternative is to skip the job, which is the exact silence
    this change exists to remove.
    """

    def __init__(self, repo_root: Path, fixture: dict[str, str] | None = None) -> None:
        self._repo_root = repo_root
        self._fixture = fixture
        self._cache: dict[str, str] = {}
        self._commits: dict[str, str] = {}

    @staticmethod
    def _parse(uses: str) -> tuple[str, str, str]:
        """(slug, path, ref) for `uses`; slug empty for a same-repo call."""
        local = USES_LOCAL.match(uses.strip())
        if local:
            return "", local.group("path"), ""
        cross = USES_CROSS_REPO.match(uses.strip())
        if cross:
            return cross.group("slug"), cross.group("path"), cross.group("ref")
        raise GateError(
            f"a job delegates to {uses!r}, which is neither a same-repository "
            "workflow path (./.github/workflows/x.yml) nor a cross-repository "
            "one (owner/repo/.github/workflows/x.yml@ref). Placement cannot be "
            "read from a shape this gate does not recognise, and skipping it "
            "would report the caller green. THE GATE DID NOT RUN."
        )

    def commit(self, uses: str) -> str:
        """The commit a MUTABLE ref resolved to, or '' for an immutable pin.

        Printed beside the verdict so the reading can be re-derived. A failure
        to resolve it is not fatal -- the content was already fetched, and the
        verdict stands on the content, not on this label.
        """
        slug, _, ref = self._parse(uses)
        if not slug or SHA_REF.match(ref):
            return ""
        if uses not in self._commits:
            result = _gh(
                ["api", f"repos/{slug}/commits/{ref}", "--jq", ".sha"],
                env_name="GH_TOKEN_VARIABLES",
            )
            self._commits[uses] = (
                result.stdout.strip() if result.returncode == 0 else "unresolved"
            )
        return self._commits[uses]

    def source(self, uses: str) -> str:
        """The called workflow's YAML text, at the ref its caller pins."""
        if uses in self._cache:
            return self._cache[uses]
        if self._fixture is not None:
            if uses not in self._fixture:
                raise GateError(
                    f"the called-workflow fixture carries no entry for {uses!r}. "
                    "THE GATE DID NOT RUN."
                )
            self._cache[uses] = self._fixture[uses]
            return self._cache[uses]

        slug, path, ref = self._parse(uses)
        if not slug:
            local = self._repo_root / path
            if not local.is_file():
                raise GateError(
                    f"a job delegates to {uses!r} and {local} does not exist in "
                    "the checked-out tree, so its placement cannot be read. "
                    "THE GATE DID NOT RUN."
                )
            self._cache[uses] = local.read_text(encoding="utf-8")
            return self._cache[uses]

        # The ref goes in the QUERY STRING, never as `-f ref=...`: a single
        # `-f` makes `gh api` switch the request to POST and send the pair as
        # a body field, which the contents endpoint answers with a bare
        # `Not Found`. That 404 is indistinguishable from a real missing file,
        # so the mistake reads as a correct fail-closed refusal -- measured
        # against a SHA that demonstrably exists.
        result = _gh(
            [
                "api",
                f"repos/{slug}/contents/{path}?ref={quote(ref, safe='')}",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            env_name="GH_TOKEN_VARIABLES",
        )
        if result.returncode != 0:
            raise GateError(
                f"could not fetch the called workflow {uses!r} "
                f"({result.stderr.strip()[:200]}). A `uses:` job's placement is "
                "decided by the called workflow's runs-on resolved in THIS "
                "repository's variable scopes, so a gate that cannot read it "
                "has not judged the job -- and this repository's required "
                "checks may be the jobs in question. Supply a credential with "
                "cross-repository read as ACTIONS_VARIABLES_TOKEN. "
                "THE GATE DID NOT RUN."
            )
        self._cache[uses] = result.stdout
        return self._cache[uses]


def _called_jobs(uses: str, text: str) -> dict[str, Any]:
    """The `jobs:` mapping of a called workflow, or a refusal."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise GateError(
            f"the called workflow {uses!r} is not parseable YAML ({error}). "
            "THE GATE DID NOT RUN."
        ) from error
    jobs = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        raise GateError(
            f"the called workflow {uses!r} declares no jobs, so the caller's "
            "job resolves to no runner at all. That is a malformed delegation, "
            "not a job that is safely placed. THE GATE DID NOT RUN."
        )
    return jobs


def _labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(entry) for entry in value]
    if isinstance(value, dict):  # runs-on: {group: ..., labels: [...]}
        return [str(entry) for entry in value.get("labels") or []]
    return [str(value)]


def _split_top_level(expression: str, operator: str) -> list[str]:
    """Split on `operator` at parenthesis depth 0, outside single quotes.

    Depth matters because the inline default in `fromJSON(vars.X || '[...]')`
    is the SAME `||` token as the one separating the arms of the selector.
    Splitting textually merges the two and reports an arm that does not exist.
    """
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    index = 0
    while index < len(expression):
        char = expression[index]
        if char == "'":
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif (
                depth == 0
                and char == operator[0]
                and expression[index : index + len(operator)] == operator
            ):
                parts.append(expression[start:index])
                index += len(operator)
                start = index
                continue
        index += 1
    parts.append(expression[start:])
    return [part.strip() for part in parts if part.strip()]


def _labels_of(
    fragment: str, runs_on: str, variables: Variables
) -> tuple[list[str], str]:
    """Resolve one arm's value to labels, live, or refuse to guess."""
    names = VAR_REF.findall(fragment)
    if not names:
        raise GateError(
            "a runs-on expression that names no vars.* cannot be resolved "
            f"statically: {runs_on!r}. THE GATE DID NOT RUN."
        )
    labels: list[str] = []
    how: list[str] = []
    for name in dict.fromkeys(names):
        value = variables.get(name)
        if value is None:
            match = re.search(FALLBACK_FOR.format(name=name), fragment)
            if match is None:
                raise GateError(
                    f"{name} is unset at every scope and carries no literal "
                    f"fallback in {runs_on!r}; placement is undecidable. "
                    "THE GATE DID NOT RUN."
                )
            value = match.group(1)
            how.append(f"{name} unset -> {value}")
        else:
            how.append(f"{name}={value}")
        try:
            labels.extend(str(entry) for entry in json.loads(value))
        except json.JSONDecodeError as error:
            raise GateError(
                f"{name} is not valid JSON ({value!r}): {error}. THE GATE DID NOT RUN."
            ) from error
    return labels, "; ".join(how)


def resolve_branches(runs_on: Any, variables: Variables) -> list[Branch]:
    """Return every arm this `runs-on` can resolve to, with its guard.

    An expression is not "unknown": it resolves, live, to whatever the
    repository's own variable scopes currently hold. It is resolved ARM BY ARM
    rather than flattened, because `A && X || Y` places a run on X or on Y and
    never on both, and the two arms answer to different rules -- see the fork
    paragraph in the module docstring.
    """
    if not isinstance(runs_on, str) or "${{" not in str(runs_on):
        return [Branch(guard="", labels=_labels(runs_on), how="literal")]

    inner = runs_on.strip()
    if inner.startswith("${{") and inner.endswith("}}"):
        inner = inner[3:-2]

    branches: list[Branch] = []
    for segment in _split_top_level(inner, "||"):
        operands = _split_top_level(segment, "&&")
        guard = " && ".join(operands[:-1]) if len(operands) > 1 else ""
        labels, how = _labels_of(operands[-1], runs_on, variables)
        branches.append(Branch(guard=guard, labels=labels, how=how))
    return branches


def _job_source(text: str, job_id: str) -> str:
    """The raw source of one job mapping, for annotation lookup.

    Taken from the file text rather than the parsed document because a comment
    is not part of the parse, and the annotation is deliberately a comment: it
    must be visible beside the pin it excuses.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^  {re.escape(job_id)}\s*:\s*$", line):
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^  \S", lines[index]):
            end = index
            break
    # include the line immediately above, so an annotation may sit on top of
    # the job rather than only inside it
    return "\n".join(lines[max(0, start - 1) : end])


def _offending_placements(
    branches: list[Branch],
    contexts: tuple[EventContext, ...],
    slug: str,
    where: str,
    refs: RefNames,
) -> list[Placement]:
    """Every way this `runs-on` breaches the rule, and the events that reach it.

    Two breaches, not one. A hosted arm selected under any event except a fork
    pull request is the rule this gate is named for. An event that selects NO
    arm is the other: `runs-on` evaluates to a falsy value and GitHub schedules
    the job onto nothing, which is a fork guard with nothing to fall back to
    seen from the event side.

    The short circuit in front of both is not an optimisation, it is a scoping
    decision. When no arm carries a hosted label AND some arm is unguarded,
    every event lands on some arm and none of them is hosted, whatever the
    guards say -- so the guards need not be evaluated, and a repository whose
    expressions are all fleet is never refused over a guard shape this gate has
    not been taught. Evaluation is demanded exactly where the answer depends on
    it.
    """
    if not _needs_evaluation(branches):
        return []

    hosted_by_arm: dict[int, list[str]] = {}
    unplaced: list[str] = []
    for declared in contexts:
        for context in _variants(declared, branches, refs):
            index = _select(branches, context, slug, where)
            if index is None:
                unplaced.append(context.key)
            elif branches[index].hosted and not context.fork_exempt:
                hosted_by_arm.setdefault(index, []).append(context.key)

    placements = [
        Placement(
            branch=branches[index],
            events=tuple(keys),
            reason="resolves to a GitHub-hosted label",
        )
        for index, keys in sorted(hosted_by_arm.items())
    ]
    if unplaced:
        placements.append(
            Placement(
                branch=None,
                events=tuple(unplaced),
                reason=(
                    "selects no arm at all -- every guard is false and the "
                    "expression carries no unguarded fallback, so runs-on "
                    "evaluates to a falsy value and the job cannot start"
                ),
            )
        )
    return placements


def _latent(
    branches: list[Branch],
    declared: tuple[EventContext, ...],
    slug: str,
    where: str,
    refs: RefNames,
) -> list[str]:
    """Matrix cells this workflow does NOT declare that would resolve hosted.

    Reported, never enforced. A job cannot run under a trigger its workflow
    does not carry, and the pull request that adds the trigger is judged by
    this gate at that moment. Printing the cell is what stops that from being
    a surprise -- `infra-consistency-check.yml` carried exactly this warning in
    a comment for months before the trigger arrived.
    """
    declared_keys = {context.key for context in declared}
    latent: list[str] = []
    if not _needs_evaluation(branches):
        return latent
    for cell in EVENT_MATRIX:
        if cell.key in declared_keys or cell.fork_exempt:
            continue
        for context in _variants(cell, branches, refs):
            index = _select(branches, context, slug, where)
            if index is not None and branches[index].hosted:
                latent.append(context.key)
    return latent


def _matrix_report(
    branches: list[Branch],
    contexts: tuple[EventContext, ...],
    slug: str,
    where: str,
    refs: RefNames,
) -> list[str]:
    """One line per event cell: the arm it selects and whether it is declared.

    This is the falsifier surface. A claim that a repository places nothing on
    a hosted runner is re-derivable from these lines cell by cell, rather than
    resting on the verdict -- which is the difference between a reading
    somebody can check and one they have to trust.
    """
    if not _needs_evaluation(branches):
        return [
            f"matrix: {where} places nothing hosted under any event -- no arm "
            "carries a hosted label and an unguarded arm exists, so the guards "
            "cannot change the answer and are not evaluated"
        ]
    declared_keys = {context.key for context in contexts}
    matrix_keys = {cell.key for cell in EVENT_MATRIX}
    cells = EVENT_MATRIX + tuple(
        context for context in contexts if context.key not in matrix_keys
    )
    lines: list[str] = []
    for cell in cells:
        scope = "declared" if cell.key in declared_keys else "not declared"
        for context in _variants(cell, branches, refs):
            index = _select(branches, context, slug, where)
            chosen = (
                ",".join(branches[index].labels)
                if index is not None
                else "(no arm selected)"
            )
            lines.append(f"matrix: {where} {context.key} -> {chosen} [{scope}]")
    return lines


def declared_contexts(document: dict[str, Any], where: str) -> tuple[EventContext, ...]:
    """The event contexts a workflow's `on:` block admits.

    `on` is read from BOTH the string key and the boolean one: PyYAML resolves
    with YAML 1.1, where the bare token `on` is the boolean true, so a workflow
    whose trigger block is written `on:` parses to a `True` key. Reading only
    the string key would find no triggers in any real workflow file and judge
    every one of them over an empty matrix -- a silent pass.
    """
    # `True` is a legitimate key here and not a typing mistake: PyYAML
    # resolves with YAML 1.1, where the bare token `on` is the boolean true.
    triggers: dict[Any, Any] = document
    raw: Any = triggers.get("on", triggers.get(True))
    if isinstance(raw, str):
        names = [raw]
    elif isinstance(raw, list):
        names = [str(entry) for entry in raw]
    elif isinstance(raw, dict):
        names = [str(key) for key in raw]
    else:
        raise GateError(
            f"{where}: the workflow's `on:` block is {raw!r}, which is not a "
            "trigger name, a list of them or a mapping of them. Which events "
            "reach a job is what decides where it runs, so a trigger block "
            "that cannot be read is not a job that is safely placed. "
            "THE GATE DID NOT RUN."
        )
    if not names:
        raise GateError(
            f"{where}: the workflow declares no trigger events at all, so no "
            "placement can be judged and none can be proven safe. "
            "THE GATE DID NOT RUN."
        )

    # A reusable workflow runs under whatever event its CALLER fired, which is
    # not knowable from here, so it is judged over the whole matrix.
    if "workflow_call" in names:
        return EVENT_MATRIX

    contexts: list[EventContext] = []
    for name in names:
        matched = [context for context in EVENT_MATRIX if context.event_name == name]
        if matched:
            contexts.extend(matched)
            continue
        # An event outside the fixed matrix is modelled with no pull-request
        # payload, which is the one property every non-pull-request event
        # shares and the only one any routing guard in this estate reads.
        contexts.append(
            EventContext(
                key=name,
                event_name=name,
                head="absent",
                fork_exempt=False,
                why="an event outside the fixed matrix, carrying no "
                "pull-request payload",
            )
        )
    return tuple(contexts)


def _placements(
    uses: str,
    variables: Variables,
    called: CalledWorkflows,
    notes: list[str],
    contexts: tuple[EventContext, ...],
    slug: str,
    refs: RefNames,
    depth: int = 1,
    parent_slug: str = "",
) -> list[tuple[str, Placement, str]]:
    """Every (runs-on, offending arm, where) a `uses:` job can be placed on.

    Recursive, because a reusable workflow may itself delegate. Each called
    job's `runs-on` is resolved against the CALLER's variables -- `variables`
    is threaded unchanged all the way down -- because that is the scope GitHub
    evaluates it in and the account the run is billed to. The event CONTEXTS
    are threaded the same way and for the same reason: a called workflow runs
    under the event that fired the CALLER, never under its own `on:` block,
    which declares only `workflow_call`.
    """
    if depth > MAX_NESTING:
        raise GateError(
            f"the delegation chain reaching {uses!r} is more than {MAX_NESTING} "
            "levels deep, which GitHub will not execute. A tree that claims to "
            "is malformed, not merely large. THE GATE DID NOT RUN."
        )
    called_slug, _, ref = CalledWorkflows._parse(uses)
    if not called_slug and parent_slug:
        raise GateError(
            f"the called workflow in {parent_slug} delegates to {uses!r}, a path "
            "relative to ITS OWN repository, which is not in this checkout. "
            "Reading it from the caller's tree would judge a different file of "
            "the same name. THE GATE DID NOT RUN."
        )

    commit = called.commit(uses)
    pin = f" (ref {ref} -> {commit})" if commit else ""
    jobs = _called_jobs(uses, called.source(uses))

    offenders: list[tuple[str, Placement, str]] = []
    for job_id, definition in jobs.items():
        if not isinstance(definition, dict):
            continue
        where = f"{uses}::{job_id}{pin}"
        nested = definition.get("uses")
        if "runs-on" in definition:
            branches = resolve_branches(definition["runs-on"], variables)
            notes.append(
                f"note:     {uses}::{job_id} resolves to "
                + " | ".join(
                    f"[{','.join(branch.labels)}] ({branch.describe()})"
                    for branch in branches
                )
                + pin
            )
            for placement in _offending_placements(
                branches, contexts, slug, where, refs
            ):
                offenders.append((str(definition["runs-on"]).strip(), placement, where))
        elif isinstance(nested, str):
            offenders.extend(
                _placements(
                    nested,
                    variables,
                    called,
                    notes,
                    contexts,
                    slug,
                    refs,
                    depth + 1,
                    called_slug or "",
                )
            )
        else:
            raise GateError(
                f"{uses}::{job_id} declares neither `runs-on` nor `uses`, so "
                "where it runs cannot be read. THE GATE DID NOT RUN."
            )
    return offenders


def _job_offenders(
    definition: dict[str, Any],
    variables: Variables,
    called: CalledWorkflows,
    notes: list[str],
    contexts: tuple[EventContext, ...],
    slug: str,
    where: str,
    refs: RefNames,
) -> list[tuple[str, Placement, str]]:
    """The placements one CALLER job can take, whether it pins or delegates."""
    if "runs-on" in definition:
        branches = resolve_branches(definition["runs-on"], variables)
        runs_on = str(definition["runs-on"]).strip()
        return [
            (runs_on, placement, "")
            for placement in _offending_placements(
                branches, contexts, slug, where, refs
            )
        ]

    uses = definition.get("uses")
    if isinstance(uses, str):
        return _placements(uses, variables, called, notes, contexts, slug, refs)

    # Neither key. GitHub would not schedule this job at all, so there is
    # nothing to place and nothing to refuse.
    return []


def scan(
    repo_root: Path,
    slug: str,
    variables: Variables,
    called: CalledWorkflows | None = None,
    notes: list[str] | None = None,
    latent: list[str] | None = None,
    matrix: list[str] | None = None,
    refs: RefNames | None = None,
) -> list[Finding]:
    called = CalledWorkflows(repo_root) if called is None else called
    refs = RefNames(slug) if refs is None else refs
    notes = [] if notes is None else notes
    latent = [] if latent is None else latent
    matrix = [] if matrix is None else matrix
    workflows = repo_root / ".github" / "workflows"
    if not workflows.is_dir():
        raise GateError(
            f"{workflows} does not exist. A repository with no workflow "
            "directory cannot be proven to place nothing on hosted runners "
            "from here. THE GATE DID NOT RUN."
        )
    paths = sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml"))
    if not paths:
        raise GateError(
            f"{workflows} contains no workflow files; nothing to judge and "
            "nothing to prove. THE GATE DID NOT RUN."
        )

    findings: list[Finding] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            continue
        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            continue
        contexts = declared_contexts(document, path.name)
        notes.append(
            f"note: {path.name} declares "
            + ", ".join(context.key for context in contexts)
        )
        for job_id, definition in jobs.items():
            if not isinstance(definition, dict):
                continue
            where = f"{path.name}::{job_id}"
            if isinstance(definition.get("uses"), str):
                notes.append(
                    f"note: {path.name}::{job_id} delegates to {definition['uses']}"
                )
            if "runs-on" in definition:
                branches = resolve_branches(definition["runs-on"], variables)
                matrix.extend(_matrix_report(branches, contexts, slug, where, refs))
                for cell in _latent(branches, contexts, slug, where, refs):
                    latent.append(
                        f"LATENT: {where} would resolve to a hosted label under "
                        f"`{cell}`, which this workflow does not declare today. "
                        "Not a failure -- the pull request that adds that "
                        "trigger is judged here at that moment."
                    )
            offenders = _job_offenders(
                definition, variables, called, notes, contexts, slug, where, refs
            )
            if not offenders:
                continue
            # The annotation lives beside the CALLER's job, because that is the
            # mapping in this repository. A `uses:` job's excuse belongs here
            # too: the called workflow is shared, and an exemption written
            # there would excuse every other caller of it as well.
            source = _job_source(text, str(job_id))
            if ANNOTATION.search(source):
                continue
            if ANNOTATION_MARKER.search(source):
                raise GateError(
                    f"{path.name}::{job_id} carries a private-repo-hosted-ok "
                    "marker whose reason and (OMN-nnnnn) ticket are not on the "
                    "SAME line, so it excuses nothing. Put the whole annotation "
                    "on one comment line; continuation lines beneath it are "
                    "fine. THE GATE DID NOT RUN."
                )
            for runs_on, placement, via in offenders:
                findings.append(
                    Finding(
                        workflow=path.name,
                        job=str(job_id),
                        runs_on=runs_on,
                        resolved=placement.labels,
                        why=placement.how,
                        branch=placement.describe(),
                        via=via,
                        events=", ".join(placement.events),
                    )
                )
    return findings


# THE TRIGGERS WHOSE `branches:` FILTER NAMES A BRANCH THAT RUNS WORKFLOWS.
# A push reads the pushed branch's own tree; a pull request reads its BASE
# branch's tree merged with the head. `merge_group` is left out: its ref is a
# temporary queue branch, never a branch somebody keeps.
BRANCH_FILTER_TRIGGERS = ("push", "pull_request", "pull_request_target")

# Branches that run workflows whatever the filters say, when they exist: the
# default branch, and the two long-lived branches of the release model.
ALWAYS_JUDGED = ("main", "dev")


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        timeout=120,
    )


def _filter_regex(pattern: str) -> re.Pattern[str]:
    """GitHub's branch-filter glob as a regular expression.

    `**` matches any characters including `/`; `*` matches any characters but
    `/`; `?` and `+` quantify the preceding character; `[...]` is a class.
    Everything else is literal.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char in "?+":
            out.append(char)
        elif char == "[":
            end = pattern.find("]", index)
            if end == -1:
                out.append(re.escape(char))
            else:
                out.append(pattern[index : end + 1])
                index = end
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + r"\Z")


def _is_match_all(pattern: str) -> bool:
    """A pattern that admits every branch (or every branch without a `/`)."""
    return pattern.strip() in {"*", "**"}


def _named_by_filters(document: dict[str, Any], branch: str) -> bool:
    """Does an explicit, non-match-all `branches:` filter admit `branch`?

    A filter is read in order, and the LAST pattern that matches decides, so a
    `!` pattern after a positive one excludes. A trigger with no filter, a
    `branches-ignore:` filter, or a match-all pattern admits every branch --
    that reaches feature branches, which are judged by their own pull request,
    so it names nothing here.
    """
    # `True` is the YAML 1.1 reading of the bare token `on`, as in
    # `declared_contexts`.
    triggers: dict[Any, Any] = document
    raw: Any = triggers.get("on", triggers.get(True))
    if not isinstance(raw, dict):
        return False
    for trigger in BRANCH_FILTER_TRIGGERS:
        config = raw.get(trigger)
        if not isinstance(config, dict):
            continue
        patterns = config.get("branches")
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            continue
        admitted = False
        explicit = False
        for pattern in (str(entry) for entry in patterns):
            negated = pattern.startswith("!")
            body = pattern[1:] if negated else pattern
            if _filter_regex(body).match(branch):
                admitted = not negated
                explicit = not negated and not _is_match_all(body)
        if admitted and explicit:
            return True
    return False


def _remote_branches(repo_root: Path) -> list[str]:
    result = _run_git(
        repo_root,
        "for-each-ref",
        "--format=%(refname:strip=3)",
        "refs/remotes/origin/",
    )
    names = [
        line.strip()
        for line in result.stdout.decode("utf-8", "replace").splitlines()
        if line.strip() and line.strip() != "HEAD"
    ]
    if result.returncode != 0 or not names:
        raise GateError(
            f"no branch of the repository is fetched into {repo_root} "
            f"(refs/remotes/origin/* is empty: "
            f"{result.stderr.decode('utf-8', 'replace').strip()[:200]}). Every "
            "branch that runs workflows must be judged, and a checkout that "
            "holds one tree can judge only that one. Fetch every head first "
            "(git fetch origin '+refs/heads/*:refs/remotes/origin/*'). "
            "THE GATE DID NOT RUN."
        )
    return sorted(names)


def _default_branch(repo_root: Path) -> str:
    result = _run_git(repo_root, "ls-remote", "--symref", "origin", "HEAD")
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        match = re.match(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", line.strip())
        if match:
            return match.group(1)
    raise GateError(
        "could not read the repository's default branch from its origin "
        f"({result.stderr.decode('utf-8', 'replace').strip()[:200]}). The "
        "default branch always runs workflows, so a gate that cannot name it "
        "cannot claim to have judged it. THE GATE DID NOT RUN."
    )


def _workflow_texts(repo_root: Path, branch: str) -> dict[str, str] | None:
    """{file name: YAML text} of a branch's `.github/workflows`, or None."""
    ref = f"refs/remotes/origin/{branch}"
    result = _run_git(
        repo_root, "archive", "--format=tar", ref, "--", ".github/workflows"
    )
    if result.returncode != 0:
        listing = _run_git(repo_root, "ls-tree", "--name-only", ref, ".github/")
        if listing.returncode == 0 and b"workflows" not in listing.stdout:
            return None
        raise GateError(
            f"could not read .github/workflows at {ref} "
            f"({result.stderr.decode('utf-8', 'replace').strip()[:200]}). A "
            "branch whose workflows cannot be read has not been judged. "
            "THE GATE DID NOT RUN."
        )
    texts: dict[str, str] = {}
    with tarfile.open(fileobj=BytesIO(result.stdout)) as archive:
        for member in archive.getmembers():
            name = member.name
            if not member.isfile() or "/" in name.removeprefix(".github/workflows/"):
                continue
            if not name.endswith((".yml", ".yaml")):
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                texts[name.removeprefix(".github/workflows/")] = handle.read().decode(
                    "utf-8"
                )
    return texts


def workflow_branches(repo_root: Path, event_branch: str) -> list[str]:
    """Every branch that runs workflows, except the one checked out.

    A branch runs workflows when it is the default branch, `main` or `dev`, or
    when an explicit `branches:` filter on the default, `main` or `dev` tree
    names it (`hotfix/**` names every `hotfix/` branch). The event's own branch
    is left out because the checkout supersedes its old tip: a pull request
    that repairs a branch must be able to pass while the tip is still broken.
    """
    remote = _remote_branches(repo_root)
    default = _default_branch(repo_root)
    anchors = [
        name for name in dict.fromkeys([default, *ALWAYS_JUDGED]) if name in remote
    ]
    documents: list[dict[str, Any]] = []
    for anchor in anchors:
        for name, text in (_workflow_texts(repo_root, anchor) or {}).items():
            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError as error:
                raise GateError(
                    f"{anchor}:{name} is not parseable YAML ({error}), so the "
                    "branches its filters name cannot be read. "
                    "THE GATE DID NOT RUN."
                ) from error
            if isinstance(document, dict):
                documents.append(document)
    named = [
        branch
        for branch in remote
        if branch in anchors
        or any(_named_by_filters(document, branch) for document in documents)
    ]
    return [branch for branch in named if branch != event_branch]


def scan_every_workflow_branch(
    repo_root: Path,
    slug: str,
    variables: Variables,
    event_branch: str,
    called_fixture: dict[str, str] | None,
    notes: list[str],
    latent: list[str],
    matrix: list[str],
    refs: RefNames,
    judged: list[str],
) -> list[Finding]:
    """Judge the workflow tree of every OTHER branch that runs workflows.

    Each tree is judged exactly as the checkout is -- same variable scopes,
    same event matrix, same reusable resolution -- and each finding names its
    branch as `<branch>:<workflow>`.
    """
    findings: list[Finding] = []
    for branch in workflow_branches(repo_root, event_branch):
        texts = _workflow_texts(repo_root, branch)
        sha = (
            _run_git(repo_root, "rev-parse", f"refs/remotes/origin/{branch}")
            .stdout.decode("utf-8", "replace")
            .strip()[:12]
        )
        if not texts:
            judged.append(f"branch {branch} ({sha}): no workflows, nothing runs")
            continue
        with tempfile.TemporaryDirectory(prefix="placement-branch-") as scratch:
            root = Path(scratch)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            for name, text in texts.items():
                (workflows / name).write_text(text, encoding="utf-8")
            branch_findings = scan(
                root,
                slug,
                variables,
                CalledWorkflows(root, fixture=called_fixture),
                notes,
                latent,
                matrix,
                refs,
            )
        judged.append(
            f"branch {branch} ({sha}): {len(texts)} workflow(s), "
            f"{len(branch_findings)} hosted placement(s)"
        )
        findings.extend(
            replace(finding, workflow=f"{branch}:{finding.workflow}")
            for finding in branch_findings
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name of the repository under test; defaults to $GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--assume-visibility",
        choices=["public", "private", "internal"],
        help=(
            "skip the live visibility read. For TESTS and for a local run with "
            "no GitHub credential only; CI never passes this."
        ),
    )
    parser.add_argument(
        "--variables-json",
        help=(
            "path to a JSON object of variable name -> value, used INSTEAD of "
            "the live scopes. For tests only; CI never passes it, because a "
            "fixture cannot go stale in the way the live value can."
        ),
    )
    parser.add_argument(
        "--called-workflows-json",
        help=(
            "path to a JSON object of `uses:` string -> workflow YAML text, "
            "used INSTEAD of fetching called workflows. For tests only; CI "
            "never passes it, because a fixture cannot go stale in the way "
            "the live content can."
        ),
    )
    parser.add_argument(
        "--branches-json",
        help=(
            "a JSON array of branch names, used INSTEAD of the live branch "
            "list. For tests and local runs only; CI never passes it."
        ),
    )
    parser.add_argument(
        "--every-workflow-branch",
        action="store_true",
        help=(
            "also judge the workflow tree of every OTHER branch that runs "
            "workflows (the default branch, main, dev, and every branch an "
            "explicit trigger filter names), read from refs/remotes/origin/*. "
            "A branch the caller file never reached is otherwise never judged "
            "(OMN-18431). The reusable workflow always passes it."
        ),
    )
    parser.add_argument(
        "--event-branch",
        default="",
        help=(
            "the branch whose tree is checked out (the pull request's base, or "
            "the pushed branch). Its remote tip is superseded by the checkout "
            "and is not judged a second time."
        ),
    )
    parser.add_argument(
        "--report-event-matrix",
        action="store_true",
        help=(
            "print, for every job that declares a `runs-on`, the arm each cell "
            "of the fixed event matrix selects and whether the workflow "
            "declares that trigger. This is the falsifier surface: a claim "
            "that a repository places nothing hosted is re-derivable from it "
            "line by line, rather than resting on the verdict."
        ),
    )
    parser.add_argument(
        "--report-reusable-calls",
        action="store_true",
        help=(
            "also print each `uses:` job, the workflow it delegates to, and "
            "what every called job's runs-on resolved to in THIS repository's "
            "variable scopes"
        ),
    )
    args = parser.parse_args(argv)

    # The two fixture flags substitute a FILE for a live read -- the variable
    # scopes, and the called workflows. That is exactly what their help text
    # says, and until now "CI never passes it" was a claim in a docstring. A
    # claim in a docstring is not a control: anyone who added one to a workflow
    # would get a gate that reports on a file somebody wrote instead of on the
    # live estate, and it would pass. So the boundary is enforced where it can
    # be checked. Inside Actions the flags are REFUSED, which is the same
    # fail-closed posture every other unresolvable input in this file takes.
    # Outside Actions they work unchanged, which is what the tests and a local
    # credential-free run need.
    fixtures = [
        name
        for name, value in (
            ("--variables-json", args.variables_json),
            ("--called-workflows-json", args.called_workflows_json),
            ("--assume-visibility", args.assume_visibility),
            ("--branches-json", args.branches_json),
        )
        if value
    ]
    if fixtures and os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            f"::error::{', '.join(fixtures)} replaces a live read with a file "
            "and is for tests and local runs only. Inside GitHub Actions the "
            "gate must resolve visibility, variables and called workflows "
            "live, or it is reporting on whatever the file says rather than on "
            "this repository. THE GATE DID NOT RUN.",
            file=sys.stderr,
        )
        return 2

    if not args.repo:
        print(
            "::error::--repo (or $GITHUB_REPOSITORY) is required: visibility is "
            "resolved live per repository, never guessed. THE GATE DID NOT RUN.",
            file=sys.stderr,
        )
        return 2

    try:
        visibility = args.assume_visibility or resolve_visibility(args.repo)
        if visibility == "public":
            print(
                f"OK: {args.repo} is public; GitHub-hosted runners are the "
                "correct placement there and this gate does not apply."
            )
            return 0
        variables = (
            Variables.from_fixture(
                json.loads(Path(args.variables_json).read_text(encoding="utf-8"))
            )
            if args.variables_json
            else Variables(args.repo)
        )
        called = CalledWorkflows(
            Path(args.repo_root),
            fixture=(
                json.loads(Path(args.called_workflows_json).read_text(encoding="utf-8"))
                if args.called_workflows_json
                else None
            ),
        )
        notes: list[str] = []
        latent: list[str] = []
        matrix: list[str] = []
        refs = (
            RefNames.from_fixture(json.loads(args.branches_json))
            if args.branches_json
            else RefNames(args.repo)
        )
        findings = scan(
            Path(args.repo_root),
            args.repo,
            variables,
            called,
            notes,
            latent,
            matrix,
            refs,
        )
        judged: list[str] = []
        if args.every_workflow_branch:
            findings.extend(
                scan_every_workflow_branch(
                    Path(args.repo_root),
                    args.repo,
                    variables,
                    args.event_branch,
                    (
                        json.loads(
                            Path(args.called_workflows_json).read_text(encoding="utf-8")
                        )
                        if args.called_workflows_json
                        else None
                    ),
                    notes,
                    latent,
                    matrix,
                    refs,
                    judged,
                )
            )
    except GateError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    if args.report_reusable_calls:
        for note in notes:
            print(note)

    if args.report_event_matrix:
        for line in matrix:
            print(line)

    # Which branches were judged besides the checkout, on every run: a
    # verdict over "every branch" is only re-derivable if it names them.
    for line in judged:
        print(f"judged: {line}")

    # Printed on EVERY run, pass or fail. A latent cell is the state the
    # OMN-18616 defect sat in for months before a trigger was added -- visible
    # only in one workflow's own comment, seen by nobody.
    for line in latent:
        print(line)

    if not findings:
        print(
            f"OK: every job in {args.repo} ({visibility}) resolves to a "
            "non-hosted runner under every trigger event it declares."
        )
        return 0

    print(
        f"::error::{args.repo} is {visibility}, and private repositories do not "
        f"run CI on GitHub-hosted runners (operator ruling 2026-09-14). "
        f"{len(findings)} job placement(s) breach that under a trigger event "
        "the workflow declares:",
        file=sys.stderr,
    )
    for finding in findings:
        via = f"\n    via:      {finding.via}" if finding.via else ""
        print(
            f"  {finding.workflow}::{finding.job}{via}\n"
            f"    runs-on:  {finding.runs_on}\n"
            f"    arm:      {finding.branch}\n"
            f"    events:   {finding.events}\n"
            f"    resolves: {finding.resolved}   [{finding.why}]",
            file=sys.stderr,
        )
    print(
        "\nPlacement is read per TRIGGER EVENT: the `events:` line names the "
        "events that actually reach the offending arm. A selector guarded on "
        "the head repository alone reaches its public arm under EVERY event "
        "carrying no pull-request payload, because that field is null there -- "
        "test the event first:\n"
        '  contains(fromJSON(\'["pull_request","pull_request_review"]\'), '
        "github.event_name) &&\n"
        "  github.event.pull_request.head.repo.full_name != github.repository\n"
        "\nOtherwise move the job to the fleet, or -- if the fleet genuinely "
        "cannot carry it -- record WHY beside the job:\n"
        "  # private-repo-hosted-ok: <reason> (OMN-nnnnn)\n"
        "A pin with no reason is the failure this gate exists to refuse.\n"
        "A finding carrying a `via:` line is a job that DELEGATES: the label is "
        "chosen by the called workflow but resolved in THIS repository's "
        "variable scopes, so the fix is usually this repository's routing "
        "variable, not an edit to the shared workflow.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
