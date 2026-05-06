# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Daemon availability check and in-memory fallback for delegation.

When the emit daemon cannot be reached, delegation still works via in-memory
SQLite persistence. This module exposes the availability probe and the
transport selection result so callers can choose the appropriate path.
"""

from __future__ import annotations

import logging

from omniclaude.delegation.transport import (
    DelegationTransportSelector,
    EnumDelegationTransport,
    get_delegation_transport,
)

logger = logging.getLogger(__name__)

__all__ = [
    "is_daemon_available",
    "get_delegation_transport",
    "EnumDelegationTransport",
    "DelegationTransportSelector",
]


def is_daemon_available(
    socket_path: str | None = None,
    ping_timeout: float = 1.0,
) -> bool:
    """Return True if the emit daemon is reachable via its Unix socket.

    Uses a lightweight socket ping — no Kafka or external dependencies required.
    Falls back to False on any error so the caller can safely degrade to
    in-memory mode without raising.

    Args:
        socket_path: Override the socket path. If None, resolved from env.
        ping_timeout: Seconds to wait for the daemon to respond.
    """
    transport = get_delegation_transport(
        socket_path=socket_path,
        ping_timeout=ping_timeout,
    )
    available = transport == EnumDelegationTransport.DAEMON
    if not available:
        logger.info("emit daemon unavailable — delegation will use in-memory mode")
    return available
