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
INIT_DB_SCRIPT = REPO_ROOT / "scripts" / "init-db.sh"
ONEX_SCHEMA_COMPAT_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "onex-schema-compat.yml"
)
PLUGIN_COMPAT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "plugin-compat-gate.yml"
INTEGRATION_TESTS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "integration-tests.yml"
)
VENV_CACHE_RESTORE_IF = "${{ vars.OMNI_ENABLE_VENV_CACHE_RESTORE == 'true' }}"


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
    steps = _steps(job)
    step = next(
        item
        for item in steps
        if isinstance(item, dict) and item.get("name") == step_name
    )
    return cast("dict[str, Any]", step)


def _steps(job: dict[str, Any]) -> list[Any]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return steps


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
    assert "psql -v ON_ERROR_STOP=1" in provision_step["run"]
    assert "\\gexec" not in provision_step["run"]
    assert "DO $$" not in provision_step["run"]
    assert "CREATE DATABASE omnidash_analytics" in provision_step["run"]
    assert "CREATE ROLE omnidash_readonly" in provision_step["run"]
    assert "ALTER ROLE omnidash_readonly" in provision_step["run"]
    assert "public.ci_permission_test" in provision_step["run"]
    assert "DROP TABLE IF EXISTS public.ci_permission_test" in provision_step["run"]
    assert "GRANT SELECT ON public.ci_permission_test" in provision_step["run"]
    assert "SELECT to_regclass('public.ci_permission_test')" in provision_step["run"]
    assert "> /tmp/omnidash_readonly_insert.out 2>&1" in provision_step["run"]
    assert "> /tmp/omnidash_readonly_update.out 2>&1" in provision_step["run"]
    assert "> /tmp/omnidash_readonly_delete.out 2>&1" in provision_step["run"]


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


@pytest.mark.parametrize(
    ("job_name", "psql_step_name"),
    [
        ("hooks-tests", "Initialize hooks database"),
        ("database-validation", "Validate database schema"),
    ],
)
def test_postgres_service_jobs_install_psql_before_use(
    ci_workflow: dict[str, Any],
    job_name: str,
    psql_step_name: str,
) -> None:
    steps = _steps(_job(ci_workflow, job_name))
    install_index = next(
        index
        for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == "Install PostgreSQL client"
    )
    psql_index = next(
        index
        for index, step in enumerate(steps)
        if isinstance(step, dict) and step.get("name") == psql_step_name
    )
    install_step = cast("dict[str, Any]", steps[install_index])

    assert install_index < psql_index
    assert "apt-get install -y postgresql-client" in install_step["run"]
    assert '-e PGPORT="${PGPORT:-}"' in install_step["run"]


def test_init_db_tracks_migrations_in_public_schema() -> None:
    script = INIT_DB_SCRIPT.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.schema_migrations" in script
    assert "FROM public.schema_migrations" in script
    assert "INSERT INTO public.schema_migrations" in script
    assert "post-init validation surface" in script


def test_init_db_passes_configured_postgres_port_to_psql() -> None:
    script = INIT_DB_SCRIPT.read_text(encoding="utf-8")

    assert "PSQL_ARGS=(--username" in script
    assert 'PSQL_ARGS+=(--port "$POSTGRES_PORT")' in script
    assert 'PSQL_ARGS+=(--port "$PGPORT")' in script
    assert '"${PSQL_ARGS[@]}"' in script


def test_database_validation_uses_public_schema_qualified_tables(
    ci_workflow: dict[str, Any],
) -> None:
    step = _step(_job(ci_workflow, "database-validation"), "Validate database schema")
    run = step["run"]

    assert "\\dt public.*" in run
    assert "psql -v ON_ERROR_STOP=1" in run
    assert "CREATE TABLE IF NOT EXISTS public.schema_migrations" in run
    assert "\\d schema_migrations" not in run
    assert "\\d claude_session_snapshots" not in run


@pytest.mark.parametrize(
    "workflow_path",
    [
        WORKFLOW_PATH,
        ONEX_SCHEMA_COMPAT_WORKFLOW,
        PLUGIN_COMPAT_WORKFLOW,
        INTEGRATION_TESTS_WORKFLOW,
    ],
)
def test_cache_restore_steps_are_opt_in_for_ci_timeout_resilience(
    workflow_path: Path,
) -> None:
    loaded = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded.get("jobs")
    assert isinstance(jobs, dict)

    cache_steps = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if isinstance(step, dict) and str(step.get("uses", "")).startswith(
                "actions/cache"
            ):
                cache_steps.append(step)

    assert cache_steps
    for step in cache_steps:
        assert step.get("if") == VENV_CACHE_RESTORE_IF
        assert step.get("uses") == "actions/cache/restore@v5"
