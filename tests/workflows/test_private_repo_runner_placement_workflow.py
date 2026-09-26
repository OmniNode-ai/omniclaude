# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shape of the private-repo runner placement reusable workflow (OMN-18205).

Two properties are asserted mechanically because both were learned the
expensive way elsewhere in this estate.

The gate job is PINNED to the fleet. A job that judges private repositories
cannot itself be placed on a hosted runner: it would have to break the
invariant it enforces in order to run. Routing it through a seam would be
worse still, because it would then share fate with the variable it reads.

The workflow accepts no force, skip or override input. An enforcement surface
whose argument parser offers a way past it is advisory, and the way that is
discovered is always during the incident it was meant to prevent.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "private-repo-runner-placement-reusable.yml"
)

BYPASS_WORDS = ("force", "skip", "override", "bypass", "allow_hosted", "dry_run")


def _document() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_gate_job_is_pinned_to_the_fleet() -> None:
    job = _document()["jobs"]["private-repo-runner-placement"]
    assert job["runs-on"] == ["self-hosted", "omnibase-ci"], (
        "the job that enforces 'private repos never run hosted' must not run "
        "hosted, and must not resolve through a routing variable either: it "
        "would share fate with the value it reads"
    )


def test_it_is_a_reusable_workflow_with_no_bypass_input() -> None:
    document = _document()
    triggers = document.get(True) or document.get("on")
    assert "workflow_call" in triggers, "callers consume this by `uses:`"
    inputs = (triggers["workflow_call"] or {}).get("inputs") or {}
    offending = [
        name for name in inputs if any(word in name.lower() for word in BYPASS_WORDS)
    ]
    assert not offending, (
        f"the placement gate offers bypass-shaped input(s) {offending}; an "
        "enforcement surface with a way past it is advisory"
    )


def test_the_validator_is_checked_out_at_this_workflows_own_sha() -> None:
    """One pin, not two: the caller's `uses:` SHA governs workflow AND script."""
    steps = _document()["jobs"]["private-repo-runner-placement"]["steps"]
    checkouts = [
        step
        for step in steps
        if isinstance(step.get("uses"), str)
        and step["uses"].startswith("actions/checkout")
    ]
    refs = [step.get("with", {}).get("ref") for step in checkouts]
    assert "${{ github.job_workflow_sha }}" in refs, (
        "pinning the validator to github.sha or to @main each broke a "
        "cross-repo gate in production, both times silently"
    )


def test_the_hook_and_the_workflow_run_the_same_validator() -> None:
    """A local verdict and a CI verdict must not be able to disagree."""
    hooks = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".pre-commit-hooks.yaml").read_text(
            encoding="utf-8"
        )
    )
    hook = next(h for h in hooks if h["id"] == "private-repo-runner-placement")
    assert "scripts/private_repo_runner_placement_gate.py" in hook["entry"]
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/private_repo_runner_placement_gate.py" in body


def test_the_hook_inspects_the_whole_tree_not_the_diff() -> None:
    """OMN-17993: a diff-scoped hook reports green over everything already landed."""
    hooks = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".pre-commit-hooks.yaml").read_text(
            encoding="utf-8"
        )
    )
    hook = next(h for h in hooks if h["id"] == "private-repo-runner-placement")
    assert hook.get("always_run") is True
    assert hook.get("pass_filenames") is False


def test_the_gate_judges_every_branch_that_runs_workflows() -> None:
    """OMN-18431: a branch the caller file never reached was never judged.

    The reusable must fetch every head and pass the enumeration flag with the
    event's own branch, unconditionally. An input that could turn it off would
    be a bypass by another name, so it is asserted to be a fixed argument.
    """
    body = WORKFLOW.read_text(encoding="utf-8")
    steps = _document()["jobs"]["private-repo-runner-placement"]["steps"]
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert "+refs/heads/*:refs/remotes/origin/*" in runs, (
        "the gate reads other branches from refs/remotes/origin/*; without "
        "fetching every head it refuses, and a checkout alone holds one tree"
    )
    assert "--every-workflow-branch" in runs
    assert "--event-branch" in runs
    assert "github.base_ref || github.ref_name" in body, (
        "the event's own branch is the pull request's BASE (whose tree the "
        "merge checkout supersedes) or, on a push, the pushed branch"
    )
    inputs = (
        (_document().get(True) or _document().get("on"))["workflow_call"] or {}
    ).get("inputs") or {}
    assert not any("branch" in name.lower() for name in inputs), (
        "branch enumeration is not optional"
    )
