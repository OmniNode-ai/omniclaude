# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for the reusable deploy-gate workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-gate-reusable.yml"


def _load_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _deploy_gate_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get("deploy-gate")
    assert isinstance(job, dict), "deploy-gate job must exist"
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "deploy-gate job must define steps"
    step = next(
        item for item in steps if isinstance(item, dict) and item.get("name") == name
    )
    return cast("dict[str, Any]", step)


def test_reusable_deploy_gate_reads_only_the_caller_contracts() -> None:
    """OMN-20074: the gate fetches only its composite action and the caller's contracts.

    No change control tree, checkout script or evidence-source resolution step
    remains; the contracts come from the caller's pull request head.
    """
    workflow = _load_workflow()
    job = _deploy_gate_job(workflow)

    assert job["timeout-minutes"] == 25

    fetch_step = _step(job, "Fetch deploy-gate support scripts (omniclaude)")
    assert fetch_step["if"] == "github.event_name != 'merge_group'"
    assert (
        fetch_step["uses"]
        == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    )
    assert fetch_step["with"]["repository"] == "OmniNode-ai/omniclaude"
    assert fetch_step["with"]["persist-credentials"] is False
    sparse_checkout = fetch_step["with"]["sparse-checkout"]
    assert ".github/actions/deploy-gate" in sparse_checkout

    head_step = _step(job, "Checkout the caller's pull request head contracts")
    assert head_step["if"] == "github.event_name != 'merge_group'"
    assert head_step["with"]["path"] == ".pr-head"

    gate_step = _step(job, "Run deploy gate (canonical composite action)")
    assert gate_step["with"]["contracts-dir"] == ".pr-head/contracts"
    assert "contract-source" not in gate_step["with"]

    names = [str(step.get("name", "")) for step in job["steps"]]
    assert not [n for n in names if "OCC" in n or "onex_change_control" in n]
