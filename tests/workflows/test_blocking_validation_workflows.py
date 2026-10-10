# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for blocking validation workflow gates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT_VALIDATION_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "contract-validation.yml"
)


def _load_workflow(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} must parse as a YAML mapping"
    return cast("dict[str, Any]", loaded)


def _job(workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    job = jobs.get(job_name)
    assert isinstance(job, dict), f"job {job_name!r} must exist"
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], step_name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list), "job must define steps"
    step = next(
        item
        for item in steps
        if isinstance(item, dict) and item.get("name") == step_name
    )
    return cast("dict[str, Any]", step)


def test_skill_node_boundary_gate_is_blocking_for_changed_skills() -> None:
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    step = _step(
        _job(workflow, "arch-invariants"), "Validate skill-node boundary (OMN-8094)"
    )
    run = step.get("run")
    assert isinstance(run, str)

    assert step.get("continue-on-error") is not True
    assert "git diff --name-only" in run
    assert "'plugins/onex/skills/**/SKILL.md'" in run
    assert '--skill "$skill"' in run
    assert "--strict" in run
    assert "baseline violations remain tracked separately" in run


def test_contract_proof_resolution_gate_is_blocking() -> None:
    workflow = _load_workflow(CONTRACT_VALIDATION_WORKFLOW_PATH)
    step = _step(_job(workflow, "contract-validation"), "Resolve proof references")
    run = step.get("run")
    assert isinstance(run, str)

    assert step.get("continue-on-error") is not True
    assert "cli_validate_proofs.py" in run
    assert "--json" in run
    assert "json_status=$?" in run
    assert "human_status=$?" in run
    assert "exit 1" in run
    assert "|| echo" not in run
    assert "Phase 1" not in step["name"]


def test_contract_validation_reads_a_pinned_validator_that_accepts_binds_ac() -> None:
    """The composite action reads OCC main, whose schema refused `binds_ac`.

    A contract that binds its criteria (which repo-evidence / dod-verify requires)
    was refused as `dod_evidence.N.binds_ac: Extra inputs are not permitted`. The
    validators are fetched at a full sha instead, as omnimarket and
    omnibase_infra do.
    """
    workflow = _load_workflow(CONTRACT_VALIDATION_WORKFLOW_PATH)
    job = _job(workflow, "contract-validation")
    steps = [item for item in job["steps"] if isinstance(item, dict)]

    assert not [
        item
        for item in steps
        if "onex_change_control/.github/actions/validate-contract"
        in str(item.get("uses", ""))
    ], "the OCC composite action resolves OCC main; fetch the validators at a sha"

    fetch = _step(job, "Check out pinned contract validators")
    run = str(fetch.get("run", ""))
    match = re.search(r"^\s*occ_sha=([0-9a-f]{40})$", run, re.MULTILINE)
    assert match, "the validators must be fetched at a full sha"
    assert "https://github.com/OmniNode-ai/onex_change_control.git" in run
    assert '"$occ_sha"' in run

    validate = _step(job, "Run contract validation")
    assert validate.get("id") == "validate-contract"
    assert "validate-yaml" in str(validate.get("run", ""))
