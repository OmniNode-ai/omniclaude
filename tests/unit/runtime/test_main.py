# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for omniclaude.runtime.__main__

Tests the --dry-run validation checklist:
    1. Dry-run success: exits 0, prints expected lines
    2. Missing KAFKA_BOOTSTRAP_SERVERS: exits 1 with clear error
    3. Missing OMNICLAUDE_CONTRACTS_ROOT: exits 1 with clear error
    4. Contract parse failure threshold (< 80%): exits 1

Ticket: OMN-2801
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.runtime.__main__ import _check_contracts, _check_route_matcher, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contracts(tmp_path: Path, total: int, valid: int) -> Path:
    """Create contract.yaml files under tmp_path/nodes.

    Creates ``valid`` parseable contracts and ``total - valid`` unparseable ones.
    """
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    for i in range(valid):
        node_dir = nodes_dir / f"node_valid_{i}"
        node_dir.mkdir()
        (node_dir / "contract.yaml").write_text(
            f"name: node_valid_{i}\ncontract_name: node_valid_{i}\n"
        )
    for i in range(total - valid):
        node_dir = nodes_dir / f"node_broken_{i}"
        node_dir.mkdir()
        # Write broken YAML (invalid syntax)
        (node_dir / "contract.yaml").write_text("name: [unclosed bracket\n")
    return nodes_dir


def _make_valid_contracts(tmp_path: Path, count: int) -> Path:
    """Create ``count`` valid contract.yaml files."""
    return _make_contracts(tmp_path, total=count, valid=count)


# ---------------------------------------------------------------------------
# Route matcher
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRouteMatcher:
    """Route matcher validates canonical omniclaude topic pattern."""

    def test_route_matcher_ok(self) -> None:
        """Route matcher returns True for canonical topic."""
        ok, msg = _check_route_matcher()
        assert ok is True
        assert "OK" in msg
        assert "onex.cmd.omniclaude.onex-status.v1" in msg


# ---------------------------------------------------------------------------
# Contract parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckContracts:
    """Contract parsing threshold validation."""

    def test_all_valid_contracts_passes(self, tmp_path: Path) -> None:
        """10/10 valid contracts: ok=True."""
        nodes_dir = _make_valid_contracts(tmp_path, 10)
        ok, msg, parsed, total = _check_contracts(str(nodes_dir))
        assert ok is True
        assert parsed == 10
        assert total == 10

    def test_below_threshold_fails(self, tmp_path: Path) -> None:
        """7/10 valid contracts (70%) is below the 80% threshold: ok=False."""
        nodes_dir = _make_contracts(tmp_path, total=10, valid=7)
        ok, msg, parsed, total = _check_contracts(str(nodes_dir))
        assert ok is False
        assert parsed == 7
        assert total == 10

    def test_exactly_at_threshold_passes(self, tmp_path: Path) -> None:
        """8/10 valid contracts (80%) is exactly at threshold: ok=True."""
        nodes_dir = _make_contracts(tmp_path, total=10, valid=8)
        ok, msg, parsed, total = _check_contracts(str(nodes_dir))
        assert ok is True
        assert parsed == 8
        assert total == 10

    def test_nonexistent_dir_fails(self, tmp_path: Path) -> None:
        """Nonexistent OMNICLAUDE_CONTRACTS_ROOT returns ok=False."""
        missing = tmp_path / "does_not_exist"
        ok, msg, parsed, total = _check_contracts(str(missing))
        assert ok is False
        assert parsed == 0

    def test_empty_dir_fails(self, tmp_path: Path) -> None:
        """Empty contracts directory (no contract.yaml files): ok=False."""
        empty = tmp_path / "empty"
        empty.mkdir()
        ok, msg, parsed, total = _check_contracts(str(empty))
        assert ok is False


# ---------------------------------------------------------------------------
# Full dry-run via main()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunSuccess:
    """Dry-run exits 0 when all required checks pass."""

    def test_dry_run_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exits 0 with expected output lines when environment is valid."""
        nodes_dir = _make_valid_contracts(tmp_path, 5)
        env = {
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:29092",
            "OMNICLAUDE_CONTRACTS_ROOT": str(nodes_dir),
        }
        with patch.dict(os.environ, env, clear=False):
            rc = main(["start", "--dry-run"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "Route matcher: OK" in out
        assert "Contracts:" in out
        assert "OK" in out
        assert "Backends:" in out
        assert "Note: contract cache is static" in out


@pytest.mark.unit
class TestDryRunMissingKafka:
    """Dry-run exits 1 when KAFKA_BOOTSTRAP_SERVERS is missing."""

    def test_missing_kafka_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exits 1 with clear error when KAFKA_BOOTSTRAP_SERVERS is unset."""
        nodes_dir = _make_valid_contracts(tmp_path, 5)
        env_patch = {
            "OMNICLAUDE_CONTRACTS_ROOT": str(nodes_dir),
        }
        # Remove KAFKA_BOOTSTRAP_SERVERS from env if present
        with patch.dict(os.environ, env_patch, clear=False):
            os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)
            rc = main(["start", "--dry-run"])

        assert rc == 1
        err = capsys.readouterr().err
        assert "KAFKA_BOOTSTRAP_SERVERS" in err


@pytest.mark.unit
class TestDryRunMissingContractsRoot:
    """Dry-run exits 1 when OMNICLAUDE_CONTRACTS_ROOT is missing."""

    def test_missing_contracts_root_exits_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exits 1 with clear error when OMNICLAUDE_CONTRACTS_ROOT is unset."""
        with patch.dict(
            os.environ, {"KAFKA_BOOTSTRAP_SERVERS": "localhost:29092"}, clear=False
        ):
            os.environ.pop("OMNICLAUDE_CONTRACTS_ROOT", None)
            rc = main(["start", "--dry-run"])

        assert rc == 1
        err = capsys.readouterr().err
        assert "OMNICLAUDE_CONTRACTS_ROOT" in err


@pytest.mark.unit
class TestDryRunContractThreshold:
    """Dry-run exits 1 when contract parse failure rate exceeds threshold."""

    def test_below_threshold_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exits 1 when fewer than 80% of contracts are parseable."""
        # 7/10 = 70% < 80% threshold
        nodes_dir = _make_contracts(tmp_path, total=10, valid=7)
        env = {
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:29092",
            "OMNICLAUDE_CONTRACTS_ROOT": str(nodes_dir),
        }
        with patch.dict(os.environ, env, clear=False):
            rc = main(["start", "--dry-run"])

        assert rc == 1
        err = capsys.readouterr().err
        assert "Contracts" in err
