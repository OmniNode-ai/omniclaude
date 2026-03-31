# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Integration tests for the DoD enforcement chain. [OMN-7092]

Proves the full DoD completion guard → evidence receipt → policy decision chain
by invoking the real shell script (pre_tool_use_dod_completion_guard.sh) with
controlled inputs and asserting exit codes and stderr output.

The guard script:
- Reads JSON from stdin describing a Linear tool invocation
- Checks for a DoD evidence receipt at .evidence/<ticket_id>/dod_report.json
- Applies policy based on DOD_ENFORCEMENT_MODE (advisory / soft / hard)
- Exits 0 (allow) or 2 (block, hard mode only)

These tests do NOT require Kafka, Postgres, or any external services.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_dod_completion_guard.sh"
)
_TICKET_ID = "OMN-TEST-9999"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_linear_done_input(ticket_id: str = _TICKET_ID) -> str:
    """Build stdin JSON that mimics a Linear save_issue call setting status to Done."""
    return json.dumps(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {
                "id": ticket_id,
                "state": "Done",
            },
        }
    )


def _make_non_linear_input() -> str:
    """Build stdin JSON for a non-Linear tool call (should always be allowed)."""
    return json.dumps(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/foo.txt"},
        }
    )


def _write_receipt(
    evidence_dir: Path,
    *,
    failed: int = 0,
    verified: int = 3,
    timestamp: str | None = None,
    raw_content: str | None = None,
) -> Path:
    """Write a DoD evidence receipt to the expected location.

    Args:
        evidence_dir: The .evidence/<ticket_id>/ directory.
        failed: Number of failed checks.
        verified: Number of verified checks.
        timestamp: ISO timestamp (defaults to now).
        raw_content: If provided, write this verbatim instead of generating JSON.

    Returns:
        Path to the written receipt file.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence_dir / "dod_report.json"

    if raw_content is not None:
        receipt_path.write_text(raw_content)
        return receipt_path

    if timestamp is None:
        timestamp = datetime.now(tz=UTC).isoformat()

    receipt = {
        "ticket_id": _TICKET_ID,
        "timestamp": timestamp,
        "git_sha": "abc123",
        "branch": "test-branch",
        "working_dir": str(evidence_dir.parent.parent),
        "contract_path": "contract.yaml",
        "result": {
            "total": verified + failed,
            "verified": verified,
            "failed": failed,
            "skipped": 0,
            "details": [],
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2))
    return receipt_path


def _run_guard(
    stdin_data: str,
    cwd: str,
    *,
    enforcement_mode: str = "hard",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the guard script and return the completed process.

    Sets up the minimal environment needed for the script to run:
    - PLUGIN_PYTHON_BIN: points to the system python3
    - ONEX_STATE_DIR: temp directory for logs
    - DOD_ENFORCEMENT_MODE: the enforcement policy
    - OMNICLAUDE_MODE: set to 'full' to avoid lite-mode early exit
    - CLAUDE_PLUGIN_ROOT: set to the plugin directory
    """
    env = os.environ.copy()
    # Find python3 for the script's embedded python calls
    python_bin = shutil.which("python3") or "/usr/bin/python3"
    env["PLUGIN_PYTHON_BIN"] = python_bin
    env["ONEX_STATE_DIR"] = os.path.join(cwd, ".onex_state")
    env["DOD_ENFORCEMENT_MODE"] = enforcement_mode
    env["OMNICLAUDE_MODE"] = "full"
    env["CLAUDE_PLUGIN_ROOT"] = str(_REPO_ROOT / "plugins" / "onex")
    # Prevent emit_client_wrapper from trying to connect to Kafka
    env.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    if extra_env:
        env.update(extra_env)

    # Ensure ONEX_STATE_DIR/logs exists for the hook log
    os.makedirs(os.path.join(cwd, ".onex_state", "logs"), exist_ok=True)

    return subprocess.run(
        ["bash", str(_GUARD_SCRIPT)],
        input=stdin_data,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=15,
        check=False,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Create a temporary working directory for guard tests."""
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDoDCompletionGuardHardMode:
    """Tests for the DoD completion guard in hard enforcement mode."""

    def test_guard_blocks_without_receipt(self, work_dir: Path) -> None:
        """Hard mode blocks Done status when no evidence receipt exists."""
        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (block), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "block" in result.stderr.lower()

    def test_guard_allows_with_clean_receipt(self, work_dir: Path) -> None:
        """Hard mode allows Done status when receipt exists, is fresh, and has 0 failures."""
        evidence_dir = work_dir / ".evidence" / _TICKET_ID
        _write_receipt(evidence_dir, failed=0, verified=3)

        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (allow), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_guard_blocks_with_failed_receipt(self, work_dir: Path) -> None:
        """Hard mode blocks Done status when receipt has failed checks."""
        evidence_dir = work_dir / ".evidence" / _TICKET_ID
        _write_receipt(evidence_dir, failed=2, verified=1)

        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (block), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "fail" in result.stderr.lower()

    def test_guard_rejects_malformed_receipt(self, work_dir: Path) -> None:
        """Hard mode blocks when receipt file contains invalid JSON."""
        evidence_dir = work_dir / ".evidence" / _TICKET_ID
        _write_receipt(evidence_dir, raw_content="not valid json {{{")

        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (block for malformed receipt), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_guard_rejects_stale_receipt(self, work_dir: Path) -> None:
        """Hard mode blocks when receipt is older than 30 minutes."""
        evidence_dir = work_dir / ".evidence" / _TICKET_ID
        stale_ts = (datetime.now(tz=UTC) - timedelta(minutes=45)).isoformat()
        _write_receipt(evidence_dir, failed=0, verified=3, timestamp=stale_ts)

        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (block for stale receipt), got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "stale" in result.stderr.lower()


@pytest.mark.integration
class TestDoDCompletionGuardPolicyModes:
    """Tests verifying advisory and soft modes allow the tool call."""

    def test_advisory_allows_without_receipt(self, work_dir: Path) -> None:
        """Advisory mode allows Done status even without receipt (exit 0)."""
        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="advisory",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (advisory allows), got {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )

    def test_soft_allows_without_receipt(self, work_dir: Path) -> None:
        """Soft mode allows Done status even without receipt (exit 0, with warning)."""
        result = _run_guard(
            _make_linear_done_input(),
            str(work_dir),
            enforcement_mode="soft",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 (soft allows), got {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
        assert "warning" in result.stderr.lower()


@pytest.mark.integration
class TestDoDCompletionGuardBypass:
    """Tests verifying the guard passes through non-completion tool calls."""

    def test_non_linear_tool_always_allowed(self, work_dir: Path) -> None:
        """Non-Linear tool calls always pass through (exit 0)."""
        result = _run_guard(
            _make_non_linear_input(),
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for non-Linear tool, got {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )

    def test_non_completion_status_allowed(self, work_dir: Path) -> None:
        """Linear tool call with non-completion status always passes (exit 0)."""
        input_data = json.dumps(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {
                    "id": _TICKET_ID,
                    "state": "In Progress",
                },
            }
        )
        result = _run_guard(
            input_data,
            str(work_dir),
            enforcement_mode="hard",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for non-completion status, got {result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
