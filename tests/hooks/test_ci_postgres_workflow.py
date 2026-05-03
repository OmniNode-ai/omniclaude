# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Structural tests for Postgres service-port handling in CI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast("dict[str, Any]", loaded)


def _job(ci_workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    jobs = ci_workflow.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs.get(job_name)
    assert isinstance(job, dict)
    return cast("dict[str, Any]", job)


def _step(job: dict[str, Any], step_name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    step = next(
        item
        for item in steps
        if isinstance(item, dict) and item.get("name") == step_name
    )
    return cast("dict[str, Any]", step)


def test_omnidash_role_check_uses_mapped_postgres_port(
    ci_workflow: dict[str, Any],
) -> None:
    job = _job(ci_workflow, "arch-omnidash-db-role")
    install_step = _step(job, "Install PostgreSQL client")
    provision_step = _step(
        job, "Provision omnidash_readonly role and verify permissions"
    )
    provision_env = provision_step.get("env")
    assert isinstance(provision_env, dict)

    assert '-e PGPORT="${PGPORT:-}"' in install_step["run"]
    assert provision_env.get("PGPORT") == "${{ job.services.postgres.ports['5432'] }}"
    assert "for attempt in {1..30}" in provision_step["run"]
    assert 'psql -h localhost -p "$PGPORT"' in provision_step["run"]


@pytest.mark.parametrize(
    ("job_name", "step_name"),
    [
        ("hooks-tests", "Initialize hooks database"),
        ("database-validation", "Validate database schema"),
    ],
)
def test_postgres_service_jobs_use_bounded_mapped_port_waits(
    ci_workflow: dict[str, Any],
    job_name: str,
    step_name: str,
) -> None:
    step = _step(_job(ci_workflow, job_name), step_name)
    run = step["run"]

    assert "for attempt in {1..30}" in run
    assert 'psql -h localhost -p "$PGPORT"' in run
    assert "Waiting for PostgreSQL on localhost:${PGPORT}" in run
