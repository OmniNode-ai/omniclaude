# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Every CI job that runs ``uv sync`` provisions its Python first (OMN-18512).

``Comment Render Delegation (OMN-18512)`` and ``Refusal Surface (OMN-18983)``
ran ``uv sync --python 3.12`` with no ``actions/setup-python`` step before it.
On a runner without a matching interpreter, ``uv`` then downloads a managed
CPython from github.com/astral-sh/python-build-standalone. On 2026-11-08 that
download answered ``504 Gateway Timeout`` on all three retries of all three
sync attempts, so the required check failed on omniclaude#3212, #3219 and #3220
for a reason unrelated to those pull requests. Jobs that do run
``actions/setup-python`` first resolved the toolcache interpreter and passed on
the same heads.

The guard reads ``ci.yml`` the way the runner does: a job that invokes
``uv sync`` must have a ``setup-python`` step that precedes the sync step.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
# The two jobs that went red on 2026-11-08 must stay covered by this guard.
RECORDED_FAILURES = ("comment-render-delegation", "refusal-surface")


def _uv_sync_jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: job
        for name, job in workflow["jobs"].items()
        if any("uv sync" in str(step.get("run", "")) for step in job.get("steps", []))
    }


def _python_provisioned_before_sync(job: dict[str, Any]) -> bool:
    for step in job.get("steps", []):
        if "actions/setup-python" in str(step.get("uses", "")):
            return True
        if "uv sync" in str(step.get("run", "")):
            return False
    return False


@pytest.mark.unit
def test_ci_uv_sync_jobs_provision_python_first() -> None:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = _uv_sync_jobs(workflow)
    missing = sorted(
        name for name, job in jobs.items() if not _python_provisioned_before_sync(job)
    )
    assert not missing, (
        "These ci.yml jobs run `uv sync` without an earlier actions/setup-python "
        "step, so uv downloads CPython from github.com at run time and the job "
        f"fails when that download does (OMN-18512): {missing}"
    )


@pytest.mark.unit
def test_recorded_failures_are_still_covered_by_the_guard() -> None:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = _uv_sync_jobs(workflow)
    for name in RECORDED_FAILURES:
        assert name in jobs, f"{name} no longer runs uv sync; update the guard"
