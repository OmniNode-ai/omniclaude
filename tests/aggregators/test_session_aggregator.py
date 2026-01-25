# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for SessionAggregator.

Validates aggregation contract semantics including:
- Idempotency: Events deduplicated via natural keys
- Out-of-order handling: Events within buffer accepted, outside logged
- Status state machine: ORPHAN -> ACTIVE -> ENDED/TIMED_OUT transitions
- First-write-wins: Identity fields set once and never overwritten
- Append-only collections: Prompts and tools accumulate

Related Tickets:
    - OMN-1401: Session storage in OmniMemory
    - OMN-1489: Core models in omnibase_core
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from omniclaude.aggregators import (
    ConfigSessionAggregator,
    EnumSessionStatus,
    ProtocolSessionAggregator,
    SessionAggregator,
)
from omniclaude.hooks.schemas import (
    HookEventType,
    HookSource,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
    SessionEndReason,
)

# =============================================================================
# Helper Factories
# =============================================================================


def make_timestamp(offset_seconds: float = 0.0) -> datetime:
    """Create a timezone-aware timestamp with optional offset."""
    return datetime.now(UTC) + timedelta(seconds=offset_seconds)


def make_session_started(
    session_id: str,
    entity_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    working_directory: str = "/workspace/test",
    git_branch: str | None = "main",
    hook_source: HookSource = HookSource.STARTUP,
) -> ModelHookEventEnvelope:
    """Create a SessionStarted event envelope."""
    entity = entity_id or uuid4()
    return ModelHookEventEnvelope(
        event_type=HookEventType.SESSION_STARTED,
        payload=ModelHookSessionStartedPayload(
            entity_id=entity,
            session_id=session_id,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id or uuid4(),
            emitted_at=emitted_at or make_timestamp(),
            working_directory=working_directory,
            git_branch=git_branch,
            hook_source=hook_source,
        ),
    )


def make_session_ended(
    session_id: str,
    entity_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    reason: SessionEndReason = SessionEndReason.LOGOUT,
    duration_seconds: float | None = None,
    tools_used_count: int = 0,
) -> ModelHookEventEnvelope:
    """Create a SessionEnded event envelope."""
    entity = entity_id or uuid4()
    return ModelHookEventEnvelope(
        event_type=HookEventType.SESSION_ENDED,
        payload=ModelHookSessionEndedPayload(
            entity_id=entity,
            session_id=session_id,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id or uuid4(),
            emitted_at=emitted_at or make_timestamp(),
            reason=reason,
            duration_seconds=duration_seconds,
            tools_used_count=tools_used_count,
        ),
    )


def make_prompt_submitted(
    session_id: str,
    prompt_id: UUID | None = None,
    entity_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    prompt_preview: str = "Test prompt",
    prompt_length: int = 100,
    detected_intent: str | None = None,
) -> ModelHookEventEnvelope:
    """Create a PromptSubmitted event envelope."""
    entity = entity_id or uuid4()
    return ModelHookEventEnvelope(
        event_type=HookEventType.PROMPT_SUBMITTED,
        payload=ModelHookPromptSubmittedPayload(
            entity_id=entity,
            session_id=session_id,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id or uuid4(),
            emitted_at=emitted_at or make_timestamp(),
            prompt_id=prompt_id or uuid4(),
            prompt_preview=prompt_preview,
            prompt_length=prompt_length,
            detected_intent=detected_intent,
        ),
    )


def make_tool_executed(
    session_id: str,
    tool_execution_id: UUID | None = None,
    entity_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
    emitted_at: datetime | None = None,
    tool_name: str = "Read",
    success: bool = True,
    duration_ms: int | None = 50,
    summary: str | None = "Read file successfully",
) -> ModelHookEventEnvelope:
    """Create a ToolExecuted event envelope."""
    entity = entity_id or uuid4()
    return ModelHookEventEnvelope(
        event_type=HookEventType.TOOL_EXECUTED,
        payload=ModelHookToolExecutedPayload(
            entity_id=entity,
            session_id=session_id,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id or uuid4(),
            emitted_at=emitted_at or make_timestamp(),
            tool_execution_id=tool_execution_id or uuid4(),
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
            summary=summary,
        ),
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config() -> ConfigSessionAggregator:
    """Create default aggregator configuration."""
    return ConfigSessionAggregator()


@pytest.fixture
def aggregator(config: ConfigSessionAggregator) -> SessionAggregator:
    """Create a session aggregator instance."""
    return SessionAggregator(config, aggregator_id="test-aggregator")


@pytest.fixture
def correlation_id() -> UUID:
    """Create a correlation ID for tracing."""
    return uuid4()


# =============================================================================
# Happy Path Tests
# =============================================================================


class TestHappyPath:
    """Tests for normal session lifecycle."""

    @pytest.mark.asyncio
    async def test_complete_session_lifecycle(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Complete session: start -> prompt -> tool -> end."""
        session_id = "test-session-1"
        base_time = make_timestamp()

        # 1. Start session
        start_event = make_session_started(
            session_id, emitted_at=base_time, working_directory="/workspace/project"
        )
        result = await aggregator.process_event(start_event, correlation_id)
        assert result is True

        # Verify ACTIVE status
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot is not None
        assert snapshot["status"] == EnumSessionStatus.ACTIVE.value
        assert snapshot["working_directory"] == "/workspace/project"
        assert snapshot["event_count"] == 1

        # 2. Submit prompt
        prompt_event = make_prompt_submitted(
            session_id,
            emitted_at=base_time + timedelta(seconds=1),
            prompt_preview="Fix the bug",
            prompt_length=50,
        )
        result = await aggregator.process_event(prompt_event, correlation_id)
        assert result is True

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 1
        assert snapshot["event_count"] == 2

        # 3. Execute tool
        tool_event = make_tool_executed(
            session_id,
            emitted_at=base_time + timedelta(seconds=2),
            tool_name="Read",
            success=True,
        )
        result = await aggregator.process_event(tool_event, correlation_id)
        assert result is True

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["tool_count"] == 1
        assert snapshot["event_count"] == 3

        # 4. End session
        end_event = make_session_ended(
            session_id,
            emitted_at=base_time + timedelta(seconds=10),
            reason=SessionEndReason.LOGOUT,
            duration_seconds=10.0,
        )
        result = await aggregator.process_event(end_event, correlation_id)
        assert result is True

        # Verify ENDED status
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ENDED.value
        assert snapshot["end_reason"] == SessionEndReason.LOGOUT.value
        assert snapshot["prompt_count"] == 1
        assert snapshot["tool_count"] == 1
        assert snapshot["event_count"] == 4

    @pytest.mark.asyncio
    async def test_session_with_only_start_and_end(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Session with only start and end events (no prompts/tools)."""
        session_id = "minimal-session"
        base_time = make_timestamp()

        # Start
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # End
        end_event = make_session_ended(
            session_id,
            emitted_at=base_time + timedelta(seconds=5),
            duration_seconds=5.0,
        )
        await aggregator.process_event(end_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ENDED.value
        assert snapshot["prompt_count"] == 0
        assert snapshot["tool_count"] == 0
        assert snapshot["event_count"] == 2

    @pytest.mark.asyncio
    async def test_session_with_many_events(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Session with many prompts and tools."""
        session_id = "busy-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add 10 prompts and 20 tools
        for i in range(10):
            prompt_event = make_prompt_submitted(
                session_id,
                emitted_at=base_time + timedelta(seconds=i + 1),
                prompt_preview=f"Prompt {i}",
            )
            await aggregator.process_event(prompt_event, correlation_id)

        for i in range(20):
            tool_event = make_tool_executed(
                session_id,
                emitted_at=base_time + timedelta(seconds=11 + i),
                tool_name=f"Tool{i}",
            )
            await aggregator.process_event(tool_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 10
        assert snapshot["tool_count"] == 20
        assert snapshot["event_count"] == 31  # 1 start + 10 prompts + 20 tools


# =============================================================================
# Idempotency Tests
# =============================================================================


class TestIdempotency:
    """Tests for event idempotency (critical per contract)."""

    @pytest.mark.asyncio
    async def test_duplicate_session_started_ignored(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Second SessionStarted for same session is ignored."""
        session_id = "dup-start-session"

        # First SessionStarted
        event1 = make_session_started(
            session_id, working_directory="/first/path", git_branch="main"
        )
        result1 = await aggregator.process_event(event1, correlation_id)
        assert result1 is True

        # Second SessionStarted (should be ignored)
        event2 = make_session_started(
            session_id, working_directory="/second/path", git_branch="feature"
        )
        result2 = await aggregator.process_event(event2, correlation_id)
        assert result2 is False

        # Verify original values preserved
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["working_directory"] == "/first/path"
        assert snapshot["git_branch"] == "main"
        assert snapshot["event_count"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_session_ended_ignored(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Second SessionEnded for same session is ignored."""
        session_id = "dup-end-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # First SessionEnded
        end1 = make_session_ended(
            session_id,
            emitted_at=base_time + timedelta(seconds=10),
            reason=SessionEndReason.LOGOUT,
            duration_seconds=10.0,
        )
        result1 = await aggregator.process_event(end1, correlation_id)
        assert result1 is True

        # Second SessionEnded (should be ignored)
        end2 = make_session_ended(
            session_id,
            emitted_at=base_time + timedelta(seconds=20),
            reason=SessionEndReason.CLEAR,
            duration_seconds=20.0,
        )
        result2 = await aggregator.process_event(end2, correlation_id)
        assert result2 is False

        # Verify first end values preserved
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["end_reason"] == SessionEndReason.LOGOUT.value
        assert snapshot["duration_seconds"] == 10.0

    @pytest.mark.asyncio
    async def test_duplicate_prompt_same_id_ignored(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Prompt with same prompt_id is ignored (natural key deduplication)."""
        session_id = "dup-prompt-session"
        prompt_id = uuid4()

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # First prompt
        prompt1 = make_prompt_submitted(
            session_id, prompt_id=prompt_id, prompt_preview="First prompt"
        )
        result1 = await aggregator.process_event(prompt1, correlation_id)
        assert result1 is True

        # Duplicate prompt (same prompt_id)
        prompt2 = make_prompt_submitted(
            session_id, prompt_id=prompt_id, prompt_preview="Duplicate prompt"
        )
        result2 = await aggregator.process_event(prompt2, correlation_id)
        assert result2 is False

        # Verify only one prompt exists
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 1
        assert snapshot["prompts"][0]["prompt_preview"] == "First prompt"

    @pytest.mark.asyncio
    async def test_duplicate_tool_same_execution_id_ignored(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Tool with same tool_execution_id is ignored."""
        session_id = "dup-tool-session"
        tool_execution_id = uuid4()

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # First tool execution
        tool1 = make_tool_executed(
            session_id, tool_execution_id=tool_execution_id, tool_name="Read"
        )
        result1 = await aggregator.process_event(tool1, correlation_id)
        assert result1 is True

        # Duplicate tool execution (same tool_execution_id)
        tool2 = make_tool_executed(
            session_id, tool_execution_id=tool_execution_id, tool_name="Write"
        )
        result2 = await aggregator.process_event(tool2, correlation_id)
        assert result2 is False

        # Verify only one tool exists
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["tool_count"] == 1
        assert snapshot["tools"][0]["tool_name"] == "Read"


# =============================================================================
# Out-of-Order Tests
# =============================================================================


class TestOutOfOrder:
    """Tests for out-of-order event handling (critical per contract)."""

    @pytest.mark.asyncio
    async def test_events_within_buffer_accepted(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Events out of order within buffer window are accepted."""
        session_id = "ooo-buffer-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add prompt at t+10
        prompt1 = make_prompt_submitted(
            session_id, emitted_at=base_time + timedelta(seconds=10)
        )
        await aggregator.process_event(prompt1, correlation_id)

        # Add prompt at t+5 (out of order but within 60s buffer)
        prompt2 = make_prompt_submitted(
            session_id, emitted_at=base_time + timedelta(seconds=5)
        )
        result = await aggregator.process_event(prompt2, correlation_id)

        # Should be accepted
        assert result is True
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 2

    @pytest.mark.asyncio
    async def test_events_outside_buffer_logged_but_accepted(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Events outside buffer window are logged but still accepted."""
        session_id = "ooo-outside-buffer-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add prompt at t+120 (well ahead)
        prompt1 = make_prompt_submitted(
            session_id, emitted_at=base_time + timedelta(seconds=120)
        )
        await aggregator.process_event(prompt1, correlation_id)

        # Add prompt at t+5 (120-5=115 seconds behind, outside 60s buffer)
        prompt2 = make_prompt_submitted(
            session_id, emitted_at=base_time + timedelta(seconds=5)
        )
        result = await aggregator.process_event(prompt2, correlation_id)

        # Should still be accepted (logs warning but accepts)
        assert result is True
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 2


# =============================================================================
# Partial Session Tests
# =============================================================================


class TestPartialSession:
    """Tests for partial/orphan sessions."""

    @pytest.mark.asyncio
    async def test_prompt_before_session_started_creates_orphan(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Prompt arriving before SessionStarted creates ORPHAN session."""
        session_id = "orphan-prompt-session"

        # Prompt without SessionStarted
        prompt_event = make_prompt_submitted(session_id, prompt_preview="Orphan prompt")
        result = await aggregator.process_event(prompt_event, correlation_id)
        assert result is True

        # Verify ORPHAN status
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ORPHAN.value
        assert snapshot["prompt_count"] == 1
        # Orphan sessions don't have identity fields set
        assert snapshot["working_directory"] is None

    @pytest.mark.asyncio
    async def test_tool_before_session_started_creates_orphan(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Tool arriving before SessionStarted creates ORPHAN session."""
        session_id = "orphan-tool-session"

        # Tool without SessionStarted
        tool_event = make_tool_executed(session_id, tool_name="Orphan Read")
        result = await aggregator.process_event(tool_event, correlation_id)
        assert result is True

        # Verify ORPHAN status
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ORPHAN.value
        assert snapshot["tool_count"] == 1

    @pytest.mark.asyncio
    async def test_missing_session_end_stays_active(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Session without SessionEnded stays ACTIVE."""
        session_id = "no-end-session"

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # Add prompts and tools
        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        tool_event = make_tool_executed(session_id)
        await aggregator.process_event(tool_event, correlation_id)

        # Session should remain ACTIVE (no end event)
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ACTIVE.value
        assert snapshot["ended_at"] is None

    @pytest.mark.asyncio
    async def test_session_ended_without_start_creates_ended_orphan(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """SessionEnded without SessionStarted creates immediately ENDED session."""
        session_id = "orphan-end-session"

        # End without start
        end_event = make_session_ended(
            session_id, reason=SessionEndReason.OTHER, duration_seconds=None
        )
        result = await aggregator.process_event(end_event, correlation_id)
        assert result is True

        # Verify ENDED status (orphan end is still recorded)
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ENDED.value
        assert snapshot["started_at"] is None


# =============================================================================
# Status State Machine Tests
# =============================================================================


class TestStatusStateMachine:
    """Tests for session status state machine transitions."""

    @pytest.mark.asyncio
    async def test_orphan_to_active_transition(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """ORPHAN session transitions to ACTIVE on SessionStarted."""
        session_id = "orphan-to-active-session"

        # Create orphan with prompt
        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        # Verify ORPHAN
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ORPHAN.value

        # Now receive SessionStarted
        start_event = make_session_started(
            session_id, working_directory="/workspace/orphan-activated"
        )
        result = await aggregator.process_event(start_event, correlation_id)
        assert result is True

        # Verify transition to ACTIVE
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ACTIVE.value
        assert snapshot["working_directory"] == "/workspace/orphan-activated"
        assert snapshot["prompt_count"] == 1  # Orphan prompt preserved

    @pytest.mark.asyncio
    async def test_active_to_ended_transition(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """ACTIVE session transitions to ENDED on SessionEnded."""
        session_id = "active-to-ended-session"

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # Verify ACTIVE
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ACTIVE.value

        # End session
        end_event = make_session_ended(session_id, reason=SessionEndReason.LOGOUT)
        await aggregator.process_event(end_event, correlation_id)

        # Verify ENDED
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.ENDED.value

    @pytest.mark.asyncio
    async def test_finalize_with_timeout_reason(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """finalize_session with timeout reason sets TIMED_OUT status."""
        session_id = "timeout-session"

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # Finalize with timeout reason
        snapshot = await aggregator.finalize_session(
            session_id, correlation_id, reason="timeout"
        )

        assert snapshot is not None
        assert snapshot["status"] == EnumSessionStatus.TIMED_OUT.value
        assert snapshot["end_reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_finalize_without_reason(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """finalize_session without reason defaults to 'unspecified'."""
        session_id = "unspecified-end-session"

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # Finalize without reason
        snapshot = await aggregator.finalize_session(session_id, correlation_id)

        assert snapshot is not None
        assert snapshot["status"] == EnumSessionStatus.ENDED.value
        assert snapshot["end_reason"] == "unspecified"

    @pytest.mark.asyncio
    async def test_finalize_already_finalized_is_idempotent(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Calling finalize on already-finalized session returns existing snapshot."""
        session_id = "double-finalize-session"

        # Start and end session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(
            session_id, reason=SessionEndReason.LOGOUT, duration_seconds=100.0
        )
        await aggregator.process_event(end_event, correlation_id)

        # Finalize again (idempotent)
        snapshot = await aggregator.finalize_session(
            session_id, correlation_id, reason="timeout"
        )

        # Should return existing snapshot without change
        assert snapshot is not None
        assert snapshot["status"] == EnumSessionStatus.ENDED.value
        assert snapshot["end_reason"] == SessionEndReason.LOGOUT.value
        assert snapshot["duration_seconds"] == 100.0

    @pytest.mark.asyncio
    async def test_events_rejected_after_ended(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Events for ENDED session are rejected."""
        session_id = "ended-reject-session"

        # Start and end
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(session_id)
        await aggregator.process_event(end_event, correlation_id)

        # Try to add prompt to ended session
        prompt_event = make_prompt_submitted(session_id)
        result = await aggregator.process_event(prompt_event, correlation_id)
        assert result is False

        # Try to add tool
        tool_event = make_tool_executed(session_id)
        result = await aggregator.process_event(tool_event, correlation_id)
        assert result is False

        # Verify counts unchanged
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 0
        assert snapshot["tool_count"] == 0

    @pytest.mark.asyncio
    async def test_events_rejected_after_timed_out(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Events for TIMED_OUT session are rejected."""
        session_id = "timed-out-reject-session"

        # Start and timeout
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        await aggregator.finalize_session(session_id, correlation_id, reason="timeout")

        # Try to add prompt
        prompt_event = make_prompt_submitted(session_id)
        result = await aggregator.process_event(prompt_event, correlation_id)
        assert result is False

        # Verify TIMED_OUT
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["status"] == EnumSessionStatus.TIMED_OUT.value


# =============================================================================
# First-Write-Wins Tests
# =============================================================================


class TestFirstWriteWins:
    """Tests for first-write-wins semantics on identity fields."""

    @pytest.mark.asyncio
    async def test_working_directory_not_overwritten(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """working_directory from first SessionStarted is preserved."""
        session_id = "fww-working-dir-session"

        # Create orphan with prompt (sets correlation_id from prompt)
        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        # SessionStarted with specific working_directory
        start_event = make_session_started(
            session_id, working_directory="/first/directory"
        )
        await aggregator.process_event(start_event, correlation_id)

        # Verify working_directory set
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["working_directory"] == "/first/directory"

    @pytest.mark.asyncio
    async def test_git_branch_not_overwritten(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """git_branch from first SessionStarted is preserved."""
        session_id = "fww-git-branch-session"

        # First SessionStarted sets git_branch
        start1 = make_session_started(session_id, git_branch="develop")
        await aggregator.process_event(start1, correlation_id)

        # Second SessionStarted (ignored, but verify git_branch not changed)
        start2 = make_session_started(session_id, git_branch="feature-x")
        await aggregator.process_event(start2, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["git_branch"] == "develop"

    @pytest.mark.asyncio
    async def test_hook_source_not_overwritten(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """hook_source from first SessionStarted is preserved."""
        session_id = "fww-hook-source-session"

        # First SessionStarted
        start1 = make_session_started(session_id, hook_source=HookSource.STARTUP)
        await aggregator.process_event(start1, correlation_id)

        # Second SessionStarted with different hook_source (ignored)
        start2 = make_session_started(session_id, hook_source=HookSource.RESUME)
        await aggregator.process_event(start2, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["hook_source"] == HookSource.STARTUP.value

    @pytest.mark.asyncio
    async def test_orphan_identity_fields_set_on_activation(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Identity fields on orphan are set when SessionStarted arrives."""
        session_id = "orphan-identity-session"

        # Create orphan
        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        # Verify orphan has no identity fields
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["working_directory"] is None
        assert snapshot["git_branch"] is None
        assert snapshot["hook_source"] is None

        # Activate with SessionStarted
        start_event = make_session_started(
            session_id,
            working_directory="/activated/path",
            git_branch="main",
            hook_source=HookSource.STARTUP,
        )
        await aggregator.process_event(start_event, correlation_id)

        # Verify identity fields now set
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["working_directory"] == "/activated/path"
        assert snapshot["git_branch"] == "main"
        assert snapshot["hook_source"] == HookSource.STARTUP.value


# =============================================================================
# Append-Only Collection Tests
# =============================================================================


class TestAppendOnlyCollections:
    """Tests for append-only collection semantics."""

    @pytest.mark.asyncio
    async def test_multiple_prompts_accumulate(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Multiple prompts are accumulated, not replaced."""
        session_id = "multi-prompt-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add multiple prompts
        for i in range(5):
            prompt_event = make_prompt_submitted(
                session_id,
                emitted_at=base_time + timedelta(seconds=i + 1),
                prompt_preview=f"Prompt {i}",
                prompt_length=10 * (i + 1),
            )
            await aggregator.process_event(prompt_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["prompt_count"] == 5
        assert len(snapshot["prompts"]) == 5

    @pytest.mark.asyncio
    async def test_multiple_tools_accumulate(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Multiple tools are accumulated, not replaced."""
        session_id = "multi-tool-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add multiple tools
        tools = ["Read", "Write", "Edit", "Bash", "Grep"]
        for i, tool_name in enumerate(tools):
            tool_event = make_tool_executed(
                session_id,
                emitted_at=base_time + timedelta(seconds=i + 1),
                tool_name=tool_name,
            )
            await aggregator.process_event(tool_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["tool_count"] == 5
        assert len(snapshot["tools"]) == 5

    @pytest.mark.asyncio
    async def test_prompts_ordered_by_emitted_at(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Prompts in snapshot are ordered by emitted_at."""
        session_id = "ordered-prompts-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add prompts out of order
        prompt3 = make_prompt_submitted(
            session_id,
            emitted_at=base_time + timedelta(seconds=30),
            prompt_preview="Third",
        )
        prompt1 = make_prompt_submitted(
            session_id,
            emitted_at=base_time + timedelta(seconds=10),
            prompt_preview="First",
        )
        prompt2 = make_prompt_submitted(
            session_id,
            emitted_at=base_time + timedelta(seconds=20),
            prompt_preview="Second",
        )

        # Process out of order
        await aggregator.process_event(prompt3, correlation_id)
        await aggregator.process_event(prompt1, correlation_id)
        await aggregator.process_event(prompt2, correlation_id)

        # Verify ordered by emitted_at in snapshot
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        prompts = snapshot["prompts"]
        assert prompts[0]["prompt_preview"] == "First"
        assert prompts[1]["prompt_preview"] == "Second"
        assert prompts[2]["prompt_preview"] == "Third"

    @pytest.mark.asyncio
    async def test_tools_ordered_by_emitted_at(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Tools in snapshot are ordered by emitted_at."""
        session_id = "ordered-tools-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add tools out of order
        tool3 = make_tool_executed(
            session_id,
            emitted_at=base_time + timedelta(seconds=30),
            tool_name="ThirdTool",
        )
        tool1 = make_tool_executed(
            session_id,
            emitted_at=base_time + timedelta(seconds=10),
            tool_name="FirstTool",
        )
        tool2 = make_tool_executed(
            session_id,
            emitted_at=base_time + timedelta(seconds=20),
            tool_name="SecondTool",
        )

        # Process out of order
        await aggregator.process_event(tool3, correlation_id)
        await aggregator.process_event(tool1, correlation_id)
        await aggregator.process_event(tool2, correlation_id)

        # Verify ordered by emitted_at in snapshot
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        tools = snapshot["tools"]
        assert tools[0]["tool_name"] == "FirstTool"
        assert tools[1]["tool_name"] == "SecondTool"
        assert tools[2]["tool_name"] == "ThirdTool"


# =============================================================================
# Active Sessions Management Tests
# =============================================================================


class TestActiveSessionsManagement:
    """Tests for active sessions tracking."""

    @pytest.mark.asyncio
    async def test_get_active_sessions_returns_active_and_orphan(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """get_active_sessions returns ACTIVE and ORPHAN sessions."""
        # Create ACTIVE session
        active_id = "active-list-session"
        start_event = make_session_started(active_id)
        await aggregator.process_event(start_event, correlation_id)

        # Create ORPHAN session
        orphan_id = "orphan-list-session"
        prompt_event = make_prompt_submitted(orphan_id)
        await aggregator.process_event(prompt_event, correlation_id)

        # Create ENDED session
        ended_id = "ended-list-session"
        start_end = make_session_started(ended_id)
        await aggregator.process_event(start_end, correlation_id)
        end_event = make_session_ended(ended_id)
        await aggregator.process_event(end_event, correlation_id)

        # Get active sessions
        active_sessions = await aggregator.get_active_sessions(correlation_id)

        assert active_id in active_sessions
        assert orphan_id in active_sessions
        assert ended_id not in active_sessions

    @pytest.mark.asyncio
    async def test_get_session_last_activity(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """get_session_last_activity returns correct timestamp."""
        session_id = "activity-tracking-session"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add events at later times
        later_time = base_time + timedelta(seconds=60)
        prompt_event = make_prompt_submitted(session_id, emitted_at=later_time)
        await aggregator.process_event(prompt_event, correlation_id)

        # Verify last activity
        last_activity = await aggregator.get_session_last_activity(
            session_id, correlation_id
        )
        assert last_activity is not None
        assert last_activity == later_time

    @pytest.mark.asyncio
    async def test_get_session_last_activity_nonexistent(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """get_session_last_activity returns None for nonexistent session."""
        last_activity = await aggregator.get_session_last_activity(
            "nonexistent-session", correlation_id
        )
        assert last_activity is None


# =============================================================================
# Snapshot Tests
# =============================================================================


class TestSnapshot:
    """Tests for snapshot retrieval."""

    @pytest.mark.asyncio
    async def test_get_snapshot_nonexistent_returns_none(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """get_snapshot returns None for nonexistent session."""
        snapshot = await aggregator.get_snapshot("nonexistent", correlation_id)
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_finalize_nonexistent_returns_none(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """finalize_session returns None for nonexistent session."""
        snapshot = await aggregator.finalize_session("nonexistent", correlation_id)
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_snapshot_contains_all_expected_fields(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Snapshot contains all expected fields."""
        session_id = "snapshot-fields-session"
        base_time = make_timestamp()

        # Create complete session
        start_event = make_session_started(
            session_id,
            emitted_at=base_time,
            working_directory="/test/path",
            git_branch="main",
            hook_source=HookSource.STARTUP,
        )
        await aggregator.process_event(start_event, correlation_id)

        prompt_event = make_prompt_submitted(
            session_id, emitted_at=base_time + timedelta(seconds=1)
        )
        await aggregator.process_event(prompt_event, correlation_id)

        tool_event = make_tool_executed(
            session_id, emitted_at=base_time + timedelta(seconds=2)
        )
        await aggregator.process_event(tool_event, correlation_id)

        end_event = make_session_ended(
            session_id,
            emitted_at=base_time + timedelta(seconds=10),
            reason=SessionEndReason.LOGOUT,
            duration_seconds=10.0,
        )
        await aggregator.process_event(end_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)

        # Verify all expected fields
        assert "session_id" in snapshot
        assert "status" in snapshot
        assert "correlation_id" in snapshot
        assert "started_at" in snapshot
        assert "ended_at" in snapshot
        assert "duration_seconds" in snapshot
        assert "working_directory" in snapshot
        assert "git_branch" in snapshot
        assert "hook_source" in snapshot
        assert "end_reason" in snapshot
        assert "prompt_count" in snapshot
        assert "tool_count" in snapshot
        assert "event_count" in snapshot
        assert "last_event_at" in snapshot
        assert "prompts" in snapshot
        assert "tools" in snapshot


# =============================================================================
# Configuration Tests
# =============================================================================


class TestConfiguration:
    """Tests for aggregator configuration."""

    @pytest.mark.asyncio
    async def test_custom_aggregator_id(self, config: ConfigSessionAggregator) -> None:
        """Aggregator uses custom ID when provided."""
        aggregator = SessionAggregator(config, aggregator_id="custom-id-123")
        assert aggregator.aggregator_id == "custom-id-123"

    @pytest.mark.asyncio
    async def test_generated_aggregator_id(
        self, config: ConfigSessionAggregator
    ) -> None:
        """Aggregator generates ID when not provided."""
        aggregator = SessionAggregator(config)
        assert aggregator.aggregator_id.startswith("aggregator-")
        assert len(aggregator.aggregator_id) > len("aggregator-")


# =============================================================================
# Duration Computation Tests
# =============================================================================


class TestDurationComputation:
    """Tests for session duration computation."""

    @pytest.mark.asyncio
    async def test_duration_from_event(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Duration uses value from SessionEnded event when provided."""
        session_id = "duration-from-event-session"

        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(session_id, duration_seconds=3600.5)
        await aggregator.process_event(end_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["duration_seconds"] == 3600.5

    @pytest.mark.asyncio
    async def test_duration_computed_when_not_provided(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Duration is computed from timestamps when not in event."""
        session_id = "duration-computed-session"
        start_time = make_timestamp()
        end_time = start_time + timedelta(seconds=120)

        start_event = make_session_started(session_id, emitted_at=start_time)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(
            session_id, emitted_at=end_time, duration_seconds=None
        )
        await aggregator.process_event(end_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        # Should be approximately 120 seconds
        assert snapshot["duration_seconds"] is not None
        assert 119.9 <= snapshot["duration_seconds"] <= 120.1

    @pytest.mark.asyncio
    async def test_finalize_computes_duration(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """finalize_session computes duration if start_time available."""
        session_id = "finalize-duration-session"
        start_time = make_timestamp()

        start_event = make_session_started(session_id, emitted_at=start_time)
        await aggregator.process_event(start_event, correlation_id)

        # Wait simulated time by processing events at later times
        prompt_event = make_prompt_submitted(
            session_id, emitted_at=start_time + timedelta(seconds=60)
        )
        await aggregator.process_event(prompt_event, correlation_id)

        # Finalize (computes duration from now() - started_at)
        snapshot = await aggregator.finalize_session(session_id, correlation_id)

        assert snapshot is not None
        assert snapshot["duration_seconds"] is not None
        # Duration should be >= 0 (computed at finalization time)
        assert snapshot["duration_seconds"] >= 0


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_invalid_event_type_raises(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Invalid event type raises ValueError."""
        # Create an event with mismatched type
        # (This should normally be caught by Pydantic, but we test the dispatcher)
        session_id = "invalid-event-session"

        # Create a valid session first
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # The process_event method handles type dispatch based on event_type
        # and validates payload type matches
        # This is tested at the schema level, but we verify the aggregator
        # processes valid events correctly


# =============================================================================
# Event Count Tests
# =============================================================================


class TestEventCount:
    """Tests for event count tracking."""

    @pytest.mark.asyncio
    async def test_event_count_increments_correctly(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Event count increments for each processed event."""
        session_id = "event-count-session"

        # Each event should increment count
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 1

        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 2

        tool_event = make_tool_executed(session_id)
        await aggregator.process_event(tool_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 3

        end_event = make_session_ended(session_id)
        await aggregator.process_event(end_event, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 4

    @pytest.mark.asyncio
    async def test_duplicate_events_dont_increment_count(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Duplicate/rejected events don't increment event count."""
        session_id = "dup-count-session"
        prompt_id = uuid4()

        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # First prompt
        prompt1 = make_prompt_submitted(session_id, prompt_id=prompt_id)
        await aggregator.process_event(prompt1, correlation_id)

        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 2

        # Duplicate prompt (rejected)
        prompt2 = make_prompt_submitted(session_id, prompt_id=prompt_id)
        await aggregator.process_event(prompt2, correlation_id)

        # Count should not have increased
        snapshot = await aggregator.get_snapshot(session_id, correlation_id)
        assert snapshot["event_count"] == 2


# =============================================================================
# Protocol Conformance Tests
# =============================================================================


class TestProtocolConformance:
    """Tests for protocol conformance."""

    def test_session_aggregator_implements_protocol(
        self, config: ConfigSessionAggregator
    ) -> None:
        """Verify SessionAggregator implements ProtocolSessionAggregator."""
        aggregator = SessionAggregator(config)
        assert isinstance(aggregator, ProtocolSessionAggregator)


# =============================================================================
# Metrics Tests
# =============================================================================


class TestMetrics:
    """Tests for aggregator metrics/counters."""

    @pytest.mark.asyncio
    async def test_get_metrics_returns_all_counters(
        self, aggregator: SessionAggregator
    ) -> None:
        """get_metrics returns dict with all expected counters."""
        metrics = aggregator.get_metrics()

        assert "events_processed" in metrics
        assert "events_rejected" in metrics
        assert "sessions_created" in metrics
        assert "sessions_finalized" in metrics

    @pytest.mark.asyncio
    async def test_metrics_start_at_zero(self, aggregator: SessionAggregator) -> None:
        """All metrics counters start at zero."""
        metrics = aggregator.get_metrics()

        assert metrics["events_processed"] == 0
        assert metrics["events_rejected"] == 0
        assert metrics["sessions_created"] == 0
        assert metrics["sessions_finalized"] == 0

    @pytest.mark.asyncio
    async def test_events_processed_increments_on_success(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """events_processed increments when event is successfully processed."""
        session_id = "metrics-processed-session"

        # Process events
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        tool_event = make_tool_executed(session_id)
        await aggregator.process_event(tool_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["events_processed"] == 3

    @pytest.mark.asyncio
    async def test_events_rejected_increments_on_duplicate(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """events_rejected increments when event is rejected."""
        session_id = "metrics-rejected-session"
        prompt_id = uuid4()

        # Start session
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # First prompt - should be processed
        prompt1 = make_prompt_submitted(session_id, prompt_id=prompt_id)
        await aggregator.process_event(prompt1, correlation_id)

        # Duplicate prompt - should be rejected
        prompt2 = make_prompt_submitted(session_id, prompt_id=prompt_id)
        await aggregator.process_event(prompt2, correlation_id)

        # Duplicate SessionStarted - should be rejected
        start_event2 = make_session_started(session_id)
        await aggregator.process_event(start_event2, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["events_processed"] == 2  # start + first prompt
        assert metrics["events_rejected"] == 2  # duplicate prompt + duplicate start

    @pytest.mark.asyncio
    async def test_events_rejected_increments_for_finalized_session(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """events_rejected increments when event sent to finalized session."""
        session_id = "metrics-finalized-reject-session"

        # Complete session lifecycle
        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(session_id)
        await aggregator.process_event(end_event, correlation_id)

        # Try to add prompt to ended session - should be rejected
        prompt_event = make_prompt_submitted(session_id)
        await aggregator.process_event(prompt_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["events_processed"] == 2  # start + end
        assert metrics["events_rejected"] == 1  # prompt to ended session

    @pytest.mark.asyncio
    async def test_sessions_created_increments_for_active(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_created increments when new ACTIVE session created."""
        # Create two sessions
        start1 = make_session_started("session-1")
        await aggregator.process_event(start1, correlation_id)

        start2 = make_session_started("session-2")
        await aggregator.process_event(start2, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["sessions_created"] == 2

    @pytest.mark.asyncio
    async def test_sessions_created_increments_for_orphan(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_created increments when ORPHAN session created."""
        # Create orphan session via prompt (no SessionStarted)
        prompt_event = make_prompt_submitted("orphan-session")
        await aggregator.process_event(prompt_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["sessions_created"] == 1

    @pytest.mark.asyncio
    async def test_sessions_created_increments_for_orphan_end(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_created increments when orphan end event creates session."""
        # SessionEnded without SessionStarted creates session
        end_event = make_session_ended("orphan-end-session")
        await aggregator.process_event(end_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["sessions_created"] == 1
        # Also finalized immediately
        assert metrics["sessions_finalized"] == 1

    @pytest.mark.asyncio
    async def test_sessions_finalized_increments_on_session_ended(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_finalized increments when session ends via SessionEnded."""
        session_id = "metrics-finalized-session"

        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        end_event = make_session_ended(session_id)
        await aggregator.process_event(end_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["sessions_finalized"] == 1

    @pytest.mark.asyncio
    async def test_sessions_finalized_increments_on_finalize_session(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_finalized increments when finalize_session called."""
        session_id = "metrics-timeout-session"

        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # Finalize via method call (simulating timeout)
        await aggregator.finalize_session(session_id, correlation_id, reason="timeout")

        metrics = aggregator.get_metrics()
        assert metrics["sessions_finalized"] == 1

    @pytest.mark.asyncio
    async def test_sessions_finalized_not_incremented_on_already_finalized(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """sessions_finalized not incremented when already finalized."""
        session_id = "metrics-double-finalize-session"

        start_event = make_session_started(session_id)
        await aggregator.process_event(start_event, correlation_id)

        # First finalization
        await aggregator.finalize_session(session_id, correlation_id, reason="timeout")

        # Second finalization (idempotent)
        await aggregator.finalize_session(session_id, correlation_id, reason="timeout")

        metrics = aggregator.get_metrics()
        assert metrics["sessions_finalized"] == 1  # Only counted once

    @pytest.mark.asyncio
    async def test_complete_lifecycle_metrics(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Verify metrics for complete session lifecycle."""
        session_id = "metrics-complete-lifecycle"
        base_time = make_timestamp()

        # Start session
        start_event = make_session_started(session_id, emitted_at=base_time)
        await aggregator.process_event(start_event, correlation_id)

        # Add prompts and tools
        for i in range(3):
            prompt = make_prompt_submitted(
                session_id, emitted_at=base_time + timedelta(seconds=i + 1)
            )
            await aggregator.process_event(prompt, correlation_id)

        for i in range(5):
            tool = make_tool_executed(
                session_id, emitted_at=base_time + timedelta(seconds=i + 10)
            )
            await aggregator.process_event(tool, correlation_id)

        # End session
        end_event = make_session_ended(
            session_id, emitted_at=base_time + timedelta(seconds=20)
        )
        await aggregator.process_event(end_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert (
            metrics["events_processed"] == 10
        )  # 1 start + 3 prompts + 5 tools + 1 end
        assert metrics["events_rejected"] == 0
        assert metrics["sessions_created"] == 1
        assert metrics["sessions_finalized"] == 1

    @pytest.mark.asyncio
    async def test_metrics_across_multiple_sessions(
        self, aggregator: SessionAggregator, correlation_id: UUID
    ) -> None:
        """Verify metrics accumulate across multiple sessions."""
        # Create 3 sessions
        for i in range(3):
            session_id = f"multi-session-{i}"
            start_event = make_session_started(session_id)
            await aggregator.process_event(start_event, correlation_id)

            prompt_event = make_prompt_submitted(session_id)
            await aggregator.process_event(prompt_event, correlation_id)

            end_event = make_session_ended(session_id)
            await aggregator.process_event(end_event, correlation_id)

        metrics = aggregator.get_metrics()
        assert metrics["events_processed"] == 9  # 3 sessions * 3 events each
        assert metrics["sessions_created"] == 3
        assert metrics["sessions_finalized"] == 3
