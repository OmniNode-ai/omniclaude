# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Enums for session aggregation.

This module defines enums used by the session aggregation system. These enums
represent the state machine for session lifecycle management during event
aggregation.

Note:
    EnumSessionStatus will move to omnibase_core in OMN-1489.
    This is a temporary local definition until core models are ready.

Related Tickets:
    - OMN-1401: Session storage in OmniMemory (current)
    - OMN-1489: Core models in omnibase_core (future home)
"""

from __future__ import annotations

from enum import StrEnum


class EnumSessionStatus(StrEnum):
    """Status of a session during aggregation.

    This enum represents the state machine for session lifecycle:

    State Transitions:
        ORPHAN -> ACTIVE:  When SessionStarted event is received
        ACTIVE -> ENDED:   When SessionEnded event is received (explicit end)
        ACTIVE -> TIMED_OUT: When inactivity timeout triggers
        ORPHAN -> TIMED_OUT: When orphan session times out without SessionStarted

    Notes:
        - ORPHAN status occurs when events arrive before the SessionStarted
          event (e.g., due to out-of-order delivery or late session start).
        - Once a session reaches ENDED or TIMED_OUT, it is sealed and no
          further events are accepted.

    Attributes:
        ORPHAN: Events received before SessionStarted.
            This is a transient state - sessions should transition to ACTIVE
            when SessionStarted arrives, or TIMED_OUT if it never arrives.
        ACTIVE: SessionStarted received, session is ongoing.
            This is the normal operating state for a live session.
        ENDED: SessionEnded received, session completed normally.
            Terminal state - no further events accepted.
        TIMED_OUT: Inactivity timeout triggered.
            Terminal state - session was abandoned without explicit end.

    Example:
        >>> status = EnumSessionStatus.ACTIVE
        >>> status.value
        'active'
        >>> status == "active"
        True
        >>> EnumSessionStatus("orphan")
        <EnumSessionStatus.ORPHAN: 'orphan'>
    """

    ORPHAN = "orphan"
    ACTIVE = "active"
    ENDED = "ended"
    TIMED_OUT = "timed_out"


__all__ = [
    "EnumSessionStatus",
]
