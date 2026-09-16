#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Refuse a `runs-on` label set that no ONLINE runner in the organisation carries.

A job pinned to a label nobody has does not fail. It QUEUES, silently, for as
long as the label stays unclaimed, and every surface that would normally say so
reports something else: the pull request is green because the job never ran,
the workflow shows "queued", and the runner listing is not consulted by anything
that gates a merge.

Measured, 2026-09-16 (OMN-18408): a pull request repinned five scheduled lab
probes to `[self-hosted, omnibase-verify, host-201]` and merged before the
runner carrying `host-201` was registered. Zero of 64 organisation runners
carried that label. The five probes queued for about four hours -- one chain
canary run sat unstarted for 2h40m -- and nothing anywhere said the label was
unclaimed. The merge was green, the deploy that would have created the runner
had not happened yet, and the only way to find out was to read the runner
listing by hand.

This gate is the missing surface. It is deliberately SEPARATE from the
private-repo placement gate, which answers a different question ("is this job
on a hosted runner it should not be on?"): this one applies to public
repositories too, needs a credential that gate does not, and must not have its
verdict entangled with that one's.

WHAT IT CHECKS. For every job in every workflow, each arm a `runs-on`
expression can resolve to (arms are resolved, not flattened, for the reason the
placement gate's docstring gives: `A && X || Y` places a run on X or on Y and
never on both). A GitHub-hosted arm is skipped -- hosted labels have no
organisation runner entry, by construction. A self-hosted arm must be matched
by at least one runner that is ONLINE and carries EVERY label in the arm, which
is the rule GitHub itself uses to assign a job.

OFFLINE IS NOT ABSENT, and the failure text says which. A label carried only by
offline runners is a fleet outage; a label carried by nobody at all is a pin
that can never be satisfied. Both queue a job forever, so both fail here, but
they want different repairs and the message names the difference rather than
leaving the reader to check.

FAIL-CLOSED, ALWAYS. An unreadable runner listing, an empty one, or one with no
online runner at all is exit 2 and "THE GATE DID NOT RUN" -- never a pass. An
empty result is not evidence of absence, and a gate whose input failed to load
has not judged anything. Every run also executes a POSITIVE CONTROL built from
the live listing itself: an online runner's own label set must match itself. A
control assembled from a hardcoded label would go stale the first time the
fleet is relabelled; this one cannot.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from private_repo_runner_placement_gate import (  # noqa: E402
    Branch,
    GateError,
    Variables,
    resolve_branches,
)

# `self-hosted` is implicit on every self-hosted runner and GitHub reports it in
# the labels array, so it needs no special handling in the subset test. It is
# named here only so a reader does not go looking for where it is stripped.
IMPLICIT_SELF_HOSTED = "self-hosted"

# GitHub credential shapes, for scrubbing subprocess output before it is quoted
# into an error message that lands in a CI log. `gh` is not expected to echo its
# token, but "not expected to" is not a control: this module prints the CLI's
# stderr verbatim when a read fails, and a CI log is durable and widely
# readable. Cheap insurance, and the same posture as this repository's
# PostToolUse output guard.
CREDENTIAL_SHAPES = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"
)
REDACTED = "<redacted>"


def redact(text: str) -> str:
    """Mask credential-shaped substrings, and the live token value if set.

    Both halves matter. The pattern catches a token this process never held;
    the literal match catches one whose shape GitHub changes tomorrow.
    """
    scrubbed = CREDENTIAL_SHAPES.sub(REDACTED, text)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN_VARIABLES"):
        value = os.environ.get(name, "")
        # A short value is not a credential and would mask half the message.
        if len(value) >= 8:
            scrubbed = scrubbed.replace(value, REDACTED)
    return scrubbed


@dataclass(frozen=True)
class Runner:
    name: str
    status: str
    labels: frozenset[str]

    @property
    def online(self) -> bool:
        return self.status == "online"

    def carries(self, wanted: frozenset[str]) -> bool:
        return wanted <= self.labels


@dataclass(frozen=True)
class Unclaimed:
    workflow: str
    job: str
    runs_on: str
    arm: str
    labels: tuple[str, ...]
    offline_carriers: tuple[str, ...]

    def verdict(self) -> str:
        if self.offline_carriers:
            return (
                "carried ONLY by offline runner(s): "
                + ", ".join(self.offline_carriers)
                + " -- this is a fleet outage, not a bad pin"
            )
        return "carried by NO runner in the organisation, online or offline"


def _labels_lower(values: Any) -> frozenset[str]:
    return frozenset(str(value).lower() for value in values)


def runner_listing_command(org: str) -> list[str]:
    """The argv used to read the organisation's runner listing.

    Split out so the no-credential-on-argv property is testable rather than
    asserted in a comment. The credential reaches `gh` ONLY through the
    inherited environment: every element of this list is a literal or the
    organisation slug, and a test pins that against a sentinel token.

    Why it matters: an argument list is world-readable through `ps` for the
    life of the process, on a host shared with every other job on the runner.
    An environment variable is readable only by the process and its children.
    """
    return [
        "gh",
        "api",
        "--paginate",
        f"/orgs/{org}/actions/runners?per_page=100",
    ]


def load_runners(org: str) -> list[Runner]:
    """Every runner registered to the organisation, live.

    Deliberately not wrapped in a try/except that returns an empty list: a
    listing that failed to load and a fleet with no runners are the same value
    and must not be the same verdict.
    """
    command = runner_listing_command(org)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:  # pragma: no cover - environment guard
        raise GateError(
            f"`gh` is not on PATH ({error}); the runner listing cannot be read. "
            "THE GATE DID NOT RUN."
        ) from error

    # stderr is NEVER discarded: a gate that suppresses its own error output
    # returns zero rows and reads exactly like a clean bill of health.
    if completed.returncode != 0:
        raise GateError(
            f"reading {org}'s runner listing failed (exit {completed.returncode}): "
            f"{redact(completed.stderr.strip())}. THE GATE DID NOT RUN."
        )

    runners: list[Runner] = []
    # --paginate concatenates one JSON object per page.
    decoder = json.JSONDecoder()
    text = completed.stdout.strip()
    index = 0
    while index < len(text):
        try:
            page, offset = decoder.raw_decode(text, index)
        except json.JSONDecodeError as error:
            raise GateError(
                f"{org}'s runner listing is not valid JSON: {error}. "
                "THE GATE DID NOT RUN."
            ) from error
        for entry in page.get("runners", []):
            runners.append(
                Runner(
                    name=str(entry.get("name", "")),
                    status=str(entry.get("status", "")),
                    labels=_labels_lower(
                        label.get("name", "") for label in entry.get("labels", [])
                    ),
                )
            )
        index = offset
        while index < len(text) and text[index] in " \t\r\n":
            index += 1

    if not runners:
        raise GateError(
            f"{org}'s runner listing came back empty. An organisation with no "
            "registered runners cannot be distinguished here from a listing "
            "that failed to load, and neither is a pass. THE GATE DID NOT RUN."
        )
    if not any(runner.online for runner in runners):
        raise GateError(
            f"none of {org}'s {len(runners)} registered runners is online. "
            "Every self-hosted pin would fail, which is a fleet outage rather "
            "than a set of bad pins. THE GATE DID NOT RUN."
        )
    return runners


def positive_control(runners: list[Runner]) -> None:
    """An online runner's own label set must match itself.

    Without this, a broken subset test, a case-folding mistake or a parse that
    silently produced empty label sets would report every pin as satisfied and
    the gate would pass everything forever.
    """
    probe = max(
        (runner for runner in runners if runner.online),
        key=lambda runner: len(runner.labels),
    )
    if not probe.labels:
        raise GateError(
            f"the online runner chosen as the positive control ({probe.name}) "
            "carries no labels at all, so the control cannot prove the matcher "
            "works. THE GATE DID NOT RUN."
        )
    if not any(runner.online and runner.carries(probe.labels) for runner in runners):
        raise GateError(
            "POSITIVE CONTROL FAILED: the label set of online runner "
            f"{probe.name} matches no online runner, including itself. The "
            "matcher is broken, so every 'satisfied' verdict this run would "
            "produce is meaningless. THE GATE DID NOT RUN."
        )


def _arm_is_hosted(branch: Branch) -> bool:
    return bool(branch.hosted)


def scan(
    repo_root: Path, runners: list[Runner], variables: Variables
) -> tuple[list[Unclaimed], list[str], int]:
    """Return (unclaimed arms, undecidable arms, decidable arm count).

    An arm whose labels are computed at run time -- a routing job's output, say
    -- cannot be answered from source, because the value does not exist until
    the run that produces it. Those are REPORTED, not refused: this gate's
    question is whether a label a pin names exists, and a pin that names no
    label yet has not made that claim. Refusing them would make the gate
    unusable in exactly the repository that needs it most.

    The count of decidable arms is returned so the caller can refuse a run in
    which NOTHING was decidable -- a gate that judged nothing has not passed.
    """
    workflows = repo_root / ".github" / "workflows"
    if not workflows.is_dir():
        raise GateError(
            f"{workflows} does not exist, so no pin in this repository can be "
            "judged. THE GATE DID NOT RUN."
        )
    paths = sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml"))
    if not paths:
        raise GateError(
            f"{workflows} contains no workflow files. THE GATE DID NOT RUN."
        )

    unclaimed: list[Unclaimed] = []
    undecidable: list[str] = []
    decidable = 0
    for path in paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, definition in jobs.items():
            if not isinstance(definition, dict) or "runs-on" not in definition:
                # a `uses:` job is placed by the workflow it calls, and that
                # workflow is judged by this gate in its own repository.
                continue
            try:
                branches = resolve_branches(definition["runs-on"], variables)
            except GateError as error:
                undecidable.append(f"{path.name}::{job_id} -- {error}")
                continue
            for branch in branches:
                if _arm_is_hosted(branch):
                    # GitHub-hosted labels have no organisation runner entry;
                    # whether they are ALLOWED is the placement gate's question.
                    continue
                wanted = _labels_lower(branch.labels)
                if not wanted:
                    continue
                decidable += 1
                if any(runner.online and runner.carries(wanted) for runner in runners):
                    continue
                offline = tuple(
                    sorted(
                        runner.name
                        for runner in runners
                        if not runner.online and runner.carries(wanted)
                    )
                )
                unclaimed.append(
                    Unclaimed(
                        workflow=path.name,
                        job=str(job_id),
                        runs_on=str(definition["runs-on"]).strip(),
                        arm=branch.describe(),
                        labels=tuple(branch.labels),
                        offline_carriers=offline,
                    )
                )
    return unclaimed, undecidable, decidable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name of the repository under test; defaults to $GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="organisation whose runner listing is authoritative; defaults to "
        "the owner of --repo",
    )
    parser.add_argument(
        "--runners-json",
        default=None,
        help="a fixture standing in for the live runner listing, for tests only",
    )
    parser.add_argument(
        "--variables-json",
        default=None,
        help="a fixture standing in for live Actions variables, for tests only",
    )
    args = parser.parse_args(argv)

    if not args.repo:
        print(
            "::error::--repo (or $GITHUB_REPOSITORY) is required. THE GATE DID "
            "NOT RUN.",
            file=sys.stderr,
        )
        return 2
    org = args.org or args.repo.split("/")[0]

    try:
        if args.runners_json:
            payload = json.loads(Path(args.runners_json).read_text(encoding="utf-8"))
            runners = [
                Runner(
                    name=str(entry.get("name", "")),
                    status=str(entry.get("status", "")),
                    labels=_labels_lower(
                        label.get("name", "") for label in entry.get("labels", [])
                    ),
                )
                for entry in payload.get("runners", [])
            ]
            if not runners:
                raise GateError(
                    "the runner fixture is empty; that is not a pass. "
                    "THE GATE DID NOT RUN."
                )
            if not any(runner.online for runner in runners):
                raise GateError(
                    "the runner fixture carries no online runner. THE GATE DID NOT RUN."
                )
        else:
            runners = load_runners(org)
        positive_control(runners)
        variables = (
            Variables.from_fixture(
                json.loads(Path(args.variables_json).read_text(encoding="utf-8"))
            )
            if args.variables_json
            else Variables(args.repo)
        )
        unclaimed, undecidable, decidable = scan(
            Path(args.repo_root), runners, variables
        )
        if decidable == 0:
            raise GateError(
                "not one self-hosted `runs-on` arm in this repository could be "
                "resolved from source, so this run judged nothing. A gate that "
                "judged nothing has not passed. THE GATE DID NOT RUN."
            )
    except GateError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    online = sum(1 for runner in runners if runner.online)
    # Printed on every run, pass or fail. An arm this gate could not judge is
    # not the same as one it judged and approved, and the difference has to be
    # visible without reading the source.
    for note in undecidable:
        print(f"note: label set computed at run time, not judged here: {note}")

    if not unclaimed:
        print(
            f"OK: {decidable} self-hosted `runs-on` arm(s) in {args.repo} are "
            f"each carried by at least one of {org}'s {online} online "
            f"runner(s); {len(undecidable)} arm(s) resolve at run time."
        )
        return 0

    print(
        f"::error::{len(unclaimed)} job arm(s) in {args.repo} pin a label set "
        f"that no ONLINE runner in {org} carries. A job pinned to a label "
        "nobody has does not fail -- it queues silently, and the pull request "
        "that merged it stays green:",
        file=sys.stderr,
    )
    for finding in unclaimed:
        print(
            f"  {finding.workflow}::{finding.job}\n"
            f"    runs-on: {finding.runs_on}\n"
            f"    arm:     {finding.arm}\n"
            f"    labels:  {', '.join(finding.labels)}\n"
            f"    status:  {finding.verdict()}",
            file=sys.stderr,
        )
    print(
        "\nRegister the runner BEFORE the pin merges, or pin to a label that "
        "exists today and re-pin in the change that proves the new runner "
        "online. A label pin only ever names a label that exists.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
