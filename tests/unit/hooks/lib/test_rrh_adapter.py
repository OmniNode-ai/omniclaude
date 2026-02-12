"""Tests for the RRH skill adapter (rrh_adapter.py).

Validates the A1 -> A2 -> A3 pipeline orchestration, fallback behavior,
timing, and custom client injection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Insert skill directory so bare-name imports resolve.
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "skills"
        / "rrh"
    ),
)

from omnibase_spi.contracts.pipeline.contract_rrh_result import ContractRRHResult
from omnibase_spi.contracts.shared.contract_check_result import ContractCheckResult
from omnibase_spi.contracts.shared.contract_verdict import ContractVerdict
from rrh_adapter import (
    FallbackNodeClient,
    RRHAdapter,
    RRHGovernance,
    RRHRunConfig,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEFAULT_GOVERNANCE = RRHGovernance(ticket_id="OMN-0001")


def _make_config(tmp_path: Path) -> RRHRunConfig:
    return RRHRunConfig(
        repo_path=tmp_path,
        profile_name="ticket-pipeline",
        governance=_DEFAULT_GOVERNANCE,
        output_dir=tmp_path / "artifacts",
    )


def _make_result(
    *,
    run_id: str = "test-run-001",
    status: str = "PASS",
    duration_ms: float | None = None,
) -> ContractRRHResult:
    return ContractRRHResult(
        run_id=run_id,
        checks=[
            ContractCheckResult(
                check_id="RRH-1001",
                domain="rrh",
                status="pass",
                severity="minor",
                message="All clear",
            ),
        ],
        verdict=ContractVerdict(
            status=status,
            score=100 if status == "PASS" else 0,
            block_reasons=[] if status == "PASS" else ["something failed"],
            human_summary=f"Verdict: {status}",
        ),
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Spy node client for verifying orchestration
# ---------------------------------------------------------------------------


class SpyNodeClient:
    """Records all calls for assertion."""

    def __init__(
        self,
        env_data: dict[str, Any] | None = None,
        result: ContractRRHResult | None = None,
        artifact_path: Path | None = None,
    ) -> None:
        self.env_data = env_data or {"git_branch": "main"}
        self.result = result or _make_result()
        self.artifact_path = artifact_path or Path("/tmp/rrh.json")  # noqa: S108

        self.collect_calls: list[Path] = []
        self.validate_calls: list[tuple[dict, str, RRHGovernance]] = []
        self.store_calls: list[tuple[ContractRRHResult, Path]] = []

    def collect_environment(self, repo_path: Path) -> dict[str, Any]:
        self.collect_calls.append(repo_path)
        return self.env_data

    def validate(
        self,
        environment_data: dict[str, Any],
        profile_name: str,
        governance: RRHGovernance,
    ) -> ContractRRHResult:
        self.validate_calls.append((environment_data, profile_name, governance))
        return self.result

    def store_result(self, result: ContractRRHResult, output_dir: Path) -> Path:
        self.store_calls.append((result, output_dir))
        return self.artifact_path


# ---------------------------------------------------------------------------
# Tests: A1 -> A2 -> A3 orchestration
# ---------------------------------------------------------------------------


class TestRRHAdapterOrchestration:
    """Test that RRHAdapter.run calls A1, A2, A3 in order."""

    def test_full_pipeline_calls_all_stages(self, tmp_path: Path) -> None:
        spy = SpyNodeClient()
        adapter = RRHAdapter(node_client=spy)
        config = _make_config(tmp_path)

        adapter.run(config)

        assert len(spy.collect_calls) == 1
        assert spy.collect_calls[0] == tmp_path

        assert len(spy.validate_calls) == 1
        env_data, profile, governance = spy.validate_calls[0]
        assert env_data == {"git_branch": "main"}
        assert profile == "ticket-pipeline"
        assert governance is _DEFAULT_GOVERNANCE

        assert len(spy.store_calls) == 1
        stored_result, stored_dir = spy.store_calls[0]
        assert stored_result.run_id == "test-run-001"
        assert stored_dir == tmp_path / "artifacts"

    def test_env_data_flows_to_validate(self, tmp_path: Path) -> None:
        custom_env = {"git_branch": "feat/rrh", "python": "3.12"}
        spy = SpyNodeClient(env_data=custom_env)
        adapter = RRHAdapter(node_client=spy)

        adapter.run(_make_config(tmp_path))

        env_data, _, _ = spy.validate_calls[0]
        assert env_data == custom_env

    def test_result_returned_from_run(self, tmp_path: Path) -> None:
        expected = _make_result(run_id="expected-run")
        spy = SpyNodeClient(result=expected)
        adapter = RRHAdapter(node_client=spy)

        result = adapter.run(_make_config(tmp_path))

        assert result.run_id == "expected-run"
        assert result.verdict.status == "PASS"


# ---------------------------------------------------------------------------
# Tests: Timing
# ---------------------------------------------------------------------------


class TestRRHAdapterTiming:
    """Test that duration_ms is populated when not set by the client."""

    def test_duration_ms_populated_when_none(self, tmp_path: Path) -> None:
        spy = SpyNodeClient(result=_make_result(duration_ms=None))
        adapter = RRHAdapter(node_client=spy)

        result = adapter.run(_make_config(tmp_path))

        assert result.duration_ms is not None
        assert result.duration_ms > 0

    def test_duration_ms_preserved_when_set(self, tmp_path: Path) -> None:
        spy = SpyNodeClient(result=_make_result(duration_ms=42.5))
        adapter = RRHAdapter(node_client=spy)

        result = adapter.run(_make_config(tmp_path))

        # When client already set duration, adapter should keep it.
        assert result.duration_ms == 42.5


# ---------------------------------------------------------------------------
# Tests: Fallback client
# ---------------------------------------------------------------------------


class TestFallbackNodeClient:
    """Test the built-in fallback when ONEX nodes are unavailable."""

    def test_collect_returns_fallback_marker(self, tmp_path: Path) -> None:
        client = FallbackNodeClient()
        data = client.collect_environment(tmp_path)

        assert data["_fallback"] is True
        assert data["repo_path"] == str(tmp_path)

    def test_validate_returns_quarantine(self) -> None:
        client = FallbackNodeClient()
        result = client.validate({}, "default", _DEFAULT_GOVERNANCE)

        assert result.verdict.status == "QUARANTINE"
        assert result.verdict.score == 0
        assert len(result.checks) == 1
        assert result.checks[0].check_id == "RRH-0000"
        assert result.checks[0].status == "skip"
        assert "not available" in result.checks[0].message

    def test_validate_run_id_has_fallback_prefix(self) -> None:
        client = FallbackNodeClient()
        result = client.validate({}, "default", _DEFAULT_GOVERNANCE)

        assert result.run_id.startswith("fallback-")

    def test_store_returns_fallback_path(self, tmp_path: Path) -> None:
        client = FallbackNodeClient()
        result = _make_result()
        path = client.store_result(result, tmp_path)

        assert path == tmp_path / "rrh_fallback.json"


# ---------------------------------------------------------------------------
# Tests: Custom client injection
# ---------------------------------------------------------------------------


class TestRRHAdapterCustomClient:
    """Test that a custom node client can be injected via constructor."""

    def test_custom_client_used(self, tmp_path: Path) -> None:
        custom_result = _make_result(run_id="custom-client-run", status="FAIL")
        spy = SpyNodeClient(result=custom_result)
        adapter = RRHAdapter(node_client=spy)

        result = adapter.run(_make_config(tmp_path))

        assert result.run_id == "custom-client-run"
        assert result.verdict.status == "FAIL"

    def test_default_client_is_fallback(self) -> None:
        """When no client given, adapter resolves to fallback (in test env)."""
        adapter = RRHAdapter()
        # The resolved client should be FallbackNodeClient since
        # omnibase_infra nodes are not installed in the test environment.
        assert isinstance(adapter._client, FallbackNodeClient)
