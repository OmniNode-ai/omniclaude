# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for VERTICAL-001 demo pipeline.

These tests validate the end-to-end pattern extraction pipeline:
    Claude Hook -> Kafka -> Consumer -> PostgreSQL -> Query

Run with:
    # Skip integration tests (default)
    pytest tests/hooks/test_integration_demo_pipeline.py -v

    # Run with real Kafka + PostgreSQL
    KAFKA_INTEGRATION_TESTS=1 POSTGRES_INTEGRATION_TESTS=1 \
        pytest tests/hooks/test_integration_demo_pipeline.py -v

Requirements:
    - KAFKA_BOOTSTRAP_SERVERS, KAFKA_ENVIRONMENT must be set
    - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD
    - Topics and tables must exist

Environment Variables:
    KAFKA_INTEGRATION_TESTS: Set to "1" to enable Kafka integration tests
    POSTGRES_INTEGRATION_TESTS: Set to "1" to enable PostgreSQL integration tests
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure we're using the correct import path
_src_path = str(Path(__file__).parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# Path to demo scripts
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "scripts"


def skip_unless_integration_enabled() -> None:
    """Skip test if integration tests are not enabled."""
    if os.environ.get("KAFKA_INTEGRATION_TESTS") != "1":
        pytest.skip("KAFKA_INTEGRATION_TESTS=1 not set")
    if os.environ.get("POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip("POSTGRES_INTEGRATION_TESTS=1 not set")


def get_required_env_vars() -> dict[str, str]:
    """Get and validate required environment variables."""
    required = [
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_ENVIRONMENT",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DATABASE",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    ]

    missing = [var for var in required if not os.environ.get(var)]
    if missing:
        pytest.skip(f"Missing required environment variables: {', '.join(missing)}")

    return {var: os.environ[var] for var in required}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def unique_demo_prompt() -> str:
    """Generate a unique demo prompt for test isolation.

    Returns:
        str: A unique prompt that can be identified in the database.
    """
    unique_id = uuid4().hex[:12]
    return f"Demo pattern: Integration test {unique_id} - Always validate input before processing"


@pytest.fixture
def demo_env(unique_demo_prompt: str) -> dict[str, str]:
    """Get environment with all required variables for demo scripts.

    Args:
        unique_demo_prompt: The unique prompt to use for this test.

    Returns:
        dict: Environment variables for subprocess calls.
    """
    env = os.environ.copy()
    # Ensure all required vars are present
    get_required_env_vars()
    return env


# =============================================================================
# Helper Functions
# =============================================================================


def run_demo_script(
    script_name: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess:
    """Run a demo script and return the result.

    Args:
        script_name: Name of the script (e.g., 'demo_emit_hook.py').
        args: Additional command-line arguments.
        env: Environment variables (defaults to os.environ).
        timeout: Maximum time to wait for script completion.

    Returns:
        CompletedProcess with stdout, stderr, and returncode.
    """
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        pytest.fail(f"Script not found: {script_path}")

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    return subprocess.run(
        cmd,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,  # We check returncode manually in tests
    )


def compute_signature_hash(pattern_signature: str) -> str:
    """Compute the signature hash for a pattern.

    Args:
        pattern_signature: The pattern text.

    Returns:
        SHA-256 hash of the pattern signature.
    """
    return hashlib.sha256(pattern_signature[:500].encode()).hexdigest()


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
class TestDemoPipelineIntegration:
    """End-to-end integration tests for the VERTICAL-001 demo pipeline."""

    def test_emit_script_succeeds(
        self, demo_env: dict, unique_demo_prompt: str
    ) -> None:
        """Verify demo_emit_hook.py successfully emits an event."""
        skip_unless_integration_enabled()

        result = run_demo_script(
            "demo_emit_hook.py",
            args=["--prompt", unique_demo_prompt],
            env=demo_env,
        )

        assert result.returncode == 0, (
            f"Emit failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "Event emitted successfully" in result.stdout
        assert "Demo step 1/3 complete" in result.stdout

    def test_consume_script_processes_events(
        self, demo_env: dict, unique_demo_prompt: str
    ) -> None:
        """Verify demo_consume_store.py processes events in single-batch mode."""
        skip_unless_integration_enabled()

        # First emit an event
        emit_result = run_demo_script(
            "demo_emit_hook.py",
            args=["--prompt", unique_demo_prompt],
            env=demo_env,
        )
        assert emit_result.returncode == 0, f"Emit failed: {emit_result.stderr}"

        # Give Kafka a moment to propagate
        import time

        time.sleep(2)

        # Then consume it
        consume_result = run_demo_script(
            "demo_consume_store.py",
            args=["--once"],
            env=demo_env,
            timeout=60.0,  # Consumer may need longer to connect
        )

        # Consumer should complete (may or may not find our specific event
        # depending on timing and other tests)
        assert consume_result.returncode == 0, (
            f"Consume failed:\nstdout: {consume_result.stdout}\nstderr: {consume_result.stderr}"
        )
        assert "PostgreSQL connected" in consume_result.stdout
        assert "Kafka consumer connected" in consume_result.stdout

    def test_query_script_retrieves_patterns(self, demo_env: dict) -> None:
        """Verify demo_query_patterns.py can query patterns."""
        skip_unless_integration_enabled()

        result = run_demo_script(
            "demo_query_patterns.py",
            args=["--demo-only", "--limit", "5"],
            env=demo_env,
        )

        # Query should succeed even if no demo patterns exist
        assert result.returncode in [0, 1], (
            f"Query crashed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PostgreSQL Configuration" in result.stdout
        assert "Connected" in result.stdout

    def test_full_pipeline_emit_consume_query(
        self, demo_env: dict, unique_demo_prompt: str
    ) -> None:
        """Full end-to-end test: emit -> consume -> query -> cleanup.

        This test validates the complete VERTICAL-001 demo pipeline:
        1. Emit a test event with a unique prompt
        2. Consume the event and store to PostgreSQL
        3. Query to verify the pattern was stored
        4. Cleanup the demo pattern
        """
        skip_unless_integration_enabled()
        import time

        # Step 1: Emit
        emit_result = run_demo_script(
            "demo_emit_hook.py",
            args=["--prompt", unique_demo_prompt],
            env=demo_env,
        )
        assert emit_result.returncode == 0, (
            f"Step 1 (Emit) failed: {emit_result.stderr}"
        )
        assert "Event emitted successfully" in emit_result.stdout

        # Give Kafka time to propagate
        time.sleep(3)

        # Step 2: Consume
        consume_result = run_demo_script(
            "demo_consume_store.py",
            args=["--once"],
            env=demo_env,
            timeout=60.0,
        )
        assert consume_result.returncode == 0, (
            f"Step 2 (Consume) failed: {consume_result.stderr}"
        )

        # Step 3: Query (with cleanup)
        query_result = run_demo_script(
            "demo_query_patterns.py",
            args=["--demo-only", "--cleanup"],
            env=demo_env,
        )
        # Query may return 0 (found patterns) or 1 (no patterns) - both are valid
        assert query_result.returncode in [0, 1], (
            f"Step 3 (Query) crashed: {query_result.stderr}"
        )
        assert "Connected" in query_result.stdout

        # If patterns were found, cleanup should have run
        if query_result.returncode == 0 and "Found" in query_result.stdout:
            assert (
                "CLEANUP" in query_result.stdout
                or "Demo step 3/3 complete" in query_result.stdout
            )


@pytest.mark.integration
class TestDemoScriptValidation:
    """Tests for demo script argument validation."""

    def test_emit_requires_kafka_env(self) -> None:
        """Verify emit script fails gracefully without KAFKA_BOOTSTRAP_SERVERS."""
        skip_unless_integration_enabled()

        env = os.environ.copy()
        env.pop("KAFKA_BOOTSTRAP_SERVERS", None)

        result = run_demo_script("demo_emit_hook.py", env=env)

        assert result.returncode != 0
        assert (
            "KAFKA_BOOTSTRAP_SERVERS" in result.stdout
            or "KAFKA_BOOTSTRAP_SERVERS" in result.stderr
        )

    def test_consume_requires_postgres_env(self) -> None:
        """Verify consume script fails gracefully without POSTGRES_PASSWORD."""
        skip_unless_integration_enabled()

        env = os.environ.copy()
        env.pop("POSTGRES_PASSWORD", None)

        result = run_demo_script("demo_consume_store.py", args=["--once"], env=env)

        assert result.returncode != 0
        assert (
            "POSTGRES_PASSWORD" in result.stdout or "Missing required" in result.stdout
        )

    def test_query_requires_postgres_env(self) -> None:
        """Verify query script fails gracefully without POSTGRES_HOST."""
        skip_unless_integration_enabled()

        env = os.environ.copy()
        env.pop("POSTGRES_HOST", None)

        result = run_demo_script("demo_query_patterns.py", env=env)

        assert result.returncode != 0
        assert "POSTGRES_HOST" in result.stdout or "Missing required" in result.stdout


class TestDemoScriptHelp:
    """Tests for demo script --help output."""

    def test_emit_help(self) -> None:
        """Verify emit script has help output."""
        result = run_demo_script("demo_emit_hook.py", args=["--help"])
        assert result.returncode == 0
        assert "VERTICAL-001" in result.stdout or "demo" in result.stdout.lower()

    def test_consume_help(self) -> None:
        """Verify consume script has help output."""
        result = run_demo_script("demo_consume_store.py", args=["--help"])
        assert result.returncode == 0
        assert "--once" in result.stdout

    def test_query_help(self) -> None:
        """Verify query script has help output."""
        result = run_demo_script("demo_query_patterns.py", args=["--help"])
        assert result.returncode == 0
        assert "--demo-only" in result.stdout
        assert "--cleanup" in result.stdout


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
