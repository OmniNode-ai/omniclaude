# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Workflow invariants for the public-repo hygiene gate."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REUSABLE = WORKFLOWS / "public-repo-hygiene-reusable.yml"
AUDIT = WORKFLOWS / "public-repo-hygiene-audit.yml"
CALLER = WORKFLOWS / "public-repo-hygiene.yml"


def _workflow(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _step(workflow_path: Path, job_name: str, step_name: str) -> dict[str, object]:
    workflow = _workflow(workflow_path)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[job_name]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    for candidate in steps:
        assert isinstance(candidate, dict)
        if candidate.get("name") == step_name:
            return candidate
    raise AssertionError(
        f"{workflow_path} job {job_name} has no step named {step_name!r}"
    )


def test_public_repo_hygiene_reusable_uses_org_wide_onexbot_credentials() -> None:
    """Public callers do not all receive the selected OCC app secrets."""
    step = _step(
        REUSABLE, "public-repo-hygiene", "Mint token for the private vocabulary repo"
    )
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in REUSABLE.read_text(encoding="utf-8")


def test_public_repo_hygiene_audit_uses_org_wide_onexbot_credentials() -> None:
    """The org audit has the same public governance credential boundary."""
    step = _step(AUDIT, "audit", "Mint org-read token")
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in AUDIT.read_text(encoding="utf-8")


def test_public_repo_hygiene_caller_still_inherits_secrets() -> None:
    workflow = _workflow(CALLER)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    caller = jobs["public-repo-hygiene"]
    assert isinstance(caller, dict)

    assert caller["secrets"] == "inherit"
