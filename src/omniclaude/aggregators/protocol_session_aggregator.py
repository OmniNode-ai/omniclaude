# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol definition for session event aggregation.

This module defines the contract for aggregating Claude Code hook events
into session snapshots. Uses generics to allow implementation before
concrete models from omnibase_core are available.

Design Principles:
    The aggregation contract follows these key principles:

    1. **Idempotency**: Events can be safely reprocessed without side effects.
       Natural keys (prompt_id, tool_execution_id) prevent duplicate entries.

    2. **First-Write-Wins**: Identity fields (session_id, working_directory,
       git_branch) are set once and never overwritten. This prevents data
       corruption from out-of-order event delivery.

    3. **Append-Only Collections**: Event lists (prompts, tool_executions)
       are append-only with deduplication. Events are never removed or modified.

    4. **Timeout-Based Finalization**: Sessions without explicit SessionEnded
       events are finalized after an inactivity timeout. This handles
       abandoned sessions and ungraceful terminations.

    5. **Status State Machine**: Sessions progress through defined states
       (ORPHAN -> ACTIVE -> ENDED/TIMED_OUT) with clear transition rules.

Ordering Guarantees:
    Events within a session are ordered by Kafka partition (entity_id as
    partition key). However, the aggregator must handle:
    - Late-arriving events (events that arrive after finalization)
    - Out-of-order events (tool execution before prompt)
    - Orphan events (events before SessionStarted)

Related Tickets:
    - OMN-1401: Session storage in OmniMemory (current)
    - OMN-1489: Core models in omnibase_core (snapshot model)
    - OMN-1402: Learning compute node (consumer of snapshots)

Example:
    >>> from typing import Any
    >>> from uuid import uuid4
    >>>
    >>> # Type variables will be bound to concrete models
    >>> # TSnapshot = ModelClaudeCodeSessionSnapshot (from OMN-1489)
    >>> # TEvent = ModelHookPayload union type
    >>>
    >>> class MyAggregator:
    ...     '''Example implementation (simplified).'''
    ...     @property
    ...     def aggregator_id(self) -> str:
    ...         return "my-aggregator-001"
    ...
    ...     async def process_event(self, event: Any, correlation_id: UUID) -> bool:
    ...         # Process event into session state
    ...         return True
    ...
    >>> # Verify protocol conformance at runtime
    >>> from omniclaude.aggregators import ProtocolSessionAggregator
    >>> isinstance(MyAggregator(), ProtocolSessionAggregator)  # May be False without full impl
    False
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from datetime import datetime

# =============================================================================
# Generic Type Variables
# =============================================================================

# Generic type for session snapshot model.
# Will be bound to ModelClaudeCodeSessionSnapshot from omnibase_core (OMN-1489).
TSnapshot = TypeVar("TSnapshot")

# Generic type for hook event union.
# Will be bound to ModelHookPayload union type from omniclaude.hooks.schemas.
TEvent = TypeVar("TEvent")


# =============================================================================
# Protocol Definition
# =============================================================================


@runtime_checkable
class ProtocolSessionAggregator(Protocol[TSnapshot, TEvent]):
    """Contract for aggregating session events into snapshots.

    This protocol defines the interface for session event aggregation,
    enabling different implementations (in-memory, Redis, PostgreSQL)
    while maintaining consistent semantics.

    Aggregation Semantics:
        - **Idempotency**: Events are deduplicated via natural keys
          (prompt_id, tool_execution_id). Processing the same event
          twice has no effect.

        - **First-Write-Wins**: Identity fields (session_id, working_directory,
          git_branch, hook_source) are set from the first event and never
          overwritten. Subsequent events with different values are logged
          but ignored for these fields.

        - **Append-Only Collections**: Event collections (prompts, tools)
          are append-only. New events are added; existing events are
          never modified or removed.

        - **Timeout-Based Finalization**: Sessions without explicit end
          events are finalized after inactivity timeout. The finalize_session
          method is called by a sweep process.

    State Machine:
        Sessions progress through these states:

        ```
        [No Session] ---(any event)---> ORPHAN
        ORPHAN ---(SessionStarted)---> ACTIVE
        ACTIVE ---(SessionEnded)---> ENDED
        ACTIVE ---(timeout)---> TIMED_OUT
        ORPHAN ---(timeout)---> TIMED_OUT
        ```

        Terminal states (ENDED, TIMED_OUT) accept no further events.

    Thread Safety:
        Implementations MUST be thread-safe. Multiple concurrent calls
        to process_event for different sessions are expected. Calls
        for the same session should be serialized by the caller or
        handled with appropriate locking.

    Type Parameters:
        TSnapshot: The session snapshot model type. Will be bound to
            ModelClaudeCodeSessionSnapshot from omnibase_core.
        TEvent: The event union type. Will be bound to ModelHookPayload
            from omniclaude.hooks.schemas.

    Example Implementation Pattern:
        ```python
        class InMemorySessionAggregator(ProtocolSessionAggregator[Snapshot, Event]):
            def __init__(self) -> None:
                self._sessions: dict[str, Snapshot] = {}
                self._id = f"inmem-{uuid4().hex[:8]}"

            @property
            def aggregator_id(self) -> str:
                return self._id

            async def process_event(
                self, event: Event, correlation_id: UUID
            ) -> bool:
                # Implementation here
                ...
        ```
    """

    @property
    def aggregator_id(self) -> str:
        """Unique identifier for this aggregator instance.

        This ID is used for:
        - Logging and tracing to identify which aggregator processed events
        - Distributed coordination when multiple aggregators run in parallel
        - Health checks and monitoring dashboards

        The ID should be stable for the lifetime of the aggregator instance
        but unique across instances (e.g., include hostname or UUID).

        Returns:
            A unique string identifier for this aggregator instance.

        Example:
            >>> aggregator.aggregator_id
            'session-aggregator-worker-1-a3f2b1c9'
        """
        ...

    async def process_event(self, event: TEvent, correlation_id: UUID) -> bool:
        """Process a single event into session state.

        This method handles all event types (SessionStarted, SessionEnded,
        PromptSubmitted, ToolExecuted) and updates the appropriate session
        snapshot accordingly.

        Idempotency:
            Events are deduplicated using natural keys:
            - PromptSubmitted: prompt_id
            - ToolExecuted: tool_execution_id
            - SessionStarted/SessionEnded: Only one per session allowed

            If an event with the same natural key already exists, this
            method returns False without modifying state.

        State Transitions:
            - SessionStarted: Creates new session (ACTIVE) or transitions
              ORPHAN -> ACTIVE
            - SessionEnded: Transitions ACTIVE -> ENDED
            - Other events: Added to existing session, or create ORPHAN
              session if no session exists

        Error Handling:
            - Events for finalized sessions (ENDED, TIMED_OUT) are rejected
            - Invalid event structure raises ValidationError
            - Storage errors are propagated to caller

        Args:
            event: The hook event to process. Must be one of:
                - ModelHookSessionStartedPayload
                - ModelHookSessionEndedPayload
                - ModelHookPromptSubmittedPayload
                - ModelHookToolExecutedPayload
            correlation_id: Correlation ID for distributed tracing.
                This should be logged with all operations for debugging.

        Returns:
            True if the event was successfully processed and state was modified.
            False if the event was rejected (duplicate, finalized session, etc.).

        Raises:
            ValidationError: If the event fails schema validation.
            StorageError: If the underlying storage operation fails.

        Example:
            >>> event = ModelHookPromptSubmittedPayload(...)
            >>> correlation_id = uuid4()
            >>> was_processed = await aggregator.process_event(event, correlation_id)
            >>> if was_processed:
            ...     print("Event processed successfully")
            ... else:
            ...     print("Event rejected (duplicate or finalized session)")
        """
        ...

    async def get_snapshot(
        self, session_id: str, correlation_id: UUID
    ) -> TSnapshot | None:
        """Get current snapshot for a session.

        Returns the current state of a session as a snapshot object.
        The snapshot includes all aggregated data: identity fields,
        event counts, and optionally the event collections.

        Note:
            The session_id is a string (not UUID) because Claude Code
            session IDs may not always be valid UUIDs, depending on
            the source (startup vs resume vs clear).

        Args:
            session_id: The Claude Code session ID (string, not UUID).
                This matches the session_id field in hook events.
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            The current session snapshot, or None if the session does
            not exist in the aggregator's state.

        Example:
            >>> snapshot = await aggregator.get_snapshot("abc123", uuid4())
            >>> if snapshot:
            ...     print(f"Session status: {snapshot.status}")
            ...     print(f"Prompt count: {snapshot.prompt_count}")
            ... else:
            ...     print("Session not found")
        """
        ...

    async def finalize_session(
        self,
        session_id: str,
        correlation_id: UUID,
        reason: str | None = None,
    ) -> TSnapshot | None:
        """Finalize and seal a session snapshot.

        Called when SessionEnded is received or timeout expires.
        After finalization, no further events are accepted for this session.

        Finalization performs these operations:
        1. Sets session status to ENDED or TIMED_OUT
        2. Records finalization timestamp and reason
        3. Computes final metrics (duration, event counts)
        4. Optionally persists to long-term storage

        Idempotency:
            Calling finalize on an already-finalized session returns the
            existing snapshot without modification.

        Args:
            session_id: The session to finalize.
            correlation_id: Correlation ID for distributed tracing.
            reason: Finalization reason for logging and analytics.
                Common values: "user_exit", "timeout", "clear", "logout".
                If None, defaults to "unspecified".

        Returns:
            The final sealed snapshot, or None if the session was not found.

        Example:
            >>> # Finalize due to timeout
            >>> snapshot = await aggregator.finalize_session(
            ...     session_id="abc123",
            ...     correlation_id=uuid4(),
            ...     reason="timeout"
            ... )
            >>> if snapshot:
            ...     print(f"Session finalized: {snapshot.status}")
        """
        ...

    async def get_active_sessions(self, correlation_id: UUID) -> list[str]:
        """Get list of active (non-finalized) session IDs.

        Used by the timeout sweep process to find sessions that may
        need to be finalized due to inactivity. Returns sessions with
        status ACTIVE or ORPHAN.

        Performance:
            This method should be efficient even with many sessions.
            Implementations may use indexing or separate tracking for
            active sessions to avoid scanning all sessions.

        Args:
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            List of session IDs with status ACTIVE or ORPHAN.
            Returns empty list if no active sessions exist.

        Example:
            >>> active_ids = await aggregator.get_active_sessions(uuid4())
            >>> for session_id in active_ids:
            ...     last_activity = await aggregator.get_session_last_activity(
            ...         session_id, uuid4()
            ...     )
            ...     if should_timeout(last_activity):
            ...         await aggregator.finalize_session(
            ...             session_id, uuid4(), reason="timeout"
            ...         )
        """
        ...

    async def get_session_last_activity(
        self,
        session_id: str,
        correlation_id: UUID,
    ) -> datetime | None:
        """Get last activity timestamp for a session.

        Used by the timeout sweep to determine if a session should be
        finalized due to inactivity. Returns the timestamp of the most
        recent event received for the session.

        Activity Tracking:
            The "last activity" is the emitted_at timestamp of the most
            recent event processed for this session, regardless of event
            type. This includes:
            - SessionStarted
            - SessionEnded (even though this finalizes the session)
            - PromptSubmitted
            - ToolExecuted

        Args:
            session_id: The session to check.
            correlation_id: Correlation ID for distributed tracing.

        Returns:
            Timestamp of the last event, or None if session not found.

        Example:
            >>> from datetime import datetime, timedelta, UTC
            >>> last_activity = await aggregator.get_session_last_activity(
            ...     "abc123", uuid4()
            ... )
            >>> if last_activity:
            ...     idle_time = datetime.now(UTC) - last_activity
            ...     if idle_time > timedelta(hours=1):
            ...         print("Session has been idle for over an hour")
        """
        ...


__all__ = [
    "ProtocolSessionAggregator",
    "TSnapshot",
    "TEvent",
]
