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


def _gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], check=False, capture_output=True, text=True, timeout=30
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


def live_variables(slug: str) -> dict[str, str]:
    """Repository variables layered over organisation variables.

    A repo-scoped shadow overrides the organisation value, which is the whole
    trap in rule 14: flipping the org value while a shadow still holds the old
    one drains nothing, and the org readback looks correct.
    """
    org = slug.split("/", 1)[0]
    merged: dict[str, str] = {}
    for scope in (["--org", org], ["--repo", slug]):
        result = _gh(["variable", "list", *scope, "--json", "name,value"])
        if result.returncode != 0:
            raise GateError(
                f"could not list variables for scope {scope[1]} "
                f"({result.stderr.strip()[:200]}). Placement cannot be "
                "resolved. THE GATE DID NOT RUN."
            )
        for item in json.loads(result.stdout or "[]"):
            merged[item["name"]] = item["value"]
    return merged


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


def resolve_runs_on(runs_on: Any, variables: dict[str, str]) -> tuple[list[str], str]:
    """Return the labels this `runs-on` resolves to, and how it was resolved.

    An expression names one or more variables. Every branch a `pull_request`
    event can take is resolved and the UNION is returned: a selector that sends
    some events to a hosted class is a hosted placement for those events, and
    reporting only the common case is how a gate reports green on the half of
    the matrix nobody looked at.
    """
    if not isinstance(runs_on, str) or "${{" not in str(runs_on):
        return _labels(runs_on), "literal"

    names = VAR_REF.findall(runs_on)
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
            match = re.search(FALLBACK_FOR.format(name=name), runs_on)
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


def scan(repo_root: Path, slug: str, variables: dict[str, str]) -> list[Finding]:
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
            labels, how = resolve_runs_on(definition["runs-on"], variables)
            hosted = [label for label in labels if HOSTED_LABEL.match(label)]
            if not hosted:
                continue
            if ANNOTATION.search(_job_source(text, str(job_id))):
                continue
            findings.append(
                Finding(
                    workflow=path.name,
                    job=str(job_id),
                    runs_on=str(definition["runs-on"]).strip(),
                    resolved=",".join(labels),
                    why=how,
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
            json.loads(Path(args.variables_json).read_text(encoding="utf-8"))
            if args.variables_json
            else live_variables(args.repo)
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
