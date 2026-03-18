# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for DoD evidence runner — check execution and receipt generation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the skill lib to path
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "onex"
        / "skills"
        / "_lib"
        / "dod-evidence-runner"
    ),
)

from dod_evidence_runner import (
    EvidenceRunResult,
    emit_dod_verify_completed,
    run_dod_evidence,
    write_evidence_receipt,
)


class TestTestExistsCheck:
    """Tests for test_exists check type."""

    def test_test_exists_passes_when_test_file_exists(self, tmp_path: Path) -> None:
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_example.py").write_text("def test_one(): pass")

        items = [
            {
                "id": "dod-001",
                "description": "Tests exist",
                "checks": [
                    {"check_type": "test_exists", "check_value": str(test_dir)},
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.verified == 1
        assert result.failed == 0

    def test_test_exists_fails_when_missing(self, tmp_path: Path) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Tests exist",
                "checks": [
                    {
                        "check_type": "test_exists",
                        "check_value": str(tmp_path / "nonexistent"),
                    },
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.failed == 1


class TestTestPassesCheck:
    """Tests for test_passes check type."""

    def test_test_passes_runs_command(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Tests pass",
                "checks": [
                    {"check_type": "test_passes", "check_value": "true"},
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.verified == 1

    def test_test_passes_fails_on_exit_1(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Tests pass",
                "checks": [
                    {"check_type": "test_passes", "check_value": "false"},
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.failed == 1


class TestFileExistsCheck:
    """Tests for file_exists check type."""

    def test_file_exists_glob_match(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("key: value")
        items = [
            {
                "id": "dod-001",
                "description": "Config exists",
                "checks": [
                    {
                        "check_type": "file_exists",
                        "check_value": str(tmp_path / "*.yaml"),
                    },
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.verified == 1

    def test_file_exists_fails_when_missing(self, tmp_path: Path) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Config exists",
                "checks": [
                    {
                        "check_type": "file_exists",
                        "check_value": str(tmp_path / "*.nonexistent"),
                    },
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.failed == 1


class TestGrepCheck:
    """Tests for grep check type."""

    def test_grep_finds_pattern(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("class ModelDodCheck:\n    pass\n")
        items = [
            {
                "id": "dod-001",
                "description": "Pattern found",
                "checks": [
                    {
                        "check_type": "grep",
                        "check_value": {
                            "pattern": "class ModelDodCheck",
                            "path": str(src),
                        },
                    },
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.verified == 1

    def test_grep_missing_pattern(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("nothing here\n")
        items = [
            {
                "id": "dod-001",
                "description": "Pattern found",
                "checks": [
                    {
                        "check_type": "grep",
                        "check_value": {
                            "pattern": "NONEXISTENT_PATTERN_XYZ",
                            "path": str(src),
                        },
                    },
                ],
            }
        ]
        result = run_dod_evidence(items)
        assert result.failed == 1


class TestCommandCheck:
    """Tests for command check type."""

    def test_command_exit_0_is_verified(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Command works",
                "checks": [{"check_type": "command", "check_value": "true"}],
            }
        ]
        result = run_dod_evidence(items)
        assert result.verified == 1

    def test_command_exit_1_is_failed(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Command works",
                "checks": [{"check_type": "command", "check_value": "false"}],
            }
        ]
        result = run_dod_evidence(items)
        assert result.failed == 1

    def test_command_timeout(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Slow command",
                "checks": [{"check_type": "command", "check_value": "sleep 60"}],
            }
        ]
        # Patch timeout to be very short
        with patch(
            "dod_evidence_runner._DEFAULT_TIMEOUT_SECONDS",
            1,
        ):
            result = run_dod_evidence(items)
        assert result.failed == 1
        assert "Timeout" in result.details[0].checks[0].message


class TestRunnerStructuredResult:
    """Tests for structured result format."""

    def test_runner_produces_structured_result(self) -> None:
        items = [
            {
                "id": "dod-001",
                "description": "Item 1",
                "checks": [{"check_type": "command", "check_value": "true"}],
            },
            {
                "id": "dod-002",
                "description": "Item 2",
                "checks": [{"check_type": "command", "check_value": "false"}],
            },
            {
                "id": "dod-003",
                "description": "Item 3",
                "checks": [
                    {"check_type": "endpoint", "check_value": "http://localhost"}
                ],
            },
        ]
        result = run_dod_evidence(items)
        assert result.total == 3
        assert result.verified == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert len(result.details) == 3


class TestEvidenceReceipt:
    """Tests for evidence receipt writing."""

    def test_runner_writes_evidence_receipt(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=1, verified=1)
        receipt_path = write_evidence_receipt(
            ticket_id="OMN-5168",
            contract_path="contracts/OMN-5168.yaml",
            run_result=run_result,
            working_dir=str(tmp_path),
            output_dir=str(tmp_path / ".evidence" / "OMN-5168"),
        )
        assert receipt_path.exists()
        data = json.loads(receipt_path.read_text())
        assert data["ticket_id"] == "OMN-5168"

    def test_receipt_includes_timestamp(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=0)
        receipt_path = write_evidence_receipt(
            ticket_id="OMN-5168",
            contract_path="contracts/OMN-5168.yaml",
            run_result=run_result,
            working_dir=str(tmp_path),
            output_dir=str(tmp_path / ".evidence" / "OMN-5168"),
        )
        data = json.loads(receipt_path.read_text())
        assert "timestamp" in data
        assert "T" in data["timestamp"]  # ISO format

    def test_receipt_includes_provenance(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=0)
        receipt_path = write_evidence_receipt(
            ticket_id="OMN-5168",
            contract_path="contracts/OMN-5168.yaml",
            run_result=run_result,
            working_dir=str(tmp_path),
            output_dir=str(tmp_path / ".evidence" / "OMN-5168"),
        )
        data = json.loads(receipt_path.read_text())
        assert "git_sha" in data
        assert "branch" in data
        assert "working_dir" in data
        assert "contract_path" in data

    def test_receipt_provenance_matches_current_repo(self) -> None:
        """Receipt provenance reflects actual repo state when run from a git repo."""
        import tempfile

        # Use the actual worktree as working_dir
        working_dir = str(Path(__file__).resolve().parents[2])  # omniclaude root

        with tempfile.TemporaryDirectory() as output_dir:
            run_result = EvidenceRunResult(total=0)
            receipt_path = write_evidence_receipt(
                ticket_id="OMN-TEST",
                contract_path="test.yaml",
                run_result=run_result,
                working_dir=working_dir,
                output_dir=output_dir,
            )
            data = json.loads(receipt_path.read_text())

            # Should have a real git SHA from the omniclaude repo
            if data["git_sha"]:
                assert len(data["git_sha"]) == 40  # Full SHA
            assert data["working_dir"] == working_dir


class TestEmitDodVerifyCompleted:
    """Tests for dod.verify.completed event emission."""

    def test_emit_returns_true_when_emit_event_succeeds(self) -> None:
        mock_emit = MagicMock(return_value=True)
        run_result = EvidenceRunResult(total=2, verified=2, failed=0, skipped=0)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            result = emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
            )

        assert result is True
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "dod.verify.completed"
        payload = call_args[0][1]
        assert payload["ticket_id"] == "OMN-5198"
        assert payload["total_checks"] == 2
        assert payload["passed_checks"] == 2
        assert payload["failed_checks"] == 0
        assert payload["overall_pass"] is True

    def test_emit_returns_false_when_no_emit_event(self) -> None:
        run_result = EvidenceRunResult(total=1, verified=0, failed=1)

        with patch("dod_evidence_runner._get_emit_event", return_value=None):
            result = emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
            )

        assert result is False

    def test_emit_payload_includes_policy_mode(self) -> None:
        mock_emit = MagicMock(return_value=True)
        run_result = EvidenceRunResult(total=1, verified=1)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
                policy_mode="hard",
            )

        payload = mock_emit.call_args[0][1]
        assert payload["policy_mode"] == "hard"
        assert payload["overall_pass"] is True

    def test_emit_payload_overall_pass_false_when_failures(self) -> None:
        mock_emit = MagicMock(return_value=True)
        run_result = EvidenceRunResult(total=2, verified=1, failed=1)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
            )

        payload = mock_emit.call_args[0][1]
        assert payload["overall_pass"] is False
        assert payload["failed_checks"] == 1

    def test_emit_returns_false_on_exception(self) -> None:
        mock_emit = MagicMock(side_effect=RuntimeError("daemon crashed"))
        run_result = EvidenceRunResult(total=1, verified=1)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            result = emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
            )

        assert result is False

    def test_emit_uses_explicit_run_id(self) -> None:
        mock_emit = MagicMock(return_value=True)
        run_result = EvidenceRunResult(total=0)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            emit_dod_verify_completed(
                ticket_id="OMN-5198",
                run_result=run_result,
                run_id="fixed-run-id-123",
            )

        payload = mock_emit.call_args[0][1]
        assert payload["run_id"] == "fixed-run-id-123"

    def test_emit_reads_session_id_from_env(self) -> None:
        mock_emit = MagicMock(return_value=True)
        run_result = EvidenceRunResult(total=0)

        with patch("dod_evidence_runner._get_emit_event", return_value=mock_emit):
            with patch.dict("os.environ", {"CLAUDE_SESSION_ID": "session-abc"}):
                emit_dod_verify_completed(
                    ticket_id="OMN-5198",
                    run_result=run_result,
                )

        payload = mock_emit.call_args[0][1]
        assert payload["session_id"] == "session-abc"


class TestWriteEvidenceReceiptWithEmission:
    """Tests for event emission wired into write_evidence_receipt."""

    def test_write_receipt_emits_event_by_default(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=1, verified=1)
        mock_emit_fn = MagicMock(return_value=True)

        with patch(
            "dod_evidence_runner.emit_dod_verify_completed",
            mock_emit_fn,
        ):
            receipt_path = write_evidence_receipt(
                ticket_id="OMN-5198",
                contract_path="contracts/OMN-5198.yaml",
                run_result=run_result,
                working_dir=str(tmp_path),
                output_dir=str(tmp_path / ".evidence" / "OMN-5198"),
            )

        # Receipt must still be written even with emission wired in
        assert receipt_path.exists()
        mock_emit_fn.assert_called_once_with(
            "OMN-5198", run_result, policy_mode="advisory"
        )

    def test_write_receipt_skips_emission_when_emit_false(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=1, verified=1)
        mock_emit_fn = MagicMock(return_value=True)

        with patch(
            "dod_evidence_runner.emit_dod_verify_completed",
            mock_emit_fn,
        ):
            write_evidence_receipt(
                ticket_id="OMN-5198",
                contract_path="contracts/OMN-5198.yaml",
                run_result=run_result,
                working_dir=str(tmp_path),
                output_dir=str(tmp_path / ".evidence" / "OMN-5198"),
                emit=False,
            )

        mock_emit_fn.assert_not_called()

    def test_write_receipt_forwards_policy_mode(self, tmp_path: Path) -> None:
        run_result = EvidenceRunResult(total=1, verified=1)
        mock_emit_fn = MagicMock(return_value=True)

        with patch(
            "dod_evidence_runner.emit_dod_verify_completed",
            mock_emit_fn,
        ):
            write_evidence_receipt(
                ticket_id="OMN-5198",
                contract_path="contracts/OMN-5198.yaml",
                run_result=run_result,
                working_dir=str(tmp_path),
                output_dir=str(tmp_path / ".evidence" / "OMN-5198"),
                policy_mode="soft",
            )

        mock_emit_fn.assert_called_once_with("OMN-5198", run_result, policy_mode="soft")

    def test_write_receipt_still_written_when_emission_fails(
        self, tmp_path: Path
    ) -> None:
        run_result = EvidenceRunResult(total=1, failed=1)
        mock_emit_fn = MagicMock(side_effect=RuntimeError("daemon down"))

        with patch(
            "dod_evidence_runner.emit_dod_verify_completed",
            mock_emit_fn,
        ):
            # Should not raise — emission failure must not break receipt writing
            receipt_path = write_evidence_receipt(
                ticket_id="OMN-5198",
                contract_path="contracts/OMN-5198.yaml",
                run_result=run_result,
                working_dir=str(tmp_path),
                output_dir=str(tmp_path / ".evidence" / "OMN-5198"),
            )

        assert receipt_path.exists()
