# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for evidence dual-write (disk + Kafka)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.verification.evidence_writer import (
    EvidenceWriter,
    ModelCheckResult,
    ModelSelfCheckResult,
    ModelVerifierCheckResult,
)


@pytest.mark.unit
class TestEvidenceWriterDisk:
    """Evidence writer creates files on disk."""

    def test_self_check_creates_file(self, tmp_path: Path) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result = ModelSelfCheckResult(
            task_id="task-1",
            passed=True,
            checks=[
                ModelCheckResult(criterion="Tests pass", status="PASS", output="ok"),
            ],
            contract_fingerprint="abc123",
        )
        path = writer.write_self_check(result)
        assert (tmp_path / "evidence" / "task-1" / "self-check.yaml").exists()
        assert path == tmp_path / "evidence" / "task-1" / "self-check.yaml"

        content = json.loads(path.read_text())
        assert content["task_id"] == "task-1"
        assert content["passed"] is True
        assert content["evidence_type"] == "self_check"
        assert content["contract_fingerprint"] == "abc123"
        assert "timestamp" in content
        assert "content_fingerprint" in content

    def test_verifier_check_creates_file(self, tmp_path: Path) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result = ModelVerifierCheckResult(
            task_id="task-2",
            passed=False,
            findings=["Missing unit test for edge case"],
            contract_fingerprint="def456",
        )
        path = writer.write_verifier_check(result)
        assert (tmp_path / "evidence" / "task-2" / "verifier-check.yaml").exists()

        content = json.loads(path.read_text())
        assert content["task_id"] == "task-2"
        assert content["passed"] is False
        assert content["evidence_type"] == "verifier"
        assert content["findings"] == ["Missing unit test for edge case"]
        assert content["contract_fingerprint"] == "def456"

    def test_reverification_overwrites_with_fresh_timestamp(
        self, tmp_path: Path
    ) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result_v1 = ModelSelfCheckResult(task_id="task-3", passed=False, checks=[])
        result_v2 = ModelSelfCheckResult(task_id="task-3", passed=True, checks=[])

        writer.write_self_check(result_v1)
        content_v1 = json.loads(
            (tmp_path / "evidence" / "task-3" / "self-check.yaml").read_text()
        )

        writer.write_self_check(result_v2)
        content_v2 = json.loads(
            (tmp_path / "evidence" / "task-3" / "self-check.yaml").read_text()
        )

        assert content_v1["timestamp"] != content_v2["timestamp"]
        assert content_v2["passed"] is True


@pytest.mark.unit
class TestEvidenceWriterKafka:
    """Evidence writer emits Kafka events (fail-open)."""

    @patch("omniclaude.verification.evidence_writer.emit_event")
    def test_self_check_emits_kafka_event(
        self, mock_emit: MagicMock, tmp_path: Path
    ) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result = ModelSelfCheckResult(task_id="task-1", passed=True, checks=[])
        writer.write_self_check(result, session_id="s1", correlation_id="c1")

        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert event.evidence_type == "self_check"
        assert event.passed is True
        assert event.task_id == "task-1"
        assert event.session_id == "s1"
        assert event.correlation_id == "c1"

    @patch("omniclaude.verification.evidence_writer.emit_event")
    def test_verifier_check_emits_kafka_event(
        self, mock_emit: MagicMock, tmp_path: Path
    ) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result = ModelVerifierCheckResult(
            task_id="task-2", passed=False, findings=["issue"]
        )
        writer.write_verifier_check(result, session_id="s2", correlation_id="c2")

        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert event.evidence_type == "verifier"
        assert event.passed is False
        assert event.task_id == "task-2"

    @patch("omniclaude.verification.evidence_writer.emit_event")
    def test_reverification_emits_fresh_kafka_event(
        self, mock_emit: MagicMock, tmp_path: Path
    ) -> None:
        writer = EvidenceWriter(state_dir=str(tmp_path))
        result = ModelSelfCheckResult(task_id="task-3", passed=True, checks=[])

        writer.write_self_check(result)
        writer.write_self_check(result)

        assert mock_emit.call_count == 2
        first_event = mock_emit.call_args_list[0][0][0]
        second_event = mock_emit.call_args_list[1][0][0]
        assert first_event.emitted_at != second_event.emitted_at
