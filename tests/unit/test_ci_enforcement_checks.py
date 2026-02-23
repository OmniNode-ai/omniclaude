"""
Unit tests for CI enforcement gate scripts introduced in OMN-2592.

Each script in scripts/validation/ has a corresponding section here.
Tests verify that:
  - Compliant code returns exit 0 (no violations)
  - Violating code returns exit 1 (violations detected)

Test data is provided via pytest fixtures and parametrize markers rather than
hardcoded inline strings, so new cases can be added in one place.
"""

from __future__ import annotations

import importlib.util
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

# -----------------------------------------------------------------------
# Helper: load a validation script as a module
# -----------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "validation"


def load_validator(name: str):  # type: ignore[return]
    """Load a validation script module by filename stem."""
    script_path = SCRIPTS_DIR / f"{name}.py"
    if not script_path.exists():
        pytest.fail(f"Validation script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# -----------------------------------------------------------------------
# Helpers for inline source checking
# -----------------------------------------------------------------------


def _check_source(
    checker_fn: Callable[[Path], list[str]],
    source: str,
    tmp_path: Path,
    filename: str = "test_file.py",
) -> list[str]:
    """Write source to a temp file and run checker_fn against it."""
    py_file = tmp_path / filename
    py_file.write_text(textwrap.dedent(source))
    return checker_fn(py_file)


# -----------------------------------------------------------------------
# Test data fixtures: violation sources for parametrized tests
# -----------------------------------------------------------------------

# (description, source_snippet) pairs — each must produce >= 1 violation
NO_DB_VIOLATION_SOURCES = [
    (
        "sqlalchemy_import",
        """
        from sqlalchemy.ext.asyncio import AsyncSession

        class NodeMyOrchestrator:
            async def execute_orchestration(self, session: AsyncSession):
                result = await session.execute("SELECT 1")
        """,
    ),
    (
        "select_sql_string",
        """
        class NodeMyOrchestrator:
            async def execute_orchestration(self):
                sql = "SELECT * FROM runs WHERE id = $1"
                return sql
        """,
    ),
    (
        "fetchall_method_call",
        """
        class NodeMyOrchestrator:
            async def execute_orchestration(self, conn):
                rows = await conn.fetchall()
                return rows
        """,
    ),
]

KAFKA_VIOLATION_SOURCES = [
    (
        "aiokafka_import",
        """
        from aiokafka import AIOKafkaProducer

        async def send_msg():
            producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
            await producer.start()
        """,
    ),
    (
        "confluent_kafka_import",
        """
        from confluent_kafka import Producer
        """,
    ),
    (
        "kafka_attribute_access",
        """
        import kafka

        def get_producer():
            return kafka.KafkaProducer(bootstrap_servers="localhost:9092")
        """,
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# 1. validate_no_db_in_orchestrator
# ═══════════════════════════════════════════════════════════════════════


class TestNoDbInOrchestrator:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_db_in_orchestrator")

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        source = '''
        """Orchestrator node — no DB access."""
        from omniclaude.some_service import SomeService

        class NodeMyOrchestrator:
            async def execute_orchestration(self, ctx):
                return await SomeService().process(ctx)
        '''
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    @pytest.mark.parametrize(("description", "source"), NO_DB_VIOLATION_SOURCES)
    def test_violation_detected(
        self, description: str, source: str, tmp_path: Path
    ) -> None:
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1, (
            f"Expected violation for case '{description}' but got none"
        )


# ═══════════════════════════════════════════════════════════════════════
# 2. validate_no_git_outside_effects
# ═══════════════════════════════════════════════════════════════════════


class TestNoGitOutsideEffects:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_git_outside_effects")

    def test_non_effect_clean_file_passes(self, tmp_path: Path) -> None:
        source = """
        import os

        def compute_something():
            return 42
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_subprocess_git_caught(self, tmp_path: Path) -> None:
        source = """
        import subprocess

        def bad_fn():
            subprocess.run(["git", "commit", "-m", "msg"])
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_subprocess_gh_string_caught(self, tmp_path: Path) -> None:
        source = """
        import subprocess

        def bad_fn():
            result = subprocess.check_output("gh pr create --title test", shell=True)
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_effect_file_is_allowed(self, tmp_path: Path) -> None:
        source = """
        import subprocess

        def push_to_remote():
            subprocess.run(["git", "push", "origin", "main"])
        """
        # Effect files are allowed
        assert self.mod.is_effect_file(tmp_path / "node_git_effect.py") is True
        assert self.mod.is_effect_file(tmp_path / "node_compute.py") is False


# ═══════════════════════════════════════════════════════════════════════
# 3. validate_no_linear_outside_effects
# ═══════════════════════════════════════════════════════════════════════


class TestNoLinearOutsideEffects:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_linear_outside_effects")

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.some_compute import process
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_linear_client_import_caught(self, tmp_path: Path) -> None:
        source = """
        from linear_sdk import LinearClient

        client = LinearClient(api_key="secret")
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_effect_file_is_exempted(self, tmp_path: Path) -> None:
        assert self.mod.is_effect_file(tmp_path / "node_linear_effect.py") is True
        assert self.mod.is_effect_file(tmp_path / "node_compute.py") is False


# ═══════════════════════════════════════════════════════════════════════
# 4. validate_no_repo_adapter_in_orchestrator
# ═══════════════════════════════════════════════════════════════════════


class TestNoRepoAdapterInOrchestrator:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_repo_adapter_in_orchestrator")

    def test_clean_orchestrator_passes(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.nodes.some_effect import SomeEffect

        class NodeMyOrchestrator:
            pass
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_repository_import_caught(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.lib.repository.run_repository import RunRepository
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_db_adapter_import_caught(self, tmp_path: Path) -> None:
        source = """
        import omniclaude.db_adapter as adapter
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 5. validate_cost_ledger_isolation
# ═══════════════════════════════════════════════════════════════════════


class TestCostLedgerIsolation:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_cost_ledger_isolation")

    def test_clean_non_effect_file_passes(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.lib.budget import BudgetSummary
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_model_cost_ledger_import_caught(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.models import ModelCostLedger
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_effect_file_is_allowed(self, tmp_path: Path) -> None:
        # Effect files must be inside a node_* ancestor directory to be whitelisted.
        # A bare *_effect.py in an arbitrary directory is NOT an effect module.
        node_dir = tmp_path / "node_budget_evaluator"
        assert self.mod.is_effect_module(node_dir / "node_budget_effect.py") is True
        assert self.mod.is_effect_module(tmp_path / "node_budget_effect.py") is False
        assert self.mod.is_effect_module(tmp_path / "node_budget_compute.py") is False


# ═══════════════════════════════════════════════════════════════════════
# 6. validate_topic_naming
# ═══════════════════════════════════════════════════════════════════════


class TestTopicNaming:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_topic_naming")

    def test_valid_topic_passes(self, tmp_path: Path) -> None:
        source = """
        TOPIC = "onex.evt.omniclaude.prompt-submitted.v1"
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_valid_cmd_topic_passes(self, tmp_path: Path) -> None:
        source = """
        TOPIC = "onex.cmd.omniintelligence.claude-hook-event.v1"
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_invalid_topic_caught(self, tmp_path: Path) -> None:
        source = """
        TOPIC = "onex.bad_kind.omniclaude.something.v1"
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_non_onex_string_ignored(self, tmp_path: Path) -> None:
        source = """
        MESSAGE = "hello world"
        OTHER = "some.topic.string"
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []


# ═══════════════════════════════════════════════════════════════════════
# 9. validate_cost_ledger_structure
# ═══════════════════════════════════════════════════════════════════════


class TestCostLedgerStructure:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_cost_ledger_structure")

    def test_no_ledger_class_skips(self, tmp_path: Path) -> None:
        source = """
        class SomeOtherModel:
            id: int
        """
        py = tmp_path / "model.py"
        py.write_text(textwrap.dedent(source))
        found, violations = self.mod.check_file(py)
        assert not found
        assert violations == []

    def test_ledger_without_run_id_fails(self, tmp_path: Path) -> None:
        source = """
        class ModelCostLedger:
            id: int
            amount: float
        """
        py = tmp_path / "model_cost_ledger.py"
        py.write_text(textwrap.dedent(source))
        found, violations = self.mod.check_file(py)
        assert found
        assert any("run_id" in v for v in violations)

    def test_ledger_with_run_id_and_index_passes(self, tmp_path: Path) -> None:
        source = """
        from sqlalchemy.orm import mapped_column, Mapped
        import uuid

        class ModelCostLedger:
            id: Mapped[uuid.UUID]
            run_id: Mapped[uuid.UUID] = mapped_column(index=True)
            amount: Mapped[float]
        """
        py = tmp_path / "model_cost_ledger.py"
        py.write_text(textwrap.dedent(source))
        found, violations = self.mod.check_file(py)
        assert found
        assert violations == []


# ═══════════════════════════════════════════════════════════════════════
# 10. validate_no_direct_kafka_producer
# ═══════════════════════════════════════════════════════════════════════


class TestNoDirectKafkaProducer:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_direct_kafka_producer")

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        source = """
        from omniclaude.publisher.emit_client import emit_event
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    @pytest.mark.parametrize(("description", "source"), KAFKA_VIOLATION_SOURCES)
    def test_violation_detected(
        self, description: str, source: str, tmp_path: Path
    ) -> None:
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1, (
            f"Expected violation for case '{description}' but got none"
        )

    def test_publisher_path_is_allowed(self, tmp_path: Path) -> None:
        assert (
            self.mod.is_allowed_path(tmp_path / "publisher" / "embedded_publisher.py")
            is True
        )
        assert self.mod.is_allowed_path(tmp_path / "nodes" / "node_compute.py") is False


# ═══════════════════════════════════════════════════════════════════════
# 11. validate_no_utcnow
# ═══════════════════════════════════════════════════════════════════════


class TestNoUtcNow:
    @pytest.fixture(autouse=True)
    def _mod(self):
        self.mod = load_validator("validate_no_utcnow")

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        source = """
        from datetime import datetime, timezone

        def now():
            return datetime.now(tz=timezone.utc)
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert violations == []

    def test_utcnow_caught(self, tmp_path: Path) -> None:
        source = """
        from datetime import datetime

        def now():
            return datetime.utcnow()
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1

    def test_datetime_datetime_utcnow_caught(self, tmp_path: Path) -> None:
        source = """
        import datetime

        ts = datetime.datetime.utcnow()
        """
        violations = _check_source(self.mod.check_file, source, tmp_path)
        assert len(violations) >= 1
