# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18205: in a cross-repo reusable, the untrusted test is the FORK test.

A reusable workflow's `runs-on` selector decides, for every repository that
consumes it, whether the job lands on the trusted lab fleet or on the
untrusted public class. The only property that makes a pull request untrusted
is that its head lives in a DIFFERENT repository: a same-repo pull request is
written by somebody who can already push to the repository the workflow
protects.

Five of these selectors also routed every same-repo pull request whose base
was `dev` to the public class. That is not a trust boundary; it is a blanket
pin of every consuming repository's required checks to GitHub-hosted runners,
which is exactly what the 2026-09-14 operator ruling forbids for private
repositories and what the enterprise hosted-runner switch then made
unrunnable. The sibling pr-title reusable never had the extra clause, which is
why `pr-title / check-title` was the one required context that moved when a
private repository's trusted shadow was set.

These assertions run over the LIVE workflow files, so reintroducing the clause
is a red test rather than a review catch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# Conditions that are NOT a trust boundary and must never gate the public class.
NON_TRUST_CLAUSES = (
    "github.base_ref ==",
    "github.base_ref !=",
    "github.ref ==",
    "github.event_name != 'pull_request'",
)

FORK_TEST = "github.event.pull_request.head.repo.full_name != github.repository"


def _selectors() -> list[tuple[str, str, str]]:
    """(workflow, job, runs-on) for every REUSABLE job routing through the public var.

    Scoped to `workflow_call` deliberately. A workflow that only ever runs in
    THIS repository decides placement for this repository alone, and omniclaude
    is public, where a hosted runner is the correct and free placement. The
    invariant is about a selector one repository writes and fourteen others
    inherit without being able to see it.
    """
    found: list[tuple[str, str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        triggers = document.get(True) or document.get("on")
        if not isinstance(triggers, dict) or "workflow_call" not in triggers:
            continue
        for job_id, definition in (document.get("jobs") or {}).items():
            if not isinstance(definition, dict):
                continue
            runs_on = definition.get("runs-on")
            if isinstance(runs_on, str) and "OMNI_PUBLIC_PR_RUNS_ON_JSON" in runs_on:
                found.append((path.name, str(job_id), runs_on))
    return found


def test_there_are_selectors_to_judge() -> None:
    """Positive control: a zero here makes every assertion below vacuous."""
    assert _selectors(), (
        "no job routes through OMNI_PUBLIC_PR_RUNS_ON_JSON; either the "
        "selectors were removed or this parser stopped matching, and the "
        "assertion below is then asserting nothing"
    )


@pytest.mark.parametrize(
    ("workflow", "job", "runs_on"),
    _selectors(),
    ids=[f"{w}::{j}" for w, j, _ in _selectors()],
)
def test_only_the_fork_test_gates_the_untrusted_runner_class(
    workflow: str, job: str, runs_on: str
) -> None:
    collapsed = re.sub(r"\s+", " ", runs_on)
    assert FORK_TEST.replace(" ", "") in collapsed.replace(" ", ""), (
        f"{workflow}::{job} gates the public runner class without the fork "
        "test; the fork test is the only thing that makes a pull request "
        "untrusted"
    )
    offending = [clause for clause in NON_TRUST_CLAUSES if clause in collapsed]
    assert not offending, (
        f"{workflow}::{job} sends pull requests to the untrusted public runner "
        f"class on {offending}, which is not a trust boundary. Every repository "
        "consuming this reusable then has that required check pinned to "
        "GitHub-hosted runners regardless of its own routing shadow, which the "
        "2026-09-14 ruling forbids for private repositories."
    )
