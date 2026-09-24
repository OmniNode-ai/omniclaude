# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the reusable hardcoded-model-config guard workflow.

OMN-19393, plan task A2 (knowledge-base-internal
beta/plans/2026-09-23-remove-hardcoded-model-config.md). Pins the two
properties the plan's A2 falsifiers name:

* no bypass input exists -- ``on.workflow_call.inputs`` carries only
  ``core_ref``, and no input name suggests a skip, bypass or disable path;
* the guard's own run step is unconditional -- no ``continue-on-error`` and no
  ``if:`` that could skip it -- and ``core_ref`` is validated as exactly 40
  hex characters before the guard runs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "hardcoded-model-config-reusable.yml"
)

_SKIP_NAME_PATTERN = re.compile(
    r"skip|bypass|disable|ignore|allow[-_]?fail", re.IGNORECASE
)
_FORTY_HEX = re.compile(r"^[0-9a-fA-F]{40}$")


def _load_workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _on_block(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML parses the bare key `on:` as the boolean True.
    on_block = workflow.get("on", workflow.get(True))
    assert isinstance(on_block, dict), "workflow must declare an 'on:' mapping"
    return cast("dict[str, Any]", on_block)


def _job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get("hardcoded-model-config")
    assert isinstance(job, dict), "hardcoded-model-config job must exist"
    return cast("dict[str, Any]", job)


def _guard_step(job: dict[str, Any]) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "job must define steps"
    for step in steps:
        assert isinstance(step, dict)
        run = step.get("run", "")
        if "runtime_hardcoded_model_config" in run:
            return cast("dict[str, Any]", step)
    raise AssertionError("no step invokes runtime_hardcoded_model_config")


# ---------------------------------------------------------------------------
# core_ref input: required, 40-hex, no default that would let a caller omit it
# ---------------------------------------------------------------------------


def test_core_ref_input_is_required_with_no_default() -> None:
    workflow = _load_workflow()
    inputs = _on_block(workflow)["workflow_call"]["inputs"]
    core_ref = inputs["core_ref"]
    assert core_ref["required"] is True
    assert "default" not in core_ref
    assert core_ref["type"] == "string"


@pytest.mark.parametrize(
    "value",
    [
        "b7de11ac1d9adbe5fafbf49d4711917018f3f409",  # the A1 merge sha (40 hex)
        "0" * 40,
        "F" * 40,
    ],
)
def test_forty_hex_pattern_accepts_valid_shas(value: str) -> None:
    assert _FORTY_HEX.match(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "b7de11ac1d9adbe5fafbf49d4711917018f3f40",  # 39 chars
        "b7de11ac1d9adbe5fafbf49d4711917018f3f4099",  # 41 chars
        "main",
        "dev",
        "g7de11ac1d9adbe5fafbf49d4711917018f3f409",  # non-hex char 'g'
        "not-a-sha; rm -rf /",  # shell-injection shaped
    ],
)
def test_forty_hex_pattern_rejects_everything_else(value: str) -> None:
    assert not _FORTY_HEX.match(value)


def test_guard_step_validates_core_ref_before_running() -> None:
    """The workflow's own validation step uses the identical 40-hex rule."""
    workflow = _load_workflow()
    job = _job(workflow)
    steps = job["steps"]
    validate_step = next(
        s
        for s in steps
        if isinstance(s, dict) and "core_ref must be exactly 40 hex" in s.get("run", "")
    )
    assert "0-9a-fA-F" in validate_step["run"]
    assert "{40}" in validate_step["run"]
    # The validation step must run before the guard step.
    guard_index = steps.index(_guard_step(job))
    assert steps.index(validate_step) < guard_index


# ---------------------------------------------------------------------------
# No skip / bypass input, no continue-on-error, no if: override on the guard
# ---------------------------------------------------------------------------


def test_no_skip_or_bypass_input_exists() -> None:
    workflow = _load_workflow()
    inputs = _on_block(workflow)["workflow_call"]["inputs"]
    assert set(inputs.keys()) == {"core_ref"}
    for name in inputs:
        assert not _SKIP_NAME_PATTERN.search(name), (
            f"input {name!r} looks like a bypass"
        )


def test_guard_step_has_no_continue_on_error() -> None:
    workflow = _load_workflow()
    step = _guard_step(_job(workflow))
    assert "continue-on-error" not in step


def test_guard_step_has_no_if_override() -> None:
    workflow = _load_workflow()
    step = _guard_step(_job(workflow))
    assert "if" not in step


def test_job_itself_has_no_continue_on_error_or_if() -> None:
    workflow = _load_workflow()
    job = _job(workflow)
    assert "continue-on-error" not in job
    assert "if" not in job


def test_guard_step_invokes_the_module_with_all_and_baseline() -> None:
    workflow = _load_workflow()
    step = _guard_step(_job(workflow))
    run = step["run"]
    assert (
        "python -m omnibase_core.validation.hardcoded_model_config"
        ".runtime_hardcoded_model_config" in run
    )
    assert "--all" in run
    assert "--baseline config/hardcoded_model_config_baseline.yaml" in run


def test_guard_step_installs_from_pinned_core_ref_via_uvx() -> None:
    workflow = _load_workflow()
    step = _guard_step(_job(workflow))
    run = step["run"]
    assert (
        'uvx --from "git+https://github.com/OmniNode-ai/omnibase_core@${CORE_REF}"'
        in run
    )
    assert step["env"]["CORE_REF"] == "${{ inputs.core_ref }}"


def test_guard_step_runs_shrink_only_check_against_pr_base_when_available() -> None:
    """The module exposes --base; the plan asks that it run against the PR base."""
    workflow = _load_workflow()
    step = _guard_step(_job(workflow))
    run = step["run"]
    assert "--base" in run
    assert step["env"]["PR_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"


def test_permissions_are_read_only() -> None:
    workflow = _load_workflow()
    assert workflow["permissions"] == {"contents": "read"}
