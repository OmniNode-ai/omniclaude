# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract tests for the reusable anti-growth baseline workflow (OMN-19677).

PyYAML uses YAML 1.1 semantics, so the workflow's ``on:`` key parses as the
boolean ``True`` rather than the string ``"on"``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "anti-growth-baseline-reusable.yml"
)
JOB_ID = "anti-growth-baseline"


def _raw_workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(_raw_workflow())
    assert isinstance(document, dict)
    return document


def _job() -> dict[str, Any]:
    job = _workflow()["jobs"][JOB_ID]
    assert isinstance(job, dict)
    return job


def _steps() -> list[dict[str, Any]]:
    steps = _job()["steps"]
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _step_by_name(name: str) -> dict[str, Any]:
    matches = [step for step in _steps() if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _step_by_id(step_id: str) -> dict[str, Any]:
    matches = [step for step in _steps() if step.get("id") == step_id]
    assert len(matches) == 1
    return matches[0]


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _run_bash(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env},
    )


def test_no_reference_to_the_empty_github_property() -> None:
    raw = _raw_workflow()
    assert "github.job_workflow_sha" not in raw

    for step in _steps():
        for key in ("with", "env", "run", "if"):
            for value in _string_values(step.get(key)):
                assert "job_workflow_sha" not in value


def test_self_fetch_is_pinned_to_the_resolved_pin() -> None:
    steps = _steps()
    checkout_index, checkout = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/checkout")
        and (step.get("with") or {}).get("repository") == "OmniNode-ai/omniclaude"
    )
    assert checkout["with"]["ref"] == "${{ steps.pin.outputs.sha }}"

    pin_index, pin = next(
        (index, step) for index, step in enumerate(steps) if step.get("id") == "pin"
    )
    assert pin_index < checkout_index
    assert pin["env"]["WORKFLOW_SHA"] == "${{ job.workflow_sha }}"
    assert "^[0-9a-f]{40}$" in pin["run"]
    assert "exit 1" in pin["run"]


def test_pin_step_fails_closed(tmp_path: Path) -> None:
    script = str(_step_by_id("pin")["run"])
    valid_sha = "0123456789abcdef0123456789abcdef01234567"
    cases = [
        ("", "OmniNode-ai/omniclaude", False),
        ("01234567", "OmniNode-ai/omniclaude", False),
        ("A" * 40, "OmniNode-ai/omniclaude", False),
        (valid_sha, "OmniNode-ai/omniclaude", True),
        (valid_sha, "someone/else", False),
    ]

    for index, (sha, repository, should_pass) in enumerate(cases):
        output = tmp_path / f"github-output-{index}"
        result = _run_bash(
            script,
            {
                "WORKFLOW_SHA": sha,
                "WORKFLOW_REPOSITORY": repository,
                "GITHUB_OUTPUT": str(output),
            },
        )
        assert (result.returncode == 0) is should_pass, result.stderr
        written = output.read_text(encoding="utf-8") if output.exists() else ""
        if should_pass:
            assert written == f"sha={valid_sha}\n"
        else:
            assert written == ""


def test_private_repo_guard_fails_closed() -> None:
    steps = _steps()
    guard = _step_by_name("Refuse a private repository on a GitHub-hosted runner")
    script = str(guard["run"])
    cases = [
        ("private", "github-hosted", False),
        ("internal", "github-hosted", False),
        ("", "github-hosted", False),
        ("private", "", False),
        ("private", "self-hosted", True),
        ("public", "github-hosted", True),
    ]

    for visibility, runner_environment, should_pass in cases:
        result = _run_bash(
            script,
            {
                "REPO_VISIBILITY": visibility,
                "RUNNER_ENVIRONMENT": runner_environment,
            },
        )
        assert (result.returncode == 0) is should_pass, result.stderr

    guard_index = steps.index(guard)
    checkout_indexes = [
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkout_indexes
    assert all(guard_index < index for index in checkout_indexes)


def test_head_assertion_is_present() -> None:
    step = _step_by_name(
        "Resolve merge-base authority and enforce shrink-only baseline"
    )
    assert "rev-parse HEAD" in step["run"]
    assert step["env"]["GATE_PIN"] == "${{ steps.pin.outputs.sha }}"


def test_runs_on_fork_branch_requires_public_visibility() -> None:
    runs_on = str(_job()["runs-on"])
    assert "github.event.repository.visibility == 'public'" in runs_on
    assert "vars.OMNI_PUBLIC_PR_RUNS_ON_JSON" in runs_on
    assert "vars.OMNI_TRUSTED_CI_RUNS_ON_JSON" in runs_on


def test_no_workflow_call_inputs_beyond_baseline_and_parser() -> None:
    document = _workflow()
    on_block = document[True]
    assert isinstance(on_block, dict)
    workflow_call = on_block["workflow_call"]
    assert isinstance(workflow_call, dict)
    assert set(workflow_call["inputs"]) == {"baseline-path", "parser"}
