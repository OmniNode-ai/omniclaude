# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for DoD completion guard PreToolUse hook.

Validates that the hook correctly blocks/allows Linear status updates
based on evidence receipt presence, freshness, and check results.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOOK_SCRIPT = str(
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_dod_completion_guard.sh"
)


def _run_hook(
    tool_input: dict[str, object],
    env_overrides: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the completion guard hook with the given tool input."""
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home())}
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["bash", HOOK_SCRIPT],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=10,
        check=False,
    )


class TestAllowsNonCompletionUpdates:
    """Non-completion status updates should always be allowed."""

    def test_allows_non_completion_status_updates(self) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "In Progress"},
            }
        )
        assert result.returncode == 0

    def test_allows_non_linear_tool_calls(self) -> None:
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
            }
        )
        assert result.returncode == 0


class TestBlocksDoneWithoutReceipt:
    """Completion without evidence should be handled per policy mode."""

    def test_blocks_done_without_evidence_receipt_hard_mode(
        self, tmp_path: Path
    ) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "hard"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 2

    def test_allows_done_without_receipt_advisory_mode(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "advisory"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 0


class TestAllowsDoneWithValidReceipt:
    """Completion with valid, fresh receipt should be allowed."""

    def test_allows_done_with_valid_receipt(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / ".evidence" / "OMN-1234"
        evidence_dir.mkdir(parents=True)
        receipt = {
            "ticket_id": "OMN-1234",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "result": {"total": 2, "verified": 2, "failed": 0, "skipped": 0},
        }
        (evidence_dir / "dod_report.json").write_text(json.dumps(receipt))

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "hard"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 0


class TestBlocksDoneWithStaleReceipt:
    """Stale receipts should trigger policy enforcement."""

    def test_blocks_done_with_stale_receipt_hard_mode(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / ".evidence" / "OMN-1234"
        evidence_dir.mkdir(parents=True)
        stale_time = datetime.now(tz=UTC) - timedelta(hours=1)
        receipt = {
            "ticket_id": "OMN-1234",
            "timestamp": stale_time.isoformat(),
            "result": {"total": 1, "verified": 1, "failed": 0, "skipped": 0},
        }
        (evidence_dir / "dod_report.json").write_text(json.dumps(receipt))

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "hard"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 2


class TestBlocksDoneWithFailedChecks:
    """Receipt with failures should trigger policy enforcement."""

    def test_blocks_done_with_failed_checks_hard_mode(self, tmp_path: Path) -> None:
        evidence_dir = tmp_path / ".evidence" / "OMN-1234"
        evidence_dir.mkdir(parents=True)
        receipt = {
            "ticket_id": "OMN-1234",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "result": {"total": 2, "verified": 1, "failed": 1, "skipped": 0},
        }
        (evidence_dir / "dod_report.json").write_text(json.dumps(receipt))

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "hard"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 2


class TestAllowsDoneWhenNoContractExists:
    """Legacy tickets without contracts should be allowed through."""

    def test_allows_done_when_no_contract_exists(self, tmp_path: Path) -> None:
        # No .evidence directory at all
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-LEGACY", "state": "Done"},
            },
            env_overrides={"DOD_ENFORCEMENT_MODE": "advisory"},
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
