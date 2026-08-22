# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for OMN-16371: release.yml shell-injection shape.

``workflow_dispatch`` input ``tag`` was interpolated directly into ``run:``
shell blocks under ``contents: write`` permissions, including a
``$GITHUB_OUTPUT`` forging vector (no charset guard on a value that could
carry a newline). The fix pattern is the one landed in six sibling repos
under OMN-16323 (e.g. ``omnibase_infra/.github/workflows/release.yml``):
route ``inputs.tag`` through an ``env: RELEASE_TAG`` indirection so the
shell never re-parses attacker-controlled template text, and validate the
tag charset before writing it to ``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

# Matches a raw, un-indirected `${{ inputs.tag }}` (any whitespace variant)
# appearing anywhere in workflow text -- this is the injection shape itself.
RAW_INPUTS_TAG = re.compile(r"\$\{\{\s*inputs\.tag\s*\}\}")


def _load_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _steps(workflow: dict[str, Any], job_name: str) -> list[dict[str, Any]]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"{job_name} job must exist"
    steps = job.get("steps")
    assert isinstance(steps, list), f"{job_name} job must define steps"
    return cast("list[dict[str, Any]]", steps)


def _run_steps(workflow: dict[str, Any], job_name: str) -> list[dict[str, Any]]:
    return [
        step
        for step in _steps(workflow, job_name)
        if isinstance(step, dict) and "run" in step
    ]


def test_no_raw_inputs_tag_inside_run_blocks() -> None:
    """No `run:` shell block may re-interpolate `${{ inputs.tag }}` directly.

    Direct interpolation lets a crafted `tag` value (e.g. containing `$(...)`,
    backticks, or a newline) execute as shell or forge extra
    `$GITHUB_OUTPUT` entries. Untrusted input must cross the
    template-to-shell boundary only via an `env:` variable.
    """
    workflow = _load_workflow()
    for job_name in workflow["jobs"]:
        for step in _run_steps(workflow, job_name):
            run = step["run"]
            assert not RAW_INPUTS_TAG.search(run), (
                f"job {job_name!r} step {step.get('name')!r} interpolates "
                "${{ inputs.tag }} directly into a run: block -- route it "
                "through env: RELEASE_TAG instead (OMN-16371 / OMN-16323 shape)"
            )


def test_run_steps_referencing_release_tag_use_env_indirection() -> None:
    """Every step whose shell needs the dispatch tag gets it via env:.

    Mirrors the omnibase_infra reference implementation (post-OMN-16323):
    `env: {RELEASE_TAG: ${{ inputs.tag }}}` plus a `$RELEASE_TAG` shell
    reference, never a raw template substitution.
    """
    workflow = _load_workflow()
    steps_using_release_tag = []
    for job_name in workflow["jobs"]:
        for step in _run_steps(workflow, job_name):
            run = step["run"]
            if "RELEASE_TAG" not in run:
                continue
            steps_using_release_tag.append((job_name, step))
            env = step.get("env", {})
            assert env.get("RELEASE_TAG") == "${{ inputs.tag }}", (
                f"job {job_name!r} step {step.get('name')!r} references "
                "$RELEASE_TAG in its run: block but does not set "
                "env.RELEASE_TAG from inputs.tag"
            )

    # The three known injection sites (tag-validation, release-tag output,
    # plugin-version output) must all have been converted.
    assert len(steps_using_release_tag) == 3, (
        "expected exactly 3 run: steps using RELEASE_TAG indirection "
        f"(tag validation, release tag output, plugin version output); "
        f"found {len(steps_using_release_tag)}: "
        f"{[(j, s.get('name')) for j, s in steps_using_release_tag]}"
    )


def test_github_output_writes_of_release_tag_are_charset_guarded() -> None:
    """A `$RELEASE_TAG` write to `$GITHUB_OUTPUT` must be charset-validated.

    Without a guard, a newline embedded in the dispatch input forges extra
    `GITHUB_OUTPUT` key=value entries (output-injection), regardless of the
    env: indirection fixing command injection.
    """
    workflow = _load_workflow()
    for job_name in workflow["jobs"]:
        for step in _run_steps(workflow, job_name):
            run = step["run"]
            if "RELEASE_TAG" not in run or "GITHUB_OUTPUT" not in run:
                continue
            assert "*[!A-Za-z0-9.+_-]*" in run, (
                f"job {job_name!r} step {step.get('name')!r} writes "
                "$RELEASE_TAG to $GITHUB_OUTPUT without a charset guard"
            )


def test_workflow_dispatch_tag_input_still_required() -> None:
    """Sanity: the input this test suite is guarding still exists as-is."""
    workflow = _load_workflow()
    # PyYAML (YAML 1.1) parses the bare `on:` key as the boolean True.
    on_block = workflow.get("on", workflow.get(True))
    assert isinstance(on_block, dict), "workflow must define triggers"
    tag_input = on_block["workflow_dispatch"]["inputs"]["tag"]
    assert tag_input["required"] is True
