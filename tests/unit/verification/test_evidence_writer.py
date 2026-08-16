# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for evidence dual-write (disk + Kafka)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.verification.evidence_writer import (
    EvidenceWriter,
    ModelCheckResult,
    ModelEvidenceWrittenEvent,
    ModelSelfCheckResult,
    ModelVerifierCheckResult,
    emit_event,
)

_EMIT_EFFECT_HANDLER_MODULE = (
    "omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect"
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


@pytest.mark.unit
class TestEmitEventImportFailureIsLoud:
    """OMN-15968: a broken node_event_emit_effect import must be loud.

    Repoints the dead ``node_emit_daemon.client`` import to
    ``node_event_emit_effect`` and removes the fail-open ImportError guard
    that used to swallow this at debug (OMN-13213 D1 follow-through).
    """

    def test_import_failure_logs_at_error_not_debug(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # None in sys.modules is the standard way to force ImportError for
        # a specific dotted module without needing the real package absent.
        monkeypatch.setitem(sys.modules, _EMIT_EFFECT_HANDLER_MODULE, None)
        event = ModelEvidenceWrittenEvent(
            task_id="task-import-break",
            evidence_type="self_check",
            evidence_path="/tmp/z",
            passed=True,
            emitted_at=datetime.now(UTC),
        )

        with caplog.at_level(
            logging.ERROR, logger="omniclaude.verification.evidence_writer"
        ):
            emit_event(event)

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "expected an ERROR-level log on import failure"
        assert any("task-import-break" in r.getMessage() for r in error_records)
