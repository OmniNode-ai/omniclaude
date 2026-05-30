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


def test_reusable_deploy_gate_uses_retrying_occ_contract_checkout() -> None:
    workflow = _load_workflow()
    job = _deploy_gate_job(workflow)

    assert job["timeout-minutes"] == 25

    step = _step(
        job, "Checkout onex_change_control contracts (canonical contract source)"
    )
    assert step["if"] == "github.event_name != 'merge_group'"
    assert "uses" not in step
    assert step["env"]["OCC_REF"] == "dev"
    assert (
        step["env"]["OCC_REPO_URL"]
        == "https://github.com/OmniNode-ai/onex_change_control.git"
    )

    run = step["run"]
    assert "retry_delays=(0 10 20 30 45)" in run
    assert "git -C _occ sparse-checkout init --cone" in run
    assert "git -C _occ sparse-checkout set contracts" in run
    assert "timeout 90 git -C _occ" in run
    assert "-c http.version=HTTP/1.1" in run
    assert "extraheader=${git_auth_header}" in run
    assert "fetch --depth=1 --filter=blob:none origin" in run
    assert "test -d _occ/contracts" in run
    assert "OCC contracts checkout failed after" in run
