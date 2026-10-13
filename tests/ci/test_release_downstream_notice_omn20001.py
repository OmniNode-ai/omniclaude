# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20001 - an omniclaude release notifies omnimarket so its pin moves in a PR.

Operator ruling 2026-10-01T21:43:10Z (3): a producer change that extends a
cross-repo contract notifies its consumer, and the consumer's update is raised
as a PR in the consumer repo that lands through the consumer's own checks.
``release.yml`` carries the producer half: after a non-rc release it dispatches
``omniclaude-release`` to omnimarket, whose ``omniclaude-pin-bump`` workflow
opens the pin bump PR.

Two properties, each with its own ``-k`` falsifier:

* ``release_notice``: the release workflow has a job that dispatches the event to
  omnimarket with the released version, skips a release candidate, and cannot be
  skipped for want of credentials. Each of those has a planted violation the
  check refuses.
* ``notice_wired``: this file runs in a required CI job and a pre-commit hook.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
THIS_TEST = "tests/ci/test_release_downstream_notice_omn20001.py"
NOTICE_JOB = "notify-omnimarket-pin-bump"
GUARD_STEP = "Verify the release notifies omnimarket (OMN-20001)"
GUARD_HOOK = "release-downstream-notice"


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def notice_violations(workflow: dict[str, Any]) -> list[str]:
    job = (workflow.get("jobs") or {}).get(NOTICE_JOB)
    if not isinstance(job, dict):
        return [f"release.yml has no {NOTICE_JOB} job"]
    violations: list[str] = []
    if job.get("needs") != "release":
        violations.append("the notice does not wait for the release job")
    condition = str(job.get("if", ""))
    if "needs.release.outputs.version" not in condition or "'rc'" not in condition:
        violations.append("the notice does not skip a release candidate")
    if job.get("continue-on-error"):
        violations.append("the notice job is allowed to fail silently")
    steps = job.get("steps") or []
    mints = [
        s
        for s in steps
        if str(s.get("uses", "")).startswith("actions/create-github-app-token@")
    ]
    if len(mints) != 1:
        violations.append("the notice does not mint exactly one App token")
    else:
        mint = mints[0]
        if mint.get("with", {}).get("repositories") != "omnimarket":
            violations.append("the App token is not scoped to omnimarket")
        if mint.get("continue-on-error") or mint.get("if"):
            violations.append("the App token mint can be skipped")
    if any(s.get("if") for s in steps):
        violations.append("a notice step is conditional, so the notice can be skipped")
    dispatches = [
        s
        for s in steps
        if str(s.get("uses", "")).startswith("peter-evans/repository-dispatch@")
    ]
    if len(dispatches) != 1:
        violations.append("the notice does not dispatch exactly once")
        return violations
    with_block = dispatches[0].get("with", {})
    if with_block.get("repository") != "OmniNode-ai/omnimarket":
        violations.append("the dispatch does not target OmniNode-ai/omnimarket")
    if with_block.get("event-type") != "omniclaude-release":
        violations.append("the dispatch event-type is not omniclaude-release")
    if "needs.release.outputs.version" not in str(with_block.get("client-payload", "")):
        violations.append("the dispatch does not carry the released version")
    return violations


def test_release_notice_holds_on_the_live_workflow() -> None:
    assert notice_violations(_load(RELEASE)) == []


def _mutated(change: Any) -> list[str]:
    workflow = copy.deepcopy(_load(RELEASE))
    change(workflow["jobs"][NOTICE_JOB])
    return notice_violations(workflow)


def test_release_notice_refuses_a_workflow_without_the_job() -> None:
    workflow = copy.deepcopy(_load(RELEASE))
    del workflow["jobs"][NOTICE_JOB]
    assert notice_violations(workflow) == [f"release.yml has no {NOTICE_JOB} job"]


def test_release_notice_refuses_a_job_that_does_not_skip_a_candidate() -> None:
    assert "the notice does not skip a release candidate" in _mutated(
        lambda job: job.pop("if")
    )


def test_release_notice_refuses_the_wrong_event_type() -> None:
    def change(job: dict[str, Any]) -> None:
        job["steps"][-1]["with"]["event-type"] = "plugin-release"

    assert "the dispatch event-type is not omniclaude-release" in _mutated(change)


def test_release_notice_refuses_the_wrong_target_repository() -> None:
    def change(job: dict[str, Any]) -> None:
        job["steps"][-1]["with"]["repository"] = "OmniNode-ai/omnibase_infra"

    assert "the dispatch does not target OmniNode-ai/omnimarket" in _mutated(change)


def test_release_notice_refuses_a_payload_without_the_version() -> None:
    def change(job: dict[str, Any]) -> None:
        job["steps"][-1]["with"]["client-payload"] = '{"package": "omninode-claude"}'

    assert "the dispatch does not carry the released version" in _mutated(change)


def test_release_notice_refuses_a_skippable_dispatch() -> None:
    def change(job: dict[str, Any]) -> None:
        job["steps"][-1]["if"] = "steps.token_check.outputs.has_token == 'true'"

    assert "a notice step is conditional, so the notice can be skipped" in _mutated(
        change
    )


def test_release_notice_refuses_a_job_that_may_fail_silently() -> None:
    assert "the notice job is allowed to fail silently" in _mutated(
        lambda job: job.update({"continue-on-error": True})
    )


def _precommit_hook(hook_id: str) -> dict[str, Any]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == hook_id
    ]
    assert len(hooks) == 1, f"expected one {hook_id!r} hook, found {len(hooks)}"
    return hooks[0]


def test_notice_wired_into_ci_and_precommit() -> None:
    steps = [
        step
        for job in _load(CI)["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == GUARD_STEP
    ]
    assert len(steps) == 1, f"expected one {GUARD_STEP!r} step, found {len(steps)}"
    assert THIS_TEST in str(steps[0]["run"])
    hook = _precommit_hook(GUARD_HOOK)
    assert THIS_TEST in str(hook["entry"])
    assert hook["pass_filenames"] is False
    assert hook["stages"] == ["pre-commit"]
    assert re.search(hook["files"], ".github/workflows/release.yml")
    assert re.search(hook["files"], THIS_TEST)
