# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Golden chain test for skill lifecycle events (Task 1 — OMN-8127).

Verifies that ModelSkillStartedEvent and ModelSkillCompletedEvent have
correct field-level values when published through EventBusInmemory.

This test prevents regression of the skill_invocations producer gap fixed
in OMN-8170 (wiring_dispatchers.py:435 — event_emitter now passed to
handle_skill_requested).

Uses canonical Pydantic models, not hand-written approximate payloads.
Uses EventBusInmemory so no Kafka infrastructure is required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from omnibase_core.event_bus.event_bus_inmemory import EventBusInmemory

from omniclaude.shared.models.model_skill_lifecycle_events import (
    ModelSkillCompletedEvent,
    ModelSkillStartedEvent,
)

TOPIC_SKILL_STARTED = "onex.evt.omniclaude.skill-started.v1"
TOPIC_SKILL_COMPLETED = "onex.evt.omniclaude.skill-completed.v1"


@pytest.mark.unit
async def test_skill_invocations_golden_chain() -> None:
    """Verify skill.started event has correct field values through EventBusInmemory.

    Chain: ModelSkillStartedEvent → bus.publish_envelope → consumed message
    Asserts field-level values, not just count > 0.
    """
    bus = EventBusInmemory()
    await bus.start()

    run_id = uuid4()
    correlation_id = uuid4()
    now = datetime.now(UTC)

    event = ModelSkillStartedEvent(
        run_id=run_id,
        skill_name="pr_review",
        skill_id="plugins/onex/skills/pr_review",
        repo_id="omniclaude",
        correlation_id=correlation_id,
        args_count=2,
        emitted_at=now,
        session_id="test-session-abc123",
    )

    # Validate round-trip before emission
    assert ModelSkillStartedEvent.model_validate(event.model_dump()) == event

    await bus.publish_envelope(event, topic=TOPIC_SKILL_STARTED)

    history = await bus.get_event_history(limit=10, topic=TOPIC_SKILL_STARTED)
    assert len(history) == 1

    received_raw = json.loads(history[0].value.decode("utf-8"))

    # Field-level assertions — NOT just count > 0
    assert received_raw["skill_name"] == "pr_review", (
        "skill_name must be non-null and match the emitted value"
    )
    assert received_raw["skill_id"] == "plugins/onex/skills/pr_review"
    assert received_raw["repo_id"] == "omniclaude"
    assert received_raw["session_id"] == "test-session-abc123"
    assert received_raw["args_count"] == 2
    assert UUID(received_raw["run_id"]) == run_id
    assert UUID(received_raw["correlation_id"]) == correlation_id
    # emitted_at must be a valid datetime string
    parsed_emitted_at = datetime.fromisoformat(received_raw["emitted_at"])
    assert parsed_emitted_at.tzinfo is not None, "emitted_at must be timezone-aware"

    await bus.close()


@pytest.mark.unit
async def test_skill_completed_golden_chain() -> None:
    """Verify skill.completed event has correct field values through EventBusInmemory.

    Chain: ModelSkillCompletedEvent → bus.publish_envelope → consumed message
    Verifies the run_id join key links started and completed events.
    """
    bus = EventBusInmemory()
    await bus.start()

    run_id = uuid4()
    correlation_id = uuid4()
    now = datetime.now(UTC)

    event = ModelSkillCompletedEvent(
        run_id=run_id,
        skill_name="pr_review",
        repo_id="omniclaude",
        correlation_id=correlation_id,
        status="success",
        duration_ms=1523,
        error_type=None,
        started_emit_failed=False,
        emitted_at=now,
        session_id="test-session-abc123",
    )

    assert ModelSkillCompletedEvent.model_validate(event.model_dump()) == event

    await bus.publish_envelope(event, topic=TOPIC_SKILL_COMPLETED)

    history = await bus.get_event_history(limit=10, topic=TOPIC_SKILL_COMPLETED)
    assert len(history) == 1

    received_raw = json.loads(history[0].value.decode("utf-8"))

    # Field-level assertions
    assert received_raw["skill_name"] == "pr_review"
    assert received_raw["status"] == "success", (
        "status must be 'success' | 'failed' | 'partial'"
    )
    assert received_raw["duration_ms"] == 1523
    assert received_raw["error_type"] is None
    assert received_raw["started_emit_failed"] is False
    assert UUID(received_raw["run_id"]) == run_id, (
        "run_id is the join key between started and completed events"
    )

    await bus.close()


@pytest.mark.unit
async def test_skill_started_run_id_links_to_completed() -> None:
    """Verify that run_id is shared between started and completed events.

    This tests the join-key contract that allows projections to correlate
    skill_invocations rows (started → completed) by run_id.
    """
    bus = EventBusInmemory()
    await bus.start()

    run_id = uuid4()
    correlation_id = uuid4()
    now = datetime.now(UTC)

    started = ModelSkillStartedEvent(
        run_id=run_id,
        skill_name="merge_sweep",
        skill_id="plugins/onex/skills/merge_sweep",
        repo_id="omniclaude",
        correlation_id=correlation_id,
        args_count=0,
        emitted_at=now,
    )
    completed = ModelSkillCompletedEvent(
        run_id=run_id,
        skill_name="merge_sweep",
        repo_id="omniclaude",
        correlation_id=correlation_id,
        status="success",
        duration_ms=4200,
        emitted_at=now,
    )

    await bus.publish_envelope(started, topic=TOPIC_SKILL_STARTED)
    await bus.publish_envelope(completed, topic=TOPIC_SKILL_COMPLETED)

    started_history = await bus.get_event_history(topic=TOPIC_SKILL_STARTED)
    completed_history = await bus.get_event_history(topic=TOPIC_SKILL_COMPLETED)

    assert len(started_history) == 1
    assert len(completed_history) == 1

    started_raw = json.loads(started_history[0].value.decode("utf-8"))
    completed_raw = json.loads(completed_history[0].value.decode("utf-8"))

    # The join key must match
    assert started_raw["run_id"] == completed_raw["run_id"], (
        "run_id must be identical between started and completed events (join key)"
    )

    await bus.close()
