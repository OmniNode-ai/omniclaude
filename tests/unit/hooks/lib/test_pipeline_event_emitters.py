#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for pipeline_event_emitters — all five Wave 2 emitters (OMN-5860)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_emit_fn() -> MagicMock:
    """Return a mock emit_event function."""
    return MagicMock()


@pytest.fixture(autouse=True)
def _patch_emit_client(mock_emit_fn: MagicMock):
    """Patch _get_emit_fn to return our mock for all tests."""
    with patch(
        "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
        return_value=mock_emit_fn,
    ):
        yield


# ---------------------------------------------------------------------------
# emit_epic_run_updated
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitEpicRunUpdated:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        emit_epic_run_updated(
            run_id="run-1",
            epic_id="OMN-2920",
            status="completed",
            tickets_total=5,
            tickets_completed=5,
            tickets_failed=0,
            correlation_id="corr-1",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "epic.run.updated"
        assert payload["epic_id"] == "OMN-2920"
        assert payload["status"] == "completed"
        assert "event_id" in payload
        assert "emitted_at" in payload

    def test_silent_on_emit_failure(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        mock_emit_fn.side_effect = RuntimeError("Kafka down")

        # Must not raise
        emit_epic_run_updated(
            run_id="run-1",
            epic_id="OMN-2920",
            status="failed",
            correlation_id="corr-1",
        )


# ---------------------------------------------------------------------------
# emit_pr_watch_updated
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitPrWatchUpdated:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_pr_watch_updated,
        )

        emit_pr_watch_updated(
            run_id="run-2",
            pr_number=381,
            repo="OmniNode-ai/omniclaude",
            ticket_id="OMN-2922",
            status="approved",
            review_cycles_used=1,
            watch_duration_hours=0.5,
            correlation_id="corr-2",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "pr.watch.updated"
        assert payload["pr_number"] == 381
        assert payload["status"] == "approved"


# ---------------------------------------------------------------------------
# emit_gate_decision (new — OMN-5860)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitGateDecision:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_gate_decision,
        )

        emit_gate_decision(
            gate_id="gate-abc123",
            decision="ACCEPTED",
            ticket_id="OMN-2922",
            gate_type="HIGH_RISK",
            wait_seconds=120.5,
            responder="jonah",
            correlation_id="corr-3",
            session_id="sess-1",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "gate.decision"
        assert payload["gate_id"] == "gate-abc123"
        assert payload["decision"] == "ACCEPTED"
        assert payload["ticket_id"] == "OMN-2922"
        assert payload["gate_type"] == "HIGH_RISK"
        assert payload["wait_seconds"] == 120.5
        assert payload["responder"] == "jonah"
        assert payload["session_id"] == "sess-1"
        assert "event_id" in payload
        assert "emitted_at" in payload

    def test_omits_responder_when_none(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_gate_decision,
        )

        emit_gate_decision(
            gate_id="gate-timeout",
            decision="TIMEOUT",
            ticket_id="OMN-2922",
            correlation_id="corr-4",
        )

        _, payload = mock_emit_fn.call_args[0]
        assert "responder" not in payload

    def test_silent_on_emit_failure(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_gate_decision,
        )

        mock_emit_fn.side_effect = RuntimeError("Kafka down")

        emit_gate_decision(
            gate_id="gate-fail",
            decision="REJECTED",
            ticket_id="OMN-2922",
            correlation_id="corr-5",
        )


# ---------------------------------------------------------------------------
# emit_budget_cap_hit (new — OMN-5860)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitBudgetCapHit:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
        )

        emit_budget_cap_hit(
            run_id="run-budget-1",
            tokens_used=50000,
            tokens_budget=40000,
            cap_reason="max_tokens_injected exceeded",
            correlation_id="corr-6",
            session_id="sess-2",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "budget.cap.hit"
        assert payload["run_id"] == "run-budget-1"
        assert payload["tokens_used"] == 50000
        assert payload["tokens_budget"] == 40000
        assert payload["cap_reason"] == "max_tokens_injected exceeded"
        assert payload["session_id"] == "sess-2"
        assert "event_id" in payload
        assert "emitted_at" in payload

    def test_default_cap_reason(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
        )

        emit_budget_cap_hit(
            run_id="run-budget-2",
            tokens_used=5000,
            tokens_budget=4000,
            correlation_id="corr-7",
        )

        _, payload = mock_emit_fn.call_args[0]
        assert payload["cap_reason"] == "max_tokens_injected exceeded"

    def test_silent_on_emit_failure(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
        )

        mock_emit_fn.side_effect = RuntimeError("Kafka down")

        emit_budget_cap_hit(
            run_id="run-budget-3",
            tokens_used=5000,
            tokens_budget=4000,
            correlation_id="corr-8",
        )


# ---------------------------------------------------------------------------
# emit_circuit_breaker_tripped (new — OMN-5860)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitCircuitBreakerTripped:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_circuit_breaker_tripped,
        )

        emit_circuit_breaker_tripped(
            session_id="sess-cb-1",
            failure_count=5,
            threshold=3,
            reset_timeout_seconds=30.0,
            last_error="Connection refused",
            correlation_id="corr-9",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "circuit.breaker.tripped"
        assert payload["session_id"] == "sess-cb-1"
        assert payload["failure_count"] == 5
        assert payload["threshold"] == 3
        assert payload["reset_timeout_seconds"] == 30.0
        assert payload["last_error"] == "Connection refused"
        assert "event_id" in payload
        assert "emitted_at" in payload

    def test_omits_last_error_when_none(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_circuit_breaker_tripped,
        )

        emit_circuit_breaker_tripped(
            session_id="sess-cb-2",
            failure_count=3,
            threshold=3,
            reset_timeout_seconds=60.0,
            correlation_id="corr-10",
        )

        _, payload = mock_emit_fn.call_args[0]
        assert "last_error" not in payload

    def test_silent_on_emit_failure(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_circuit_breaker_tripped,
        )

        mock_emit_fn.side_effect = RuntimeError("Kafka down")

        emit_circuit_breaker_tripped(
            session_id="sess-cb-3",
            failure_count=5,
            threshold=3,
            reset_timeout_seconds=30.0,
            correlation_id="corr-11",
        )


# ---------------------------------------------------------------------------
# emit_hostile_reviewer_completed (new — OMN-5861)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitHostileReviewerCompleted:
    def test_emits_to_correct_topic(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_hostile_reviewer_completed,
        )

        emit_hostile_reviewer_completed(
            mode="file",
            target="docs/plans/my-plan.md",
            models_attempted=["claude-sonnet-4-20250514"],
            models_succeeded=["claude-sonnet-4-20250514"],
            verdict="risks_noted",
            total_findings=3,
            critical_count=0,
            major_count=1,
            correlation_id="corr-hr-1",
            session_id="sess-hr-1",
        )

        mock_emit_fn.assert_called_once()
        topic, payload = mock_emit_fn.call_args[0]
        assert topic == "hostile.reviewer.completed"
        assert payload["mode"] == "file"
        assert payload["target"] == "docs/plans/my-plan.md"
        assert payload["models_attempted"] == ["claude-sonnet-4-20250514"]
        assert payload["models_succeeded"] == ["claude-sonnet-4-20250514"]
        assert payload["verdict"] == "risks_noted"
        assert payload["total_findings"] == 3
        assert payload["critical_count"] == 0
        assert payload["major_count"] == 1
        assert payload["session_id"] == "sess-hr-1"
        assert "event_id" in payload
        assert "emitted_at" in payload

    def test_defaults_empty_model_lists(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_hostile_reviewer_completed,
        )

        emit_hostile_reviewer_completed(
            mode="pr",
            target="42",
            verdict="clean",
            correlation_id="corr-hr-2",
        )

        _, payload = mock_emit_fn.call_args[0]
        assert payload["models_attempted"] == []
        assert payload["models_succeeded"] == []

    def test_silent_on_emit_failure(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_hostile_reviewer_completed,
        )

        mock_emit_fn.side_effect = RuntimeError("Kafka down")

        emit_hostile_reviewer_completed(
            mode="file",
            target="some-file.py",
            verdict="degraded",
            correlation_id="corr-hr-3",
        )


# ---------------------------------------------------------------------------
# Edge case: emit_fn is None (daemon unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitFnUnavailable:
    def test_all_emitters_silent_when_daemon_unavailable(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
            emit_circuit_breaker_tripped,
            emit_epic_run_updated,
            emit_gate_decision,
            emit_hostile_reviewer_completed,
            emit_pr_watch_updated,
        )

        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=None,
        ):
            # None of these should raise
            emit_epic_run_updated(
                run_id="r", epic_id="E", status="running", correlation_id="c"
            )
            emit_pr_watch_updated(
                run_id="r",
                pr_number=1,
                repo="r",
                ticket_id="t",
                status="watching",
                correlation_id="c",
            )
            emit_gate_decision(
                gate_id="g",
                decision="ACCEPTED",
                ticket_id="t",
                correlation_id="c",
            )
            emit_budget_cap_hit(
                run_id="r",
                tokens_used=1,
                tokens_budget=1,
                correlation_id="c",
            )
            emit_circuit_breaker_tripped(
                session_id="s",
                failure_count=1,
                threshold=1,
                reset_timeout_seconds=1.0,
                correlation_id="c",
            )
            emit_hostile_reviewer_completed(
                mode="file",
                target="test.py",
                verdict="clean",
                correlation_id="c",
            )
