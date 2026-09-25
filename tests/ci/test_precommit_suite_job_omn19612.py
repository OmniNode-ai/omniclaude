# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pin whole-tree CI coverage for staged-scoped pre-commit hooks (OMN-19612)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci.ci_summary_gate import GATE_JOBS, SOFT_ALLOWLIST, STRICT_SUCCESS_JOBS

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
JOB_ID = "precommit-suite"
JOB_NAME = "Pre-commit Suite (OMN-19612)"


def _load_yaml(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} did not parse to a mapping"
    return loaded


def _workflow() -> dict:
    return _load_yaml(CI_WORKFLOW)


def _job() -> dict:
    jobs = _workflow()["jobs"]
    assert JOB_ID in jobs, f"ci.yml has no `{JOB_ID}` job"
    return jobs[JOB_ID]


def _staged_scoped_hook_ids() -> set[str]:
    """Derive explicit filename-filtered hooks from the live configuration."""
    config = _load_yaml(PRECOMMIT_CONFIG)
    return {
        str(hook["id"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("pass_filenames") is True and bool(hook.get("files"))
    }


def test_every_staged_scoped_hook_has_a_whole_tree_counterpart() -> None:
    staged_scoped = _staged_scoped_hook_ids()
    assert staged_scoped, "expected at least one explicitly staged-scoped hook"

    commands = "\n".join(str(step.get("run", "")) for step in _job()["steps"])
    assert "SKIP=" not in commands
    for hook_id in staged_scoped:
        assert "pre-commit run --all-files" in commands, (
            f"{hook_id} has no whole-tree pre-commit counterpart"
        )


def test_whole_tree_job_is_unconditional_and_fail_closed() -> None:
    job = _job()
    assert "if" not in job
    assert "needs" not in job
    assert job.get("continue-on-error") is not True
    for step in job["steps"]:
        assert "if" not in step, f"conditional step: {step.get('name')}"
        assert step.get("continue-on-error") is not True, (
            f"advisory step: {step.get('name')}"
        )


def test_whole_tree_job_is_required_by_ci_summary() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS
    assert JOB_NAME not in SOFT_ALLOWLIST


def test_workflow_has_no_pull_request_path_filter() -> None:
    workflow = _workflow()
    triggers = workflow[True] if True in workflow else workflow["on"]
    pull_request = triggers.get("pull_request") or {}
    assert "paths" not in pull_request
    assert "paths-ignore" not in pull_request
