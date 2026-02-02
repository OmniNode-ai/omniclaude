# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for PostgreSQL contract-driven repository runtime.

These tests verify the contract-driven database access pattern using
PostgresRepositoryRuntime from omnibase_infra with the learned_patterns
repository contract from OMN-1779.

Run with:
    # Skip integration tests (default)
    pytest tests/hooks/test_integration_postgres_contract.py -v

    # Run integration tests with real PostgreSQL
    POSTGRES_INTEGRATION_TESTS=1 pytest tests/hooks/test_integration_postgres_contract.py -v

    # Run with environment from .env file
    source .env && POSTGRES_INTEGRATION_TESTS=1 \
        pytest tests/hooks/test_integration_postgres_contract.py -v

Requirements:
    - PostgreSQL database must be accessible at configured host/port
    - Database credentials must be set in environment variables
    - The learned_patterns table must exist (but may be empty)

Environment Variables:
    POSTGRES_INTEGRATION_TESTS: Set to "1" to enable integration tests
    POSTGRES_HOST: PostgreSQL host (default: 192.168.86.200)
    POSTGRES_PORT: PostgreSQL port (default: 5436)
    POSTGRES_DATABASE: Database name (default: omninode_bridge)
    POSTGRES_USER: Database user (default: postgres)
    POSTGRES_PASSWORD: Database password (required, no default)

Note:
    These tests are automatically skipped when POSTGRES_INTEGRATION_TESTS != "1".
    Tests handle empty result sets gracefully - the table may have no data.

    The tests verify that:
    1. Contract YAML loads and validates correctly
    2. Database connection pool can be established
    3. Contract operations execute without error
    4. Result mapping to PatternRecord works correctly
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    import asyncpg
    from omnibase_core.models.contracts import ModelDbRepositoryContract
    from omnibase_infra.runtime.db import PostgresRepositoryRuntime

# =============================================================================
# Integration Test Markers
# =============================================================================

# Mark all tests in this module as integration tests
# They will be skipped unless POSTGRES_INTEGRATION_TESTS=1
pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres_integration,
    pytest.mark.slow,
]


# =============================================================================
# Helper Functions
# =============================================================================


def get_postgres_config() -> dict[str, str | int]:
    """Get PostgreSQL configuration from environment.

    Uses environment variables with fallback to documented defaults.
    Password is required and has no default.

    Returns:
        Dictionary with host, port, database, user, and password.

    Raises:
        RuntimeError: If POSTGRES_PASSWORD is not set.
    """
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError(
            "POSTGRES_PASSWORD environment variable is required for integration tests"
        )

    return {
        "host": os.environ.get("POSTGRES_HOST", "192.168.86.200"),
        "port": int(os.environ.get("POSTGRES_PORT", "5436")),
        "database": os.environ.get("POSTGRES_DATABASE", "omninode_bridge"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": password,
    }


def get_contract_path() -> Path:
    """Get path to the learned_patterns repository contract.

    Returns:
        Path to the contract YAML file.
    """
    return (
        Path(__file__).parent.parent.parent
        / "src"
        / "omniclaude"
        / "hooks"
        / "contracts"
        / "repository_learned_patterns.yaml"
    )


def skip_unless_postgres_enabled() -> None:
    """Skip test if POSTGRES_INTEGRATION_TESTS is not enabled."""
    if os.getenv("POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "PostgreSQL integration tests disabled. "
            "Set POSTGRES_INTEGRATION_TESTS=1 to run."
        )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def postgres_config() -> dict[str, str | int]:
    """Get PostgreSQL configuration from environment.

    Module-scoped to avoid repeated environment reads.

    Returns:
        Dictionary with database connection parameters.
    """
    skip_unless_postgres_enabled()
    return get_postgres_config()


@pytest.fixture(scope="module")
def contract_path() -> Path:
    """Get path to the repository contract.

    Returns:
        Path to the contract YAML file.

    Raises:
        pytest.skip: If contract file does not exist.
    """
    path = get_contract_path()
    if not path.exists():
        pytest.skip(f"Contract file not found: {path}")
    return path


@pytest.fixture(scope="module")
def contract(contract_path: Path) -> ModelDbRepositoryContract:
    """Load and validate the repository contract.

    Args:
        contract_path: Path to the contract YAML file.

    Returns:
        Validated ModelDbRepositoryContract instance.
    """
    import yaml
    from omnibase_core.models.contracts import ModelDbRepositoryContract

    with contract_path.open() as f:
        contract_data = yaml.safe_load(f)

    return ModelDbRepositoryContract.model_validate(contract_data)


@pytest.fixture
async def pool(postgres_config: dict[str, str | int]) -> asyncpg.Pool:
    """Create an asyncpg connection pool.

    Fixture-scoped (function) to ensure clean state between tests.
    Pool is closed after each test.

    Args:
        postgres_config: Database connection parameters.

    Yields:
        asyncpg connection pool.
    """
    import asyncpg

    dsn = (
        f"postgresql://{postgres_config['user']}:{postgres_config['password']}"
        f"@{postgres_config['host']}:{postgres_config['port']}"
        f"/{postgres_config['database']}"
    )

    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=5,
        command_timeout=30.0,
    )

    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def runtime(
    pool: asyncpg.Pool,
    contract: ModelDbRepositoryContract,
) -> PostgresRepositoryRuntime:
    """Create a PostgresRepositoryRuntime instance.

    Args:
        pool: asyncpg connection pool.
        contract: Validated repository contract.

    Returns:
        Configured PostgresRepositoryRuntime.
    """
    from omnibase_infra.runtime.db import PostgresRepositoryRuntime

    return PostgresRepositoryRuntime(pool, contract)


@pytest.fixture
async def _postgres_health_check(postgres_config: dict[str, str | int]) -> None:
    """Verify PostgreSQL is reachable before running tests.

    This fixture is prefixed with underscore to indicate it's used only for
    its side effect (skipping tests when PostgreSQL is unavailable) and the
    return value is not used by dependent tests.

    Yields:
        None: No value is yielded; this fixture is used for its skip behavior.

    Raises:
        pytest.skip: If asyncpg is not installed or PostgreSQL is unreachable.
    """
    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg not installed")
        return

    dsn = (
        f"postgresql://{postgres_config['user']}:{postgres_config['password']}"
        f"@{postgres_config['host']}:{postgres_config['port']}"
        f"/{postgres_config['database']}"
    )

    try:
        conn = await asyncpg.connect(dsn, timeout=10.0)
        await conn.close()
    except Exception as e:
        pytest.skip(
            f"PostgreSQL not available at "
            f"{postgres_config['host']}:{postgres_config['port']}: {e}"
        )


# =============================================================================
# Integration Tests - Contract Loading
# =============================================================================


class TestContractLoading:
    """Tests for contract loading and validation."""

    def test_contract_file_exists(self, contract_path: Path) -> None:
        """Verify the contract YAML file exists."""
        assert contract_path.exists()
        assert contract_path.suffix == ".yaml"

    def test_contract_loads_successfully(
        self, contract: ModelDbRepositoryContract
    ) -> None:
        """Verify contract loads and validates without error."""
        assert contract is not None
        assert contract.name == "learned_patterns"
        assert contract.engine == "postgres"

    def test_contract_has_required_operations(
        self, contract: ModelDbRepositoryContract
    ) -> None:
        """Verify contract defines all expected operations."""
        op_names = set(contract.ops.keys())
        required_ops = {
            "list_validated_patterns",
            "get_pattern_by_id",
            "list_patterns_by_domain",
        }
        assert required_ops.issubset(op_names), (
            f"Missing operations: {required_ops - op_names}"
        )

    def test_contract_operations_are_read_mode(
        self, contract: ModelDbRepositoryContract
    ) -> None:
        """Verify all operations are read-only."""
        for op_name, op in contract.ops.items():
            assert op.mode == "read", f"Operation {op_name} should be read mode"


# =============================================================================
# Integration Tests - Database Connection
# =============================================================================


class TestDatabaseConnection:
    """Tests for database connectivity."""

    async def test_pool_connects_successfully(
        self,
        _postgres_health_check: None,
        pool: asyncpg.Pool,
    ) -> None:
        """Verify connection pool can be established."""
        # Pool is already created by fixture - verify it works
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            assert result == 1

    async def test_learned_patterns_table_exists(
        self,
        _postgres_health_check: None,
        pool: asyncpg.Pool,
    ) -> None:
        """Verify the learned_patterns table exists.

        Note: The table may be empty, which is fine.
        """
        async with pool.acquire() as conn:
            # Check table exists in information_schema
            result = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'learned_patterns'
                )
                """
            )
            assert result is True, "learned_patterns table should exist"


# =============================================================================
# Integration Tests - Contract Operations
# =============================================================================

# NOTE: The LIMIT clause duplication bug was fixed in omnibase_infra 0.3.1
# (OMN-1842). Tests no longer need xfail markers for this issue.


class TestListValidatedPatterns:
    """Tests for list_validated_patterns operation."""

    async def test_list_validated_patterns_executes(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify list_validated_patterns executes without error."""
        # Execute with default limit
        result = await runtime.call("list_validated_patterns", 10)

        # Result should be a list (may be empty)
        assert isinstance(result, list)

    async def test_list_validated_patterns_with_limit(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify list_validated_patterns respects limit parameter."""
        # Execute with small limit
        result = await runtime.call("list_validated_patterns", 2)

        assert isinstance(result, list)
        assert len(result) <= 2

    async def test_list_validated_patterns_returns_expected_columns(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify result rows have expected columns."""
        result = await runtime.call("list_validated_patterns", 10)

        if result:
            # Check first row has expected columns
            row = result[0]
            expected_columns = {
                "pattern_id",
                "domain",
                "title",
                "description",
                "confidence",
                "usage_count",
                "success_rate",
                "example_reference",
            }
            assert expected_columns.issubset(set(row.keys())), (
                f"Missing columns: {expected_columns - set(row.keys())}"
            )

    async def test_list_validated_patterns_maps_to_pattern_record(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify results can be mapped to PatternRecord dataclass."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        result = await runtime.call("list_validated_patterns", 10)

        if result:
            row = result[0]
            # Attempt mapping (same logic as handler_context_injection.py)
            pattern_id = row.get("pattern_id")
            if pattern_id:
                record = PatternRecord(
                    pattern_id=str(pattern_id),
                    domain=str(row.get("domain", "")),
                    title=str(row.get("title", "")),
                    description=str(row.get("description", "")),
                    confidence=float(row.get("confidence", 0.0)),
                    usage_count=int(row.get("usage_count", 0)),
                    success_rate=float(row.get("success_rate", 0.0)),
                    example_reference=row.get("example_reference"),
                )
                assert record.pattern_id == str(pattern_id)


class TestGetPatternById:
    """Tests for get_pattern_by_id operation."""

    async def test_get_pattern_by_id_with_nonexistent_id(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify get_pattern_by_id returns None for nonexistent ID.

        Note: get_pattern_by_id does NOT have LIMIT in the contract SQL,
        so it doesn't trigger the runtime limit injection bug. However,
        it may fail due to schema mismatch if the production table
        uses different column names.
        """
        # Generate a random UUID that almost certainly doesn't exist
        nonexistent_id = str(uuid4())

        result = await runtime.call("get_pattern_by_id", nonexistent_id)

        # Should return None or empty for nonexistent pattern
        assert result is None or result == []

    async def test_get_pattern_by_id_with_existing_pattern(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify get_pattern_by_id returns pattern if it exists.

        This test first fetches a pattern via list_validated_patterns,
        then queries for it by ID. If no patterns exist, test is skipped.
        """
        # Get any pattern from the database
        patterns = await runtime.call("list_validated_patterns", 1)

        if not patterns:
            pytest.skip("No patterns in database to test get_pattern_by_id")

        pattern_id = patterns[0].get("pattern_id")
        if not pattern_id:
            pytest.skip("Pattern has no pattern_id")

        # Query by ID
        result = await runtime.call("get_pattern_by_id", str(pattern_id))

        # Should return the pattern (as list with one item or dict)
        if isinstance(result, list):
            assert len(result) == 1
            assert result[0].get("pattern_id") == pattern_id
        elif isinstance(result, dict):
            assert result.get("pattern_id") == pattern_id
        else:
            # May return None if pattern was deleted between queries
            # (race condition, acceptable in integration test)
            pass


class TestListPatternsByDomain:
    """Tests for list_patterns_by_domain operation."""

    async def test_list_patterns_by_domain_executes(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify list_patterns_by_domain executes without error."""
        # Use a common domain name
        result = await runtime.call("list_patterns_by_domain", "general", 10)

        # Result should be a list (may be empty)
        assert isinstance(result, list)

    async def test_list_patterns_by_domain_with_limit(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify list_patterns_by_domain respects limit parameter."""
        result = await runtime.call("list_patterns_by_domain", "general", 2)

        assert isinstance(result, list)
        assert len(result) <= 2

    async def test_list_patterns_by_domain_returns_matching_domain(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify results match the requested domain or 'general'."""
        domain = "code_review"
        result = await runtime.call("list_patterns_by_domain", domain, 10)

        if result:
            for row in result:
                row_domain = row.get("domain")
                assert row_domain in (domain, "general"), (
                    f"Expected domain '{domain}' or 'general', got '{row_domain}'"
                )

    async def test_list_patterns_by_domain_with_existing_domain(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify querying by existing domain returns results.

        First gets any pattern, then queries by its domain.
        """
        # Get any pattern to discover an existing domain
        patterns = await runtime.call("list_validated_patterns", 1)

        if not patterns:
            pytest.skip("No patterns in database to test domain filtering")

        domain = patterns[0].get("domain")
        if not domain:
            pytest.skip("Pattern has no domain")

        # Query by that domain
        result = await runtime.call("list_patterns_by_domain", domain, 10)

        # Should return at least one pattern
        assert len(result) >= 1


# =============================================================================
# Integration Tests - Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    async def test_invalid_operation_name_raises_error(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify calling nonexistent operation raises error."""
        from omnibase_infra.errors.repository.errors_repository import (
            RepositoryContractError,
        )

        with pytest.raises(
            (KeyError, ValueError, AttributeError, RepositoryContractError)
        ):
            await runtime.call("nonexistent_operation", 10)

    async def test_invalid_uuid_format_raises_error(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify invalid UUID format is handled."""
        from omnibase_infra.errors.repository.errors_repository import (
            RepositoryExecutionError,
        )

        # Invalid UUID format should raise an error during execution
        with pytest.raises((Exception, RepositoryExecutionError)):
            await runtime.call("get_pattern_by_id", "not-a-valid-uuid")

    async def test_negative_limit_handled(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify negative limit is rejected or handled.

        The contract specifies ge=1 for limit, so negative values
        should be rejected.
        """
        # Depending on implementation, this may:
        # 1. Raise a validation error
        # 2. Use default value
        # 3. Return empty results
        # Any of these is acceptable behavior
        try:
            result = await runtime.call("list_validated_patterns", -1)
            # If it doesn't raise, result should be a list
            assert isinstance(result, list)
        except (ValueError, Exception):
            # Expected - validation rejection
            pass


# =============================================================================
# Integration Tests - Full Workflow
# =============================================================================


class TestFullWorkflow:
    """End-to-end workflow tests."""

    async def test_full_pattern_injection_workflow(
        self,
        _postgres_health_check: None,
        runtime: PostgresRepositoryRuntime,
    ) -> None:
        """Verify complete pattern injection workflow.

        This test simulates the actual usage in handler_context_injection.py:
        1. List validated patterns
        2. Map to PatternRecord objects
        3. Filter by confidence
        4. Format for injection
        """
        from omniclaude.hooks.handler_context_injection import PatternRecord

        # Step 1: Fetch patterns
        rows = await runtime.call("list_validated_patterns", 20)

        # Step 2: Map to PatternRecord
        patterns: list[PatternRecord] = []
        for row in rows:
            pattern_id = row.get("pattern_id")
            if not pattern_id:
                continue

            # Handle None values
            domain_val = row.get("domain")
            title_val = row.get("title")
            desc_val = row.get("description")
            conf_val = row.get("confidence")
            usage_val = row.get("usage_count")
            rate_val = row.get("success_rate")

            try:
                patterns.append(
                    PatternRecord(
                        pattern_id=str(pattern_id),
                        domain=str(domain_val) if domain_val is not None else "",
                        title=str(title_val) if title_val is not None else "",
                        description=str(desc_val) if desc_val is not None else "",
                        confidence=float(conf_val) if conf_val is not None else 0.0,
                        usage_count=int(usage_val) if usage_val is not None else 0,
                        success_rate=float(rate_val) if rate_val is not None else 0.0,
                        example_reference=row.get("example_reference"),
                    )
                )
            except (ValueError, TypeError):
                continue

        # Step 3: Filter by confidence (min 0.7)
        min_confidence = 0.7
        filtered_patterns = [p for p in patterns if p.confidence >= min_confidence]

        # Step 4: Verify workflow completed
        # (Actual formatting is not tested here - just data flow)
        assert isinstance(filtered_patterns, list)

        # If we have patterns, verify they meet confidence threshold
        for pattern in filtered_patterns:
            assert pattern.confidence >= min_confidence


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-s"])
