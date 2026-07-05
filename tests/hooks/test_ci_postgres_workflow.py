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
NO_FAKED_BOUNDARY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "no-faked-boundary.yml"
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


def test_golden_chain_live_is_required_service_container_gate(
    ci_workflow: dict[str, Any],
) -> None:
    job = _job(ci_workflow, "golden-chain-live")
    services = job.get("services")
    assert isinstance(services, dict)
    assert "redpanda" in services
    redpanda = services["redpanda"]
    assert isinstance(redpanda, dict)
    redpanda_options = redpanda.get("options")
    assert isinstance(redpanda_options, str)
    assert "--cpus 1" in redpanda_options
    assert "--cpuset-cpus 0" in redpanda_options
    assert "postgres" not in services

    env = job.get("env")
    assert isinstance(env, dict)
    assert env.get("KAFKA_BOOTSTRAP_SERVERS") == "localhost:9092"
    assert (
        env.get("GOLDEN_CHAIN_PG_CONTAINER")
        == "omniclaude-golden-chain-postgres-${{ github.run_id }}"
    )

    start_step = _step(job, "Start golden-chain Postgres")
    assert "docker run -d" in start_step["run"]
    assert '--name "$GOLDEN_CHAIN_PG_CONTAINER"' in start_step["run"]
    assert 'docker rm -f "$GOLDEN_CHAIN_PG_CONTAINER"' in start_step["run"]
    assert "-p 127.0.0.1::5432" in start_step["run"]
    assert "POSTGRES_HOST_AUTH_METHOD=trust" in start_step["run"]
    assert 'docker port "$GOLDEN_CHAIN_PG_CONTAINER" 5432/tcp' in start_step["run"]
    assert 'docker logs "$GOLDEN_CHAIN_PG_CONTAINER"' in start_step["run"]
    assert 'pg_isready -h 127.0.0.1 -p "$port"' in start_step["run"]
    assert "GOLDEN_CHAIN_PGPORT=${port}" in start_step["run"]

    run_step = _step(job, "Run live golden-chain sweep")
    assert run_step.get("continue-on-error") is not True
    assert "golden_chain@127.0.0.1:${GOLDEN_CHAIN_PGPORT}" in run_step["run"]
    assert "scripts/ci/run_golden_chain_live.py" in run_step["run"]

    cleanup_step = _step(job, "Stop golden-chain Postgres")
    assert cleanup_step.get("if") == "always()"
    assert 'docker rm -f "$GOLDEN_CHAIN_PG_CONTAINER"' in cleanup_step["run"]

    tests_gate = _job(ci_workflow, "tests-gate")
    needs = tests_gate.get("needs")
    assert isinstance(needs, list)
    assert "golden-chain-live" in needs
    gate_run = _step(tests_gate, "Check test results")["run"]
    assert "golden-chain-live=${{ needs.golden-chain-live.result }}" in gate_run


def test_ci_summary_checks_contract_compliance_result(
    ci_workflow: dict[str, Any],
) -> None:
    summary = _job(ci_workflow, "ci-summary")
    assert "needs" not in summary
    assert summary.get("runs-on") == "ubuntu-latest"
    assert summary.get("if") == "always()"

    run = _step(summary, "Poll run jobs and compute fail-closed CI Summary verdict")[
        "run"
    ]
    assert "scripts/ci/ci_summary_gate.py" in run
    assert '--run-attempt "${RUN_ATTEMPT}"' in run
    assert "repos/${GH_REPO}/actions/runs/${RUN_ID}/jobs?filter=all&per_page=100" in run
    assert "CI Summary = FAILURE (fail-closed: a gating job failed/cancelled)" in run


def test_contract_compliance_pins_uv_python(ci_workflow: dict[str, Any]) -> None:
    job = _job(ci_workflow, "contract-compliance")
    setup_step = _step(job, "Set up Python")
    install_step = _step(job, "Install onex_change_control")

    assert setup_step.get("uses") == "actions/setup-python@v6"
    assert setup_step["with"]["python-version"] == "${{ env.PYTHON_VERSION }}"
    assert '--python "${PYTHON_VERSION}"' in install_step["run"]


def test_no_faked_boundary_pins_uv_python() -> None:
    loaded = yaml.safe_load(NO_FAKED_BOUNDARY_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs["no-faked-boundary-gate"]
    assert isinstance(job, dict)

    install_step = _step(job, "Install dependencies")
    assert '--python "${PYTHON_VERSION}"' in install_step["run"]


def test_plugin_compat_pins_uv_python() -> None:
    loaded = yaml.safe_load(PLUGIN_COMPAT_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded.get("jobs")
    assert isinstance(jobs, dict)
    job = jobs["plugin-compat-gate"]
    assert isinstance(job, dict)

    install_step = _step(job, "Install dependencies")
    assert '--python "${PYTHON_VERSION}"' in install_step["run"]


def test_ci_uv_sync_steps_pin_python(ci_workflow: dict[str, Any]) -> None:
    jobs = ci_workflow.get("jobs")
    assert isinstance(jobs, dict)

    offenders: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str) or "uv sync" not in run:
                continue
            for line in run.splitlines():
                stripped = line.strip()
                if stripped.startswith("uv sync") and "--python" not in stripped:
                    offenders.append(f"{job_name}: {step.get('name')}: {stripped}")

    assert offenders == []


def test_legacy_integration_tests_workflow_remains_manual_only() -> None:
    loaded = yaml.safe_load(INTEGRATION_TESTS_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    triggers = loaded.get(True)
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}


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
        assert step.get("uses") == "actions/cache/restore@v6"
