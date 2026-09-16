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
    ORGANISATION variables needs a credential with organisation scope, so that
    read is made under `GH_TOKEN_ORG` when a caller supplies one and under the
    job token otherwise -- which is the case that 403s, and is handled by
    failing closed at the point a value is actually needed rather than at
    startup.
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
    consulted -- but the organisation scope is read with a credential the job
    token does not have, and demanding it up front made this gate unrunnable in
    every repository whose jobs never name a variable at all.

    The resolution is therefore deferred to the point a NAME is looked up. A
    name present at repository scope is answered without ever touching the
    organisation. A name absent there, in a repository where the organisation
    read failed, is a REFUSAL naming the token -- never a silent fall through
    to the expression own literal default, which is how a repository carrying
    no shadow at all would come back green while inheriting a hosted
    organisation value.
    """

    def __init__(self, slug: str) -> None:
        self._org_name = slug.split("/", 1)[0]
        self._repo = self._read(["--repo", slug], slug)
        self._org: dict[str, str] | None = None
        self._org_error: str | None = None

    @staticmethod
    def _read(scope: list[str], label: str) -> dict[str, str]:
        result = _gh(
            ["variable", "list", *scope, "--json", "name,value"],
            env_name="GH_TOKEN_ORG" if scope[0] == "--org" else "GH_TOKEN",
        )
        if result.returncode != 0:
            raise GateError(
                f"could not list variables for scope {label} "
                f"({result.stderr.strip()[:200]}). Placement cannot be "
                "resolved. THE GATE DID NOT RUN."
            )
        return {
            item["name"]: item["value"] for item in json.loads(result.stdout or "[]")
        }

    def _org_scope(self) -> dict[str, str] | None:
        if self._org is None and self._org_error is None:
            try:
                self._org = self._read(["--org", self._org_name], self._org_name)
            except GateError as error:
                self._org_error = str(error)
        return self._org

    @classmethod
    def from_fixture(cls, values: dict[str, str]) -> Variables:
        """A fully-resolved map, for TESTS only. CI never takes this path."""
        instance = cls.__new__(cls)
        instance._org_name = ""
        instance._repo = dict(values)
        instance._org = {}
        instance._org_error = None
        return instance

    def get(self, name: str) -> str | None:
        """The value this repository resolves `name` to, or None if unset.

        Raises rather than answering None when the organisation scope could not
        be read, because "unset here" and "unreadable above here" are different
        facts and only one of them means the expression own default applies.
        """
        if name in self._repo:
            return self._repo[name]
        org = self._org_scope()
        if org is None:
            raise GateError(
                f"{name} is not set on this repository and the organisation "
                f"scope could not be read, so whether it is set above this "
                f"repository is unknown -- and an organisation value overrides "
                f"the expression own default. Pass an organisation-readable "
                f"credential as the ORG_VARIABLES_TOKEN secret. Underlying "
                f"read: {self._org_error} THE GATE DID NOT RUN."
            )
        return org.get(name)


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


def scan(repo_root: Path, slug: str, variables: Variables) -> list[Finding]:
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
            if "runs-on" not in definition:
                # a `uses:` job takes its placement from the CALLED workflow,
                # which is judged in ITS OWN repository by this same gate. It
                # is not silently exempt: see --report-reusable-calls.
                continue
            branches = resolve_branches(definition["runs-on"], variables)
            offender = _offending_branch(branches)
            if offender is None:
                continue
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
            findings.append(
                Finding(
                    workflow=path.name,
                    job=str(job_id),
                    runs_on=str(definition["runs-on"]).strip(),
                    resolved=",".join(offender.labels),
                    why=offender.how,
                    branch=offender.describe(),
                )
            )
    return findings


def reusable_calls(repo_root: Path) -> list[tuple[str, str, str]]:
    """`uses:` jobs, reported so a cross-repo hop is visible rather than absent."""
    out: list[tuple[str, str, str]] = []
    workflows = repo_root / ".github" / "workflows"
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for job_id, definition in (document.get("jobs") or {}).items():
            if isinstance(definition, dict) and isinstance(definition.get("uses"), str):
                out.append((path.name, str(job_id), definition["uses"]))
    return out


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
        "--report-reusable-calls",
        action="store_true",
        help="also list `uses:` jobs, whose placement is decided elsewhere",
    )
    args = parser.parse_args(argv)

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
        findings = scan(Path(args.repo_root), args.repo, variables)
    except GateError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    if args.report_reusable_calls:
        for workflow, job, uses in reusable_calls(Path(args.repo_root)):
            print(f"note: {workflow}::{job} delegates placement to {uses}")

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
        print(
            f"  {finding.workflow}::{finding.job}\n"
            f"    runs-on:  {finding.runs_on}\n"
            f"    arm:      {finding.branch}\n"
            f"    resolves: {finding.resolved}   [{finding.why}]",
            file=sys.stderr,
        )
    print(
        "\nMove the job to the fleet, or -- if the fleet genuinely cannot carry "
        "it -- record WHY beside the job:\n"
        "  # private-repo-hosted-ok: <reason> (OMN-nnnnn)\n"
        "A pin with no reason is the failure this gate exists to refuse.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
