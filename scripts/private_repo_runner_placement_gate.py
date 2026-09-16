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

The exemption is scoped three ways so it cannot become a hole. It applies only
to the branch a fork actually takes; the branch an ordinary same-repo pull
request takes is judged exactly as before. It requires a non-fork branch to
exist that resolves to no hosted label, because a fork guard with nothing to
fall back to is a hosted pin wearing a guard. And it recognises only two
spellings of "is a fork", so any other guard -- an event name, a label, a
schedule -- is judged as an ordinary hosted placement rather than inheriting
the exemption by accident.

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
from dataclasses import dataclass
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

# "This pull request came from a fork", in the two spellings this estate uses:
# the head repository differing from the base, and the `fork` flag read as true
# or read bare for its truthiness. Deliberately an ENUMERATION rather than a
# loose search for the word fork, because this pattern decides whether a hosted
# arm is EXCUSED: an unrecognised guard must fall through to the ordinary
# judgement rather than inherit the exemption. The inverted forms -- `==`
# against the repository name, or `fork == false` -- guard the TRUSTED arm, not
# the fork arm, and are excluded by construction; the OMN-16683 inversion
# defect is exactly that shape.
FORK_TEST = re.compile(
    r"head\.repo\.full_name\s*!=\s*github\.repository"
    r"|head\.repo\.fork\s*==\s*true"
    r"|head\.repo\.fork\b(?!\s*[=!]=)",
    re.IGNORECASE,
)

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
    # Empty for a job that declares its own `runs-on`. For a `uses:` job it
    # names the called workflow and the job inside it whose placement this
    # finding is about, so the report says WHERE to make the change -- which is
    # not the file the finding is reported against.
    via: str = ""


@dataclass(frozen=True)
class Branch:
    """One arm of a `runs-on` selector, with the guard that reaches it.

    `guard` is empty for the arm an expression falls through to. `fork_guarded`
    says the guard is one of the two recognised fork tests, which is the only
    condition under which a hosted `labels` set is permitted here.
    """

    guard: str
    labels: list[str]
    how: str
    fork_guarded: bool

    @property
    def hosted(self) -> list[str]:
        return [label for label in self.labels if HOSTED_LABEL.match(label)]

    def describe(self) -> str:
        return f"guarded by `{self.guard.strip()}`" if self.guard else "default arm"


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
        return [
            Branch(guard="", labels=_labels(runs_on), how="literal", fork_guarded=False)
        ]

    inner = runs_on.strip()
    if inner.startswith("${{") and inner.endswith("}}"):
        inner = inner[3:-2]

    branches: list[Branch] = []
    for segment in _split_top_level(inner, "||"):
        operands = _split_top_level(segment, "&&")
        guard = " && ".join(operands[:-1]) if len(operands) > 1 else ""
        labels, how = _labels_of(operands[-1], runs_on, variables)
        branches.append(
            Branch(
                guard=guard,
                labels=labels,
                how=how,
                fork_guarded=bool(FORK_TEST.search(guard)),
            )
        )
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


def _offending_branch(branches: list[Branch]) -> Branch | None:
    """The arm that places this job on a hosted runner in breach of the rule.

    An arm a FORK reaches is exempt, but only while an ordinary arm exists that
    resolves to no hosted label: a fork guard with nothing to fall through to
    sends every event hosted, which is the placement the rule forbids, so it is
    reported against its own guard rather than excused by it.
    """
    for branch in branches:
        if branch.hosted and not branch.fork_guarded:
            return branch
    hosted_fork = [branch for branch in branches if branch.hosted]
    if hosted_fork and not any(
        not branch.fork_guarded and not branch.hosted for branch in branches
    ):
        return hosted_fork[0]
    return None


def _placements(
    uses: str,
    variables: Variables,
    called: CalledWorkflows,
    notes: list[str],
    depth: int = 1,
    parent_slug: str = "",
) -> list[tuple[str, Branch, str]]:
    """Every (runs-on, offending arm, where) a `uses:` job can be placed on.

    Recursive, because a reusable workflow may itself delegate. Each called
    job's `runs-on` is resolved against the CALLER's variables -- `variables`
    is threaded unchanged all the way down -- because that is the scope GitHub
    evaluates it in and the account the run is billed to.
    """
    if depth > MAX_NESTING:
        raise GateError(
            f"the delegation chain reaching {uses!r} is more than {MAX_NESTING} "
            "levels deep, which GitHub will not execute. A tree that claims to "
            "is malformed, not merely large. THE GATE DID NOT RUN."
        )
    slug, _, ref = CalledWorkflows._parse(uses)
    if not slug and parent_slug:
        raise GateError(
            f"the called workflow in {parent_slug} delegates to {uses!r}, a path "
            "relative to ITS OWN repository, which is not in this checkout. "
            "Reading it from the caller's tree would judge a different file of "
            "the same name. THE GATE DID NOT RUN."
        )

    commit = called.commit(uses)
    pin = f" (ref {ref} -> {commit})" if commit else ""
    jobs = _called_jobs(uses, called.source(uses))

    offenders: list[tuple[str, Branch, str]] = []
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
            offender = _offending_branch(branches)
            if offender is not None:
                offenders.append((str(definition["runs-on"]).strip(), offender, where))
        elif isinstance(nested, str):
            offenders.extend(
                _placements(nested, variables, called, notes, depth + 1, slug or "")
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
) -> list[tuple[str, Branch, str]]:
    """The placements one CALLER job can take, whether it pins or delegates."""
    if "runs-on" in definition:
        branches = resolve_branches(definition["runs-on"], variables)
        offender = _offending_branch(branches)
        if offender is None:
            return []
        return [(str(definition["runs-on"]).strip(), offender, "")]

    uses = definition.get("uses")
    if isinstance(uses, str):
        return _placements(uses, variables, called, notes)

    # Neither key. GitHub would not schedule this job at all, so there is
    # nothing to place and nothing to refuse.
    return []


def scan(
    repo_root: Path,
    slug: str,
    variables: Variables,
    called: CalledWorkflows | None = None,
    notes: list[str] | None = None,
) -> list[Finding]:
    called = CalledWorkflows(repo_root) if called is None else called
    notes = [] if notes is None else notes
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
        for job_id, definition in jobs.items():
            if not isinstance(definition, dict):
                continue
            if isinstance(definition.get("uses"), str):
                notes.append(
                    f"note: {path.name}::{job_id} delegates to {definition['uses']}"
                )
            offenders = _job_offenders(definition, variables, called, notes)
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
            for runs_on, offender, via in offenders:
                findings.append(
                    Finding(
                        workflow=path.name,
                        job=str(job_id),
                        runs_on=runs_on,
                        resolved=",".join(offender.labels),
                        why=offender.how,
                        branch=offender.describe(),
                        via=via,
                    )
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
        findings = scan(Path(args.repo_root), args.repo, variables, called, notes)
    except GateError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    if args.report_reusable_calls:
        for note in notes:
            print(note)

    if not findings:
        print(
            f"OK: every job in {args.repo} ({visibility}) resolves to a "
            "non-hosted runner."
        )
        return 0

    print(
        f"::error::{args.repo} is {visibility}, and private repositories do not "
        f"run CI on GitHub-hosted runners (operator ruling 2026-09-14). "
        f"{len(findings)} job(s) resolve to a hosted label:",
        file=sys.stderr,
    )
    for finding in findings:
        via = f"\n    via:      {finding.via}" if finding.via else ""
        print(
            f"  {finding.workflow}::{finding.job}{via}\n"
            f"    runs-on:  {finding.runs_on}\n"
            f"    arm:      {finding.branch}\n"
            f"    resolves: {finding.resolved}   [{finding.why}]",
            file=sys.stderr,
        )
    print(
        "\nMove the job to the fleet, or -- if the fleet genuinely cannot carry "
        "it -- record WHY beside the job:\n"
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
