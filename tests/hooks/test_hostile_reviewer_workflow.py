# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Structural tests for the Hostile Reviewer CI workflow — OMN-8603.

Asserts that ``.github/workflows/hostile-reviewer.yml`` is wired correctly:

- Triggers on the expected ``pull_request`` event types.
- Runs on the ``omnibase-ci`` self-hosted runner that exposes the local
  DeepSeek-R1 endpoint.
- Invokes ``omniintelligence.review_pairing.cli_review`` with at least one
  ``--model`` flag (no model is hardcoded by this test — only that the entry
  point and the model arg are present).
- Defines a ``hostile-review-gate`` job that depends on ``hostile-review``
  and exits non-zero when the review job reports ``failure``.
- Posts a PR summary comment via ``actions/github-script``.
- Does NOT require ``ANTHROPIC_API_KEY`` in any step's env block (regression
  guard for OMN-7467).

Wires the OMN-8524 implementation behind a permanent test so future edits to
the workflow cannot silently regress the gate semantics.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    """Parse the hostile-reviewer workflow YAML once per test module.

    Returns ``dict[object, object]`` because PyYAML can map the bare ``on:``
    key to Python boolean ``True`` (YAML 1.1 treats ``on`` as truthy), which
    forces the key type to be wider than ``str``.
    """
    assert WORKFLOW_PATH.is_file(), (
        f"hostile-reviewer workflow missing: {WORKFLOW_PATH}. "
        "OMN-8603 requires this CI gate to be wired."
    )
    with WORKFLOW_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), "workflow root must be a mapping"
    return loaded


def test_workflow_is_valid_yaml(workflow: dict[object, object]) -> None:
    """The workflow file must parse as a mapping with a name."""
    assert workflow.get("name"), "workflow must declare a top-level name"


def test_workflow_triggers_on_pull_request(workflow: dict[object, object]) -> None:
    """Workflow must run on PR open / synchronize / reopen against main.

    PyYAML maps the bare ``on:`` key to Python boolean ``True`` because YAML
    1.1 treats ``on`` as a truthy literal — accept either spelling.
    """
    triggers = workflow.get("on") or workflow.get(True)
    assert isinstance(triggers, dict), "workflow must declare a triggers mapping"

    pr_block = triggers.get("pull_request")
    assert isinstance(pr_block, dict), "pull_request trigger must be a mapping"

    types = pr_block.get("types") or []
    assert "opened" in types, "must trigger on PR opened"
    assert "synchronize" in types, "must trigger on PR synchronize"
    assert "reopened" in types, "must trigger on PR reopened"

    branches = pr_block.get("branches") or []
    assert "main" in branches, "must gate PRs targeting main"


def test_review_job_runs_on_self_hosted_runner(workflow: dict[object, object]) -> None:
    """The review job must run on the self-hosted ``omnibase-ci`` runner.

    The DeepSeek-R1 endpoint at .201:8001 is LAN-only — GitHub-hosted
    runners cannot reach it. This is the fundamental constraint that drove
    OMN-8603 (runner toolchain) and pins the gate to .201.
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    review_job = jobs.get("hostile-review")
    assert isinstance(review_job, dict), "hostile-review job must exist"

    runs_on = review_job.get("runs-on")
    assert runs_on is not None, "hostile-review must declare runs-on"
    # ``runs-on`` may be a list (labels) or a string. Normalize to a set.
    labels = set(runs_on) if isinstance(runs_on, list) else {runs_on}
    assert "self-hosted" in labels, "runner must be self-hosted"
    assert "omnibase-ci" in labels, (
        "runner label must include 'omnibase-ci' so the .201 LAN endpoints "
        "(LLM_DEEPSEEK_URL) are reachable"
    )


def test_review_step_invokes_cli_review_with_model(
    workflow: dict[object, object],
) -> None:
    """At least one step must invoke ``cli_review`` with ``--model``.

    Does not pin a specific model — model selection is a tunable per OMN-8524
    (currently ``deepseek-r1`` only; ``codex`` blocked on non-interactive auth).
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)

    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps, "review job must have steps"

    run_blocks = [
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and step.get("run")
    ]
    combined = "\n".join(run_blocks)

    assert "omniintelligence.review_pairing.cli_review" in combined, (
        "review job must invoke omniintelligence.review_pairing.cli_review"
    )
    assert "--model" in combined, (
        "review job must pass at least one --model flag to cli_review"
    )
    assert "--pr" in combined and "--repo" in combined, (
        "review job must pass --pr and --repo to cli_review"
    )


def test_summary_comment_step_present(workflow: dict[object, object]) -> None:
    """A step must post a summary PR comment via actions/github-script."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    steps = review_job.get("steps") or []

    script_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict)
            and isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/github-script@")
        ),
        None,
    )
    assert script_step is not None, (
        "must include an actions/github-script step that posts the verdict comment"
    )
    # Comment posting must run regardless of review outcome so degraded /
    # blocked verdicts still surface to the PR author.
    assert script_step.get("if") == "always()", (
        "summary comment step must run with if: always()"
    )


def test_gate_job_depends_on_review_and_fails_on_failure(
    workflow: dict[object, object],
) -> None:
    """The ``hostile-review-gate`` job must be the merge-blocking aggregator.

    It must:
    - declare ``needs: [hostile-review]``
    - run with ``if: always()`` so it surfaces verdict even on review crash
    - exit non-zero when ``needs.hostile-review.result == 'failure'``
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    gate_job = jobs.get("hostile-review-gate")
    assert isinstance(gate_job, dict), "hostile-review-gate job must exist"

    needs = gate_job.get("needs")
    needs_list = [needs] if isinstance(needs, str) else list(needs or [])
    assert "hostile-review" in needs_list, "gate must depend on the hostile-review job"

    assert gate_job.get("if") == "always()", (
        "gate job must use if: always() so degraded review still produces a verdict"
    )

    steps = gate_job.get("steps") or []
    run_text = "\n".join(
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and step.get("run")
    )
    assert "needs.hostile-review.result" in run_text, (
        "gate must read needs.hostile-review.result"
    )
    assert "exit 1" in run_text, (
        "gate must exit non-zero when the review reports failure"
    )


def test_no_anthropic_api_key_required(workflow: dict[object, object]) -> None:
    """ANTHROPIC_API_KEY must NOT appear in any env block (OMN-7467 guard).

    Claude Code authenticates via OAuth; requiring ANTHROPIC_API_KEY in CI
    has regressed 6+ times across the org and is an explicit anti-pattern in
    ``~/.claude/CLAUDE.md``.
    """
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Match the env-var name as a required key, not as a sanitizer regex or
    # commented documentation. The simplest robust check is "no occurrence
    # at all" in this file — there is no legitimate reason to mention the
    # variable in this workflow.
    assert "ANTHROPIC_API_KEY" not in raw, (
        "ANTHROPIC_API_KEY must not be referenced in the hostile-reviewer "
        "workflow — Claude Code uses OAuth (OMN-7467)"
    )


def test_workflow_has_pr_write_permission(workflow: dict[object, object]) -> None:
    """The workflow must grant ``pull-requests: write`` so it can post comments."""
    permissions = workflow.get("permissions")
    assert isinstance(permissions, dict), "workflow must declare permissions"
    assert permissions.get("pull-requests") == "write", (
        "workflow must request pull-requests: write to post the verdict comment"
    )
    assert permissions.get("contents") == "read", (
        "workflow should request only contents: read (least privilege)"
    )
