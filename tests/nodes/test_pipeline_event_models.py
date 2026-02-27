# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for Wave 2 pipeline event models (OMN-2922).

Validates that ModelEpicRunUpdatedEvent, ModelPrWatchUpdatedEvent,
ModelGateDecisionEvent, ModelBudgetCapHitEvent, and
ModelCircuitBreakerTrippedEvent have correct fields, frozen semantics,
and JSON serialization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# ModelEpicRunUpdatedEvent
# ---------------------------------------------------------------------------


class TestModelEpicRunUpdatedEvent:
    """Tests for ModelEpicRunUpdatedEvent."""

    def test_basic_construction(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelEpicRunUpdatedEvent,
        )

        run_id = uuid.uuid4()
        corr_id = uuid.uuid4()
        now = _now()
        event = ModelEpicRunUpdatedEvent(
            run_id=run_id,
            epic_id="OMN-2920",
            status="running",
            correlation_id=corr_id,
            emitted_at=now,
        )
        assert event.run_id == run_id
        assert event.epic_id == "OMN-2920"
        assert event.status == "running"
        assert event.tickets_total == 0
        assert event.tickets_completed == 0
        assert event.tickets_failed == 0
        assert event.phase is None
        assert event.session_id is None

    def test_frozen(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelEpicRunUpdatedEvent,
        )

        event = ModelEpicRunUpdatedEvent(
            run_id=uuid.uuid4(),
            epic_id="OMN-2920",
            status="completed",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        with pytest.raises(Exception):
            event.status = "failed"  # type: ignore[misc]

    def test_all_statuses_valid(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelEpicRunUpdatedEvent,
        )

        for status in ("running", "completed", "failed", "partial", "cancelled"):
            event = ModelEpicRunUpdatedEvent(
                run_id=uuid.uuid4(),
                epic_id="OMN-2920",
                status=status,  # type: ignore[arg-type]
                correlation_id=uuid.uuid4(),
                emitted_at=_now(),
            )
            assert event.status == status

    def test_json_round_trip(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelEpicRunUpdatedEvent,
        )

        event = ModelEpicRunUpdatedEvent(
            run_id=uuid.uuid4(),
            epic_id="OMN-2920",
            status="completed",
            tickets_total=5,
            tickets_completed=5,
            tickets_failed=0,
            phase="auto_merge",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
            session_id="session-abc",
        )
        data = event.model_dump(mode="json")
        restored = ModelEpicRunUpdatedEvent(**data)
        assert restored.epic_id == event.epic_id
        assert restored.status == event.status
        assert restored.tickets_total == 5

    def test_event_id_auto_generated(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelEpicRunUpdatedEvent,
        )

        e1 = ModelEpicRunUpdatedEvent(
            run_id=uuid.uuid4(),
            epic_id="OMN-2920",
            status="running",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        e2 = ModelEpicRunUpdatedEvent(
            run_id=uuid.uuid4(),
            epic_id="OMN-2920",
            status="running",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert e1.event_id != e2.event_id


# ---------------------------------------------------------------------------
# ModelPrWatchUpdatedEvent
# ---------------------------------------------------------------------------


class TestModelPrWatchUpdatedEvent:
    """Tests for ModelPrWatchUpdatedEvent."""

    def test_basic_construction(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelPrWatchUpdatedEvent,
        )

        run_id = uuid.uuid4()
        corr_id = uuid.uuid4()
        event = ModelPrWatchUpdatedEvent(
            run_id=run_id,
            pr_number=381,
            repo="OmniNode-ai/omniclaude",
            ticket_id="OMN-2922",
            status="watching",
            correlation_id=corr_id,
            emitted_at=_now(),
        )
        assert event.pr_number == 381
        assert event.repo == "OmniNode-ai/omniclaude"
        assert event.ticket_id == "OMN-2922"
        assert event.review_cycles_used == 0
        assert event.watch_duration_hours == 0.0

    def test_frozen(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelPrWatchUpdatedEvent,
        )

        event = ModelPrWatchUpdatedEvent(
            run_id=uuid.uuid4(),
            pr_number=381,
            repo="OmniNode-ai/omniclaude",
            ticket_id="OMN-2922",
            status="approved",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        with pytest.raises(Exception):
            event.status = "failed"  # type: ignore[misc]

    def test_all_statuses_valid(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelPrWatchUpdatedEvent,
        )

        for status in ("watching", "approved", "capped", "timeout", "failed"):
            event = ModelPrWatchUpdatedEvent(
                run_id=uuid.uuid4(),
                pr_number=1,
                repo="org/repo",
                ticket_id="OMN-1",
                status=status,  # type: ignore[arg-type]
                correlation_id=uuid.uuid4(),
                emitted_at=_now(),
            )
            assert event.status == status


# ---------------------------------------------------------------------------
# ModelGateDecisionEvent
# ---------------------------------------------------------------------------


class TestModelGateDecisionEvent:
    """Tests for ModelGateDecisionEvent."""

    def test_accepted(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelGateDecisionEvent,
        )

        event = ModelGateDecisionEvent(
            gate_id="gate-abc",
            decision="ACCEPTED",
            ticket_id="OMN-2922",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert event.decision == "ACCEPTED"
        assert event.gate_type == "HIGH_RISK"
        assert event.responder is None

    def test_rejected(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelGateDecisionEvent,
        )

        event = ModelGateDecisionEvent(
            gate_id="gate-abc",
            decision="REJECTED",
            ticket_id="OMN-2922",
            responder="U1234567",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert event.decision == "REJECTED"
        assert event.responder == "U1234567"

    def test_timeout(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelGateDecisionEvent,
        )

        event = ModelGateDecisionEvent(
            gate_id="gate-abc",
            decision="TIMEOUT",
            ticket_id="OMN-2922",
            wait_seconds=3600.0,
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert event.decision == "TIMEOUT"
        assert event.wait_seconds == 3600.0

    def test_frozen(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelGateDecisionEvent,
        )

        event = ModelGateDecisionEvent(
            gate_id="gate-abc",
            decision="ACCEPTED",
            ticket_id="OMN-2922",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        with pytest.raises(Exception):
            event.decision = "REJECTED"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ModelBudgetCapHitEvent
# ---------------------------------------------------------------------------


class TestModelBudgetCapHitEvent:
    """Tests for ModelBudgetCapHitEvent."""

    def test_basic_construction(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelBudgetCapHitEvent,
        )

        run_id = uuid.uuid4()
        event = ModelBudgetCapHitEvent(
            run_id=run_id,
            tokens_used=1850,
            tokens_budget=2000,
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert event.tokens_used == 1850
        assert event.tokens_budget == 2000
        assert event.cap_reason == "max_tokens_injected exceeded"

    def test_frozen(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelBudgetCapHitEvent,
        )

        event = ModelBudgetCapHitEvent(
            run_id=uuid.uuid4(),
            tokens_used=1800,
            tokens_budget=2000,
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        with pytest.raises(Exception):
            event.tokens_used = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ModelCircuitBreakerTrippedEvent
# ---------------------------------------------------------------------------


class TestModelCircuitBreakerTrippedEvent:
    """Tests for ModelCircuitBreakerTrippedEvent."""

    def test_basic_construction(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelCircuitBreakerTrippedEvent,
        )

        event = ModelCircuitBreakerTrippedEvent(
            session_id="session-abc",
            failure_count=5,
            threshold=5,
            reset_timeout_seconds=10.0,
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert event.session_id == "session-abc"
        assert event.failure_count == 5
        assert event.threshold == 5
        assert event.reset_timeout_seconds == 10.0
        assert event.last_error is None

    def test_with_last_error(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelCircuitBreakerTrippedEvent,
        )

        event = ModelCircuitBreakerTrippedEvent(
            session_id="session-abc",
            failure_count=5,
            threshold=5,
            reset_timeout_seconds=10.0,
            last_error="ConnectionRefusedError: [Errno 111]",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        assert "ConnectionRefusedError" in event.last_error  # type: ignore[operator]

    def test_frozen(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelCircuitBreakerTrippedEvent,
        )

        event = ModelCircuitBreakerTrippedEvent(
            session_id="session-abc",
            failure_count=5,
            threshold=5,
            reset_timeout_seconds=10.0,
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        with pytest.raises(Exception):
            event.failure_count = 99  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        from omniclaude.nodes.shared.models.model_pipeline_events import (
            ModelCircuitBreakerTrippedEvent,
        )

        event = ModelCircuitBreakerTrippedEvent(
            session_id="session-abc",
            failure_count=5,
            threshold=5,
            reset_timeout_seconds=10.0,
            last_error="TimeoutError",
            correlation_id=uuid.uuid4(),
            emitted_at=_now(),
        )
        data = event.model_dump(mode="json")
        restored = ModelCircuitBreakerTrippedEvent(**data)
        assert restored.session_id == "session-abc"
        assert restored.last_error == "TimeoutError"
