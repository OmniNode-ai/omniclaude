# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Session event aggregator implementation.

Aggregates Claude Code hook events into session snapshots following
the aggregation contract semantics defined in ProtocolSessionAggregator.

Key Semantics:
    - Idempotency: Events deduplicated via natural keys (event_id, prompt_id,
      tool_execution_id). Processing the same event twice has no effect.
    - First-Write-Wins: Identity fields (working_directory, git_branch,
      hook_source) are set from the first event and never overwritten.
    - Append-Only: Event collections (prompts, tools) are append-only
      with deduplication by natural key.
    - Timeout-Based Finalization: Sessions without explicit end events
      are finalized after inactivity timeout.

State Machine:
    [No Session] ---(any event)---> ORPHAN
    ORPHAN ---(SessionStarted)---> ACTIVE
    ACTIVE ---(SessionEnded)---> ENDED
    ACTIVE ---(timeout)---> TIMED_OUT
    ORPHAN ---(timeout)---> TIMED_OUT

    Terminal states (ENDED, TIMED_OUT) reject further events.

Thread Safety:
    Uses per-session asyncio.Lock instances for state modifications.
    Concurrent calls for different sessions proceed in parallel without
    blocking each other; calls for the same session are serialized.

Related Tickets:
    - OMN-1401: Session storage in OmniMemory (current)
    - OMN-1489: Core models in omnibase_core (snapshot model)

Example:
    >>> from uuid import uuid4
    >>> from omniclaude.aggregators import ConfigSessionAggregator
    >>> from omniclaude.aggregators.session_aggregator import SessionAggregator
    >>>
    >>> config = ConfigSessionAggregator()
    >>> aggregator = SessionAggregator(config)
    >>> print(f"Aggregator ID: {aggregator.aggregator_id}")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from omniclaude.aggregators.config import ConfigSessionAggregator
from omniclaude.aggregators.enums import EnumSessionStatus
from omniclaude.hooks.schemas import (
    HookEventType,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Internal State Models
# =============================================================================


@dataclass
class PromptRecord:
    """Record of a prompt submitted during a session.

    This is internal working state, not the final snapshot model.
    Natural key: prompt_id (used for deduplication).
    """

    prompt_id: UUID
    emitted_at: datetime
    prompt_preview: str
    prompt_length: int
    detected_intent: str | None
    causation_id: UUID | None


@dataclass
class ToolRecord:
    """Record of a tool execution during a session.

    This is internal working state, not the final snapshot model.
    Natural key: tool_execution_id (used for deduplication).
    """

    tool_execution_id: UUID
    emitted_at: datetime
    tool_name: str
    success: bool
    duration_ms: int | None
    summary: str | None
    causation_id: UUID | None


@dataclass
class SessionState:
    """Mutable aggregation state for a session.

    This is NOT the final snapshot model - that comes from omnibase_core (OMN-1489).
    This is working state that gets converted to a snapshot on finalization.

    Identity fields (working_directory, git_branch, hook_source) follow
    first-write-wins semantics - once set, they are never overwritten.

    Collections (prompts, tools) are append-only, keyed by natural ID
    for deduplication.

    Idempotency Strategy:
        - SessionStarted: One per session, tracked via has_session_started flag
        - SessionEnded: One per session, tracked via terminal status
        - PromptSubmitted: Natural key is prompt_id (dict key deduplication)
        - ToolExecuted: Natural key is tool_execution_id (dict key deduplication)

    Attributes:
        session_id: The Claude Code session identifier.
        status: Current session status in the state machine.
        correlation_id: Correlation ID from the first event.
        has_session_started: Whether SessionStarted event was processed.
        started_at: Timestamp when session started (from SessionStarted).
        ended_at: Timestamp when session ended (from SessionEnded or timeout).
        duration_seconds: Computed duration (ended_at - started_at).
        working_directory: Working directory (first-write-wins).
        git_branch: Git branch (first-write-wins).
        hook_source: Hook source (first-write-wins).
        end_reason: Reason for session end.
        prompts: Prompt records keyed by prompt_id (append-only).
        tools: Tool records keyed by tool_execution_id (append-only).
        last_event_at: Timestamp of most recent event (for timeout).
        event_count: Total events processed for this session.
    """

    session_id: str
    status: EnumSessionStatus
    correlation_id: UUID | None = None
    has_session_started: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    working_directory: str | None = None
    git_branch: str | None = None
    hook_source: str | None = None
    end_reason: str | None = None
    prompts: dict[UUID, PromptRecord] = field(default_factory=dict)
    tools: dict[UUID, ToolRecord] = field(default_factory=dict)
    last_event_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_count: int = 0


# =============================================================================
# Session Aggregator Implementation
# =============================================================================


class SessionAggregator:
    """Aggregates session events into snapshots.

    Implements ProtocolSessionAggregator with in-memory state.
    State persistence is delegated to a storage adapter (separate concern).

    The aggregator follows the aggregation contract semantics:
    - Idempotency via event_id deduplication
    - First-write-wins for identity fields
    - Append-only for collections
    - Status state machine enforcement
    - Out-of-order event handling within buffer window

    Type Parameters:
        This implementation uses dict[str, Any] for snapshots until
        the concrete ModelClaudeCodeSessionSnapshot is available from
        omnibase_core (OMN-1489).

    Attributes:
        aggregator_id: Unique identifier for this aggregator instance.

    Example:
        >>> config = ConfigSessionAggregator()
        >>> aggregator = SessionAggregator(config, aggregator_id="worker-1")
        >>> # Process events...
        >>> snapshot = await aggregator.get_snapshot("session-123", uuid4())
    """

    def __init__(
        self,
        config: ConfigSessionAggregator,
        aggregator_id: str | None = None,
    ) -> None:
        """Initialize the session aggregator.

        Args:
            config: Configuration for aggregation behavior (timeouts, etc.).
            aggregator_id: Optional unique identifier. If not provided,
                generates one with format "aggregator-{random_hex}".
        """
        self._config = config
        self._aggregator_id = aggregator_id or f"aggregator-{uuid4().hex[:8]}"
        self._sessions: dict[str, SessionState] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()  # Lock for accessing the locks dict

        logger.info(
            "SessionAggregator initialized",
            extra={
                "aggregator_id": self._aggregator_id,
                "inactivity_timeout": config.session_inactivity_timeout_seconds,
                "out_of_order_buffer": config.out_of_order_buffer_seconds,
            },
        )

    @property
    def aggregator_id(self) -> str:
        """Unique identifier for this aggregator instance.

        Used for logging, tracing, and distributed coordination.
        """
        return self._aggregator_id

    # =========================================================================
    # Protocol Implementation: process_event
    # =========================================================================

    async def process_event(
        self,
        event: ModelHookEventEnvelope,
        correlation_id: UUID,
    ) -> bool:
        """Process a single event into session state.

        Handles all event types (SessionStarted, SessionEnded, PromptSubmitted,
        ToolExecuted) and updates the appropriate session snapshot accordingly.

        Idempotency:
            Events are deduplicated using entity_id from the payload.
            For prompts and tools, natural keys (prompt_id, tool_execution_id)
            also prevent duplicate entries.

        State Transitions:
            - SessionStarted: Creates ACTIVE session or transitions ORPHAN -> ACTIVE
            - SessionEnded: Transitions ACTIVE -> ENDED
            - Other events: Added to existing session, or create ORPHAN if none exists

        Args:
            event: The hook event envelope to process.
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            True if the event was successfully processed and state was modified.
            False if the event was rejected (duplicate, finalized session, etc.).

        Raises:
            ValueError: If the event has an unknown event_type.
        """
        payload = event.payload
        session_id = payload.session_id

        logger.debug(
            "Processing event",
            extra={
                "event_type": event.event_type.value,
                "session_id": session_id,
                "correlation_id": str(correlation_id),
                "aggregator_id": self._aggregator_id,
            },
        )

        # Dispatch to appropriate handler based on event type
        if event.event_type == HookEventType.SESSION_STARTED:
            if not isinstance(payload, ModelHookSessionStartedPayload):
                raise ValueError(
                    f"Expected ModelHookSessionStartedPayload, got {type(payload).__name__}"
                )
            return await self._handle_session_started(payload, correlation_id)

        elif event.event_type == HookEventType.SESSION_ENDED:
            if not isinstance(payload, ModelHookSessionEndedPayload):
                raise ValueError(
                    f"Expected ModelHookSessionEndedPayload, got {type(payload).__name__}"
                )
            return await self._handle_session_ended(payload, correlation_id)

        elif event.event_type == HookEventType.PROMPT_SUBMITTED:
            if not isinstance(payload, ModelHookPromptSubmittedPayload):
                raise ValueError(
                    f"Expected ModelHookPromptSubmittedPayload, got {type(payload).__name__}"
                )
            return await self._handle_prompt_submitted(payload, correlation_id)

        elif event.event_type == HookEventType.TOOL_EXECUTED:
            if not isinstance(payload, ModelHookToolExecutedPayload):
                raise ValueError(
                    f"Expected ModelHookToolExecutedPayload, got {type(payload).__name__}"
                )
            return await self._handle_tool_executed(payload, correlation_id)

        else:
            raise ValueError(f"Unknown event type: {event.event_type}")

    # =========================================================================
    # Protocol Implementation: get_snapshot
    # =========================================================================

    async def get_snapshot(
        self,
        session_id: str,
        correlation_id: UUID,
    ) -> dict[str, Any] | None:
        """Get current snapshot for a session.

        Returns the current state of a session as a dictionary.
        The dictionary format will be replaced with ModelClaudeCodeSessionSnapshot
        when omnibase_core models are available (OMN-1489).

        Args:
            session_id: The Claude Code session ID.
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            Dictionary representation of the session snapshot, or None if
            the session does not exist.
        """
        lock = await self._get_session_lock(session_id)
        async with lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.debug(
                    "Session not found for snapshot",
                    extra={
                        "session_id": session_id,
                        "correlation_id": str(correlation_id),
                    },
                )
                return None

            return self._session_to_dict(session)

    # =========================================================================
    # Protocol Implementation: finalize_session
    # =========================================================================

    async def finalize_session(
        self,
        session_id: str,
        correlation_id: UUID,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Finalize and seal a session snapshot.

        Called when SessionEnded is received or timeout expires.
        After finalization, no further events are accepted for this session.

        Finalization performs:
        1. Sets session status to ENDED or TIMED_OUT
        2. Records finalization timestamp
        3. Computes final duration if start time is known
        4. Cleans up session resources (locks and state) to prevent memory leaks

        Idempotency:
            Calling finalize on an already-finalized session returns the
            existing snapshot and still performs cleanup.

        Args:
            session_id: The session to finalize.
            correlation_id: Correlation ID for distributed tracing.
            reason: Finalization reason (e.g., "timeout", "user_exit").
                If None, defaults to "unspecified".

        Returns:
            The final sealed snapshot as a dictionary, or None if session not found.
        """
        lock = await self._get_session_lock(session_id)
        async with lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.warning(
                    "Attempted to finalize non-existent session",
                    extra={
                        "session_id": session_id,
                        "correlation_id": str(correlation_id),
                    },
                )
                return None

            # Already finalized - capture snapshot but still cleanup
            if session.status in (EnumSessionStatus.ENDED, EnumSessionStatus.TIMED_OUT):
                logger.debug(
                    "Session already finalized, performing cleanup",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "correlation_id": str(correlation_id),
                    },
                )
                snapshot = self._session_to_dict(session)
            else:
                # Determine terminal status
                effective_reason = reason or "unspecified"
                if effective_reason == "timeout":
                    session.status = EnumSessionStatus.TIMED_OUT
                else:
                    session.status = EnumSessionStatus.ENDED

                session.end_reason = effective_reason
                session.ended_at = datetime.now(UTC)

                # Compute duration if we have start time
                if session.started_at is not None:
                    delta = session.ended_at - session.started_at
                    session.duration_seconds = delta.total_seconds()

                logger.info(
                    "Session finalized",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "reason": effective_reason,
                        "duration_seconds": session.duration_seconds,
                        "event_count": session.event_count,
                        "correlation_id": str(correlation_id),
                    },
                )

                snapshot = self._session_to_dict(session)

        # Clean up session lock after finalization (outside session lock)
        # This happens for both newly finalized and already-finalized sessions
        # Note: We only clean up the lock, not the state. This ensures events
        # for finalized sessions are rejected rather than creating orphans.
        await self._cleanup_session_lock_only(session_id)

        return snapshot

    # =========================================================================
    # Protocol Implementation: get_active_sessions
    # =========================================================================

    async def get_active_sessions(self, correlation_id: UUID) -> list[str]:
        """Get list of active (non-finalized) session IDs.

        Returns sessions with status ACTIVE or ORPHAN. These are candidates
        for timeout sweep processing.

        Args:
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            List of session IDs with non-terminal status.
        """
        async with self._locks_lock:
            active_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.status
                in (EnumSessionStatus.ACTIVE, EnumSessionStatus.ORPHAN)
            ]

            logger.debug(
                "Retrieved active sessions",
                extra={
                    "active_count": len(active_ids),
                    "total_count": len(self._sessions),
                    "correlation_id": str(correlation_id),
                },
            )

            return active_ids

    # =========================================================================
    # Protocol Implementation: get_session_last_activity
    # =========================================================================

    async def get_session_last_activity(
        self,
        session_id: str,
        correlation_id: UUID,
    ) -> datetime | None:
        """Get last activity timestamp for a session.

        Used by timeout sweep to determine if a session should be finalized.

        Args:
            session_id: The session to check.
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            Timestamp of the last event, or None if session not found.
        """
        lock = await self._get_session_lock(session_id)
        async with lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return session.last_event_at

    # =========================================================================
    # Protocol Implementation: cleanup_finalized_sessions
    # =========================================================================

    async def cleanup_finalized_sessions(
        self,
        correlation_id: UUID,
        older_than_seconds: float | None = None,
    ) -> int:
        """Clean up memory for finalized sessions.

        Removes session state and locks for sessions in terminal states
        (ENDED, TIMED_OUT). This should be called periodically by long-running
        consumers to prevent memory growth.

        After cleanup, any new events for these sessions will create orphan
        sessions (they won't be rejected as finalized). Only call this for
        sessions that are truly no longer needed.

        Args:
            correlation_id: Correlation ID for distributed tracing.
            older_than_seconds: If provided, only clean up sessions that have
                been in terminal state for at least this many seconds (based
                on last_event_at). If None, cleans up all finalized sessions.

        Returns:
            Number of sessions cleaned up.
        """
        from datetime import UTC, datetime, timedelta

        async with self._locks_lock:
            # Find all finalized sessions
            now = datetime.now(UTC)
            sessions_to_cleanup: list[str] = []

            for session_id, session in self._sessions.items():
                if session.status not in (
                    EnumSessionStatus.ENDED,
                    EnumSessionStatus.TIMED_OUT,
                ):
                    continue

                # Apply age filter if specified
                if older_than_seconds is not None:
                    age = (now - session.last_event_at).total_seconds()
                    if age < older_than_seconds:
                        continue

                sessions_to_cleanup.append(session_id)

            # Clean up the sessions
            for session_id in sessions_to_cleanup:
                self._sessions.pop(session_id, None)
                self._session_locks.pop(session_id, None)

        if sessions_to_cleanup:
            logger.info(
                "Cleaned up finalized sessions",
                extra={
                    "cleaned_count": len(sessions_to_cleanup),
                    "older_than_seconds": older_than_seconds,
                    "correlation_id": str(correlation_id),
                    "aggregator_id": self._aggregator_id,
                },
            )

        return len(sessions_to_cleanup)

    # =========================================================================
    # Private: Event Handlers
    # =========================================================================

    async def _handle_session_started(
        self,
        payload: ModelHookSessionStartedPayload,
        correlation_id: UUID,
    ) -> bool:
        """Handle SessionStarted event.

        Creates a new ACTIVE session or transitions an ORPHAN session to ACTIVE.
        Identity fields are set following first-write-wins semantics.

        Idempotency: Only one SessionStarted per session is accepted.

        Args:
            payload: The session started payload.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if processed, False if rejected (duplicate or finalized).
        """
        session_id = payload.session_id
        lock = await self._get_session_lock(session_id)
        async with lock:

            session = self._sessions.get(session_id)

            # Check if session exists and is finalized
            if session is not None and session.status in (
                EnumSessionStatus.ENDED,
                EnumSessionStatus.TIMED_OUT,
            ):
                logger.warning(
                    "Rejected SessionStarted for finalized session",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Check for duplicate SessionStarted (idempotency via flag)
            if session is not None and session.has_session_started:
                logger.debug(
                    "Duplicate SessionStarted event ignored",
                    extra={
                        "session_id": session_id,
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            if session is None:
                # Create new ACTIVE session
                session = SessionState(
                    session_id=session_id,
                    status=EnumSessionStatus.ACTIVE,
                    correlation_id=payload.correlation_id,
                    has_session_started=True,
                    started_at=payload.emitted_at,
                    working_directory=payload.working_directory,
                    git_branch=payload.git_branch,
                    hook_source=payload.hook_source.value,
                    last_event_at=payload.emitted_at,
                    event_count=1,
                )
                self._sessions[session_id] = session
                logger.info(
                    "New session started",
                    extra={
                        "session_id": session_id,
                        "working_directory": payload.working_directory,
                        "hook_source": payload.hook_source.value,
                        "correlation_id": str(correlation_id),
                    },
                )
            else:
                # Transition ORPHAN -> ACTIVE
                session.status = EnumSessionStatus.ACTIVE
                session.has_session_started = True
                session.started_at = payload.emitted_at

                # First-write-wins for identity fields
                if session.correlation_id is None:
                    session.correlation_id = payload.correlation_id
                if session.working_directory is None:
                    session.working_directory = payload.working_directory
                if session.git_branch is None:
                    session.git_branch = payload.git_branch
                if session.hook_source is None:
                    session.hook_source = payload.hook_source.value

                self._update_activity(session, payload.emitted_at)

                logger.info(
                    "Orphan session activated",
                    extra={
                        "session_id": session_id,
                        "prior_event_count": session.event_count - 1,
                        "correlation_id": str(correlation_id),
                    },
                )

            return True

    async def _handle_session_ended(
        self,
        payload: ModelHookSessionEndedPayload,
        correlation_id: UUID,
    ) -> bool:
        """Handle SessionEnded event.

        Transitions an ACTIVE session to ENDED status.

        Note: This method only transitions the status. Cleanup of session
        resources (locks, state) happens when finalize_session() is called.

        Idempotency: Only one SessionEnded per session is accepted.
        The terminal status check provides idempotency.

        Args:
            payload: The session ended payload.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if processed, False if rejected.
        """
        session_id = payload.session_id
        lock = await self._get_session_lock(session_id)
        async with lock:

            session = self._sessions.get(session_id)

            # Check if session exists
            if session is None:
                # Create orphan session that's immediately ended (unusual but handle it)
                session = SessionState(
                    session_id=session_id,
                    status=EnumSessionStatus.ENDED,
                    correlation_id=payload.correlation_id,
                    ended_at=payload.emitted_at,
                    end_reason=payload.reason.value,
                    duration_seconds=payload.duration_seconds,
                    last_event_at=payload.emitted_at,
                    event_count=1,
                )
                self._sessions[session_id] = session
                logger.warning(
                    "Session ended without start (orphan end)",
                    extra={
                        "session_id": session_id,
                        "reason": payload.reason.value,
                        "correlation_id": str(correlation_id),
                    },
                )
                return True

            # Check if already finalized (provides idempotency for SessionEnded)
            if session.status in (
                EnumSessionStatus.ENDED,
                EnumSessionStatus.TIMED_OUT,
            ):
                logger.debug(
                    "Duplicate SessionEnded ignored (already finalized)",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Transition to ENDED
            session.status = EnumSessionStatus.ENDED
            session.ended_at = payload.emitted_at
            session.end_reason = payload.reason.value

            # Compute duration from event if provided, otherwise calculate
            if payload.duration_seconds is not None:
                session.duration_seconds = payload.duration_seconds
            elif session.started_at is not None:
                delta = payload.emitted_at - session.started_at
                session.duration_seconds = delta.total_seconds()

            self._update_activity(session, payload.emitted_at)

            logger.info(
                "Session ended",
                extra={
                    "session_id": session_id,
                    "reason": payload.reason.value,
                    "duration_seconds": session.duration_seconds,
                    "prompt_count": len(session.prompts),
                    "tool_count": len(session.tools),
                    "correlation_id": str(correlation_id),
                },
            )

            return True

    async def _handle_prompt_submitted(
        self,
        payload: ModelHookPromptSubmittedPayload,
        correlation_id: UUID,
    ) -> bool:
        """Handle PromptSubmitted event.

        Adds prompt record to session. Creates ORPHAN session if none exists.

        Idempotency: Natural key is prompt_id. Duplicate prompt_ids are rejected.

        Args:
            payload: The prompt submitted payload.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if processed, False if rejected.
        """
        session_id = payload.session_id
        prompt_id = payload.prompt_id
        lock = await self._get_session_lock(session_id)
        async with lock:

            session = self._sessions.get(session_id)

            # Create orphan session if none exists
            if session is None:
                session = self._create_orphan_session(
                    session_id, payload.correlation_id, payload.emitted_at
                )
                self._sessions[session_id] = session
                logger.debug(
                    "Created orphan session for prompt",
                    extra={
                        "session_id": session_id,
                        "prompt_id": str(prompt_id),
                        "correlation_id": str(correlation_id),
                    },
                )

            # Check if finalized
            if session.status in (
                EnumSessionStatus.ENDED,
                EnumSessionStatus.TIMED_OUT,
            ):
                logger.warning(
                    "Rejected prompt for finalized session",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "prompt_id": str(prompt_id),
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Check for duplicate prompt (natural key idempotency)
            if prompt_id in session.prompts:
                logger.debug(
                    "Duplicate prompt_id ignored",
                    extra={
                        "session_id": session_id,
                        "prompt_id": str(prompt_id),
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Check out-of-order buffer
            if not self._is_within_buffer(session, payload.emitted_at):
                logger.warning(
                    "Prompt outside out-of-order buffer",
                    extra={
                        "session_id": session_id,
                        "prompt_id": str(prompt_id),
                        "event_time": payload.emitted_at.isoformat(),
                        "last_event_time": session.last_event_at.isoformat(),
                        "correlation_id": str(correlation_id),
                    },
                )
                # Still process - just log the warning

            # Add prompt record (append-only)
            prompt_record = PromptRecord(
                prompt_id=prompt_id,
                emitted_at=payload.emitted_at,
                prompt_preview=payload.prompt_preview,
                prompt_length=payload.prompt_length,
                detected_intent=payload.detected_intent,
                causation_id=payload.causation_id,
            )
            session.prompts[prompt_id] = prompt_record
            self._update_activity(session, payload.emitted_at)

            logger.debug(
                "Prompt added to session",
                extra={
                    "session_id": session_id,
                    "prompt_id": str(prompt_id),
                    "prompt_count": len(session.prompts),
                    "correlation_id": str(correlation_id),
                },
            )

            return True

    async def _handle_tool_executed(
        self,
        payload: ModelHookToolExecutedPayload,
        correlation_id: UUID,
    ) -> bool:
        """Handle ToolExecuted event.

        Adds tool record to session. Creates ORPHAN session if none exists.

        Idempotency: Natural key is tool_execution_id. Duplicates are rejected.

        Args:
            payload: The tool executed payload.
            correlation_id: Correlation ID for tracing.

        Returns:
            True if processed, False if rejected.
        """
        session_id = payload.session_id
        tool_execution_id = payload.tool_execution_id
        lock = await self._get_session_lock(session_id)
        async with lock:

            session = self._sessions.get(session_id)

            # Create orphan session if none exists
            if session is None:
                session = self._create_orphan_session(
                    session_id, payload.correlation_id, payload.emitted_at
                )
                self._sessions[session_id] = session
                logger.debug(
                    "Created orphan session for tool execution",
                    extra={
                        "session_id": session_id,
                        "tool_execution_id": str(tool_execution_id),
                        "tool_name": payload.tool_name,
                        "correlation_id": str(correlation_id),
                    },
                )

            # Check if finalized
            if session.status in (
                EnumSessionStatus.ENDED,
                EnumSessionStatus.TIMED_OUT,
            ):
                logger.warning(
                    "Rejected tool execution for finalized session",
                    extra={
                        "session_id": session_id,
                        "status": session.status.value,
                        "tool_execution_id": str(tool_execution_id),
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Check for duplicate tool execution (natural key idempotency)
            if tool_execution_id in session.tools:
                logger.debug(
                    "Duplicate tool_execution_id ignored",
                    extra={
                        "session_id": session_id,
                        "tool_execution_id": str(tool_execution_id),
                        "correlation_id": str(correlation_id),
                    },
                )
                return False

            # Check out-of-order buffer
            if not self._is_within_buffer(session, payload.emitted_at):
                logger.warning(
                    "Tool execution outside out-of-order buffer",
                    extra={
                        "session_id": session_id,
                        "tool_execution_id": str(tool_execution_id),
                        "event_time": payload.emitted_at.isoformat(),
                        "last_event_time": session.last_event_at.isoformat(),
                        "correlation_id": str(correlation_id),
                    },
                )
                # Still process - just log the warning

            # Add tool record (append-only)
            tool_record = ToolRecord(
                tool_execution_id=tool_execution_id,
                emitted_at=payload.emitted_at,
                tool_name=payload.tool_name,
                success=payload.success,
                duration_ms=payload.duration_ms,
                summary=payload.summary,
                causation_id=payload.causation_id,
            )
            session.tools[tool_execution_id] = tool_record
            self._update_activity(session, payload.emitted_at)

            logger.debug(
                "Tool execution added to session",
                extra={
                    "session_id": session_id,
                    "tool_execution_id": str(tool_execution_id),
                    "tool_name": payload.tool_name,
                    "tool_count": len(session.tools),
                    "correlation_id": str(correlation_id),
                },
            )

            return True

    # =========================================================================
    # Private: Helper Methods
    # =========================================================================

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific session.

        This enables per-session locking to reduce contention when processing
        events for different sessions concurrently.

        Args:
            session_id: The session identifier to get a lock for.

        Returns:
            The asyncio.Lock for the specified session.
        """
        async with self._locks_lock:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = asyncio.Lock()
            return self._session_locks[session_id]

    def _cleanup_session_lock(self, session_id: str) -> None:
        """Remove the lock for a finalized session.

        Called during session finalization to prevent memory leaks
        from accumulating locks for completed sessions.

        Note: This should only be called when already holding _locks_lock.

        Args:
            session_id: The session identifier to clean up.
        """
        self._session_locks.pop(session_id, None)

    async def _cleanup_session_lock_only(self, session_id: str) -> None:
        """Clean up the lock for a finalized session.

        Only removes the session lock, NOT the session state. The session
        state is preserved so that events for finalized sessions can still
        be rejected (rather than creating new orphan sessions).

        For complete cleanup including state, use _cleanup_session_fully().

        This method is safe to call multiple times for the same session
        (idempotent cleanup).

        Args:
            session_id: The session identifier to clean up.
        """
        async with self._locks_lock:
            lock_removed = self._session_locks.pop(session_id, None) is not None

        if lock_removed:
            logger.debug(
                "Cleaned up session lock",
                extra={
                    "session_id": session_id,
                    "aggregator_id": self._aggregator_id,
                },
            )

    async def _cleanup_session_fully(self, session_id: str) -> None:
        """Clean up all resources for a finalized session including state.

        Removes both the session lock and session state from memory.
        Called when sessions need to be completely removed (e.g., orphan
        session eviction or periodic cleanup of old finalized sessions).

        WARNING: After this cleanup, events for this session will create
        a new orphan session instead of being rejected. Only use this for
        sessions that are truly no longer needed.

        This method is safe to call multiple times for the same session
        (idempotent cleanup).

        Args:
            session_id: The session identifier to clean up.
        """
        async with self._locks_lock:
            lock_removed = self._session_locks.pop(session_id, None) is not None
            state_removed = self._sessions.pop(session_id, None) is not None

        if lock_removed or state_removed:
            logger.debug(
                "Fully cleaned up session resources",
                extra={
                    "session_id": session_id,
                    "lock_removed": lock_removed,
                    "state_removed": state_removed,
                    "aggregator_id": self._aggregator_id,
                },
            )

    def _is_within_buffer(self, session: SessionState, event_time: datetime) -> bool:
        """Check if event is within out-of-order buffer window.

        Events arriving with timestamps significantly older than the last
        processed event may indicate out-of-order delivery or data issues.

        Args:
            session: The session state.
            event_time: The event's emitted_at timestamp.

        Returns:
            True if the event is within the acceptable buffer window.
        """
        buffer = timedelta(seconds=self._config.out_of_order_buffer_seconds)
        earliest_acceptable = session.last_event_at - buffer
        return event_time >= earliest_acceptable

    def _update_activity(
        self,
        session: SessionState,
        event_time: datetime,
    ) -> None:
        """Update session activity tracking.

        Increments event count and updates last activity timestamp
        if the event is newer than the current last activity.

        Args:
            session: The session state to update.
            event_time: The event's emitted_at timestamp.
        """
        session.event_count += 1

        # Update last_event_at only if this event is newer
        if event_time > session.last_event_at:
            session.last_event_at = event_time

    def _create_orphan_session(
        self,
        session_id: str,
        correlation_id: UUID,
        event_time: datetime,
    ) -> SessionState:
        """Create an orphan session for events arriving before SessionStarted.

        Orphan sessions capture events that arrive before the SessionStarted
        event (due to out-of-order delivery). They transition to ACTIVE
        when SessionStarted is eventually received.

        This method also adds the session to the sessions dict and triggers
        cleanup of excess orphan sessions to prevent unbounded memory growth.

        Note: This method must be called while holding the appropriate lock.

        Args:
            session_id: The session identifier.
            correlation_id: The correlation ID from the event.
            event_time: The timestamp of the triggering event.

        Returns:
            A new SessionState in ORPHAN status.
        """
        session = SessionState(
            session_id=session_id,
            status=EnumSessionStatus.ORPHAN,
            correlation_id=correlation_id,
            last_event_at=event_time,
            event_count=0,  # Will be incremented by _update_activity
        )
        self._sessions[session_id] = session

        # Clean up excess orphan sessions to prevent memory exhaustion
        self._cleanup_orphan_sessions(correlation_id)

        return session

    def _cleanup_orphan_sessions(self, correlation_id: UUID) -> int:
        """Remove oldest orphan sessions if over limit.

        Called when creating new orphan sessions to enforce the
        max_orphan_sessions configuration and prevent unbounded
        memory growth.

        Removes both session state and associated locks to prevent
        memory leaks.

        Threading Model:
            This method is called while holding a session lock (via
            _get_session_lock) but NOT while holding _locks_lock. This
            creates a benign race condition when accessing _session_locks:

            - _get_session_lock: Holds _locks_lock when reading/creating locks
            - This method: Does NOT hold _locks_lock when popping locks

            The race is benign because the worst case is:
            1. This method pops a lock for session X
            2. Concurrently, _get_session_lock creates a new lock for session X
            3. Result: Redundant lock creation, which is safe (just allocates
               a new asyncio.Lock that will eventually be cleaned up)

            We accept this small race window for simplicity rather than:
            - Acquiring _locks_lock here (would require careful lock ordering
              to avoid deadlocks since we already hold a session lock)
            - Deferring lock cleanup to a separate async method (adds complexity)

            The session state removal (del self._sessions[session_id]) is also
            not protected by _locks_lock here, but callers are expected to hold
            the session lock which serializes access to that specific session's
            state.

        Args:
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            Number of orphan sessions removed.
        """
        # Find all orphan sessions
        orphan_sessions = [
            (session_id, state)
            for session_id, state in self._sessions.items()
            if state.status == EnumSessionStatus.ORPHAN
        ]

        # Check if over limit
        excess = len(orphan_sessions) - self._config.max_orphan_sessions
        if excess <= 0:
            return 0

        # Sort by last_event_at (oldest first) and remove excess
        orphan_sessions.sort(key=lambda x: x[1].last_event_at)
        removed = 0
        for session_id, _ in orphan_sessions[:excess]:
            # Remove session state
            del self._sessions[session_id]
            # Remove associated lock to prevent memory leak
            self._session_locks.pop(session_id, None)
            removed += 1
            logger.debug(
                "Cleaned up orphan session and lock",
                extra={
                    "session_id": session_id,
                    "correlation_id": str(correlation_id),
                    "reason": "max_orphan_sessions_exceeded",
                    "orphan_count": len(orphan_sessions),
                    "max_orphan_sessions": self._config.max_orphan_sessions,
                    "aggregator_id": self._aggregator_id,
                },
            )

        logger.info(
            "Orphan session cleanup completed",
            extra={
                "removed_count": removed,
                "remaining_orphans": len(orphan_sessions) - removed,
                "correlation_id": str(correlation_id),
            },
        )

        return removed

    def _session_to_dict(self, session: SessionState) -> dict[str, Any]:
        """Convert session state to dictionary representation.

        This is a temporary conversion until the concrete
        ModelClaudeCodeSessionSnapshot is available from omnibase_core (OMN-1489).

        Args:
            session: The session state to convert.

        Returns:
            Dictionary representation of the session snapshot.
        """
        return {
            "session_id": session.session_id,
            "status": session.status.value,
            "correlation_id": str(session.correlation_id) if session.correlation_id else None,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "duration_seconds": session.duration_seconds,
            "working_directory": session.working_directory,
            "git_branch": session.git_branch,
            "hook_source": session.hook_source,
            "end_reason": session.end_reason,
            "prompt_count": len(session.prompts),
            "tool_count": len(session.tools),
            "tools_used_count": len({t.tool_name for t in session.tools.values()}),
            "event_count": session.event_count,
            "last_event_at": session.last_event_at.isoformat(),
            "prompts": [
                {
                    "prompt_id": str(p.prompt_id) if p.prompt_id else None,
                    "emitted_at": p.emitted_at.isoformat(),
                    "prompt_preview": p.prompt_preview,
                    "prompt_length": p.prompt_length,
                    "detected_intent": p.detected_intent,
                    "causation_id": str(p.causation_id) if p.causation_id else None,
                }
                for p in sorted(session.prompts.values(), key=lambda x: x.emitted_at)
            ],
            "tools": [
                {
                    "tool_execution_id": str(t.tool_execution_id) if t.tool_execution_id else None,
                    "emitted_at": t.emitted_at.isoformat(),
                    "tool_name": t.tool_name,
                    "success": t.success,
                    "duration_ms": t.duration_ms,
                    "summary": t.summary,
                    "causation_id": str(t.causation_id) if t.causation_id else None,
                }
                for t in sorted(session.tools.values(), key=lambda x: x.emitted_at)
            ],
        }


__all__ = [
    "PromptRecord",
    "ToolRecord",
    "SessionState",
    "SessionAggregator",
]
