# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation transport enum and selector."""

from __future__ import annotations

import logging
import os
import socket
from enum import StrEnum

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET_PATH = "/tmp/onex-emit.sock"  # noqa: S108  # nosec B108 — fixed socket path required by daemon contract
_PING_TIMEOUT_S = 1.0


def _resolve_socket_path() -> str:
    """Resolve the emit daemon socket path using the same order as the client."""
    env_path = os.environ.get("ONEX_EMIT_SOCKET_PATH")
    if env_path:
        return env_path
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return os.path.join(xdg, "onex", "emit.sock")
    return _DEFAULT_SOCKET_PATH


class EnumDelegationTransport(StrEnum):
    DAEMON = "daemon"
    INMEMORY = "inmemory"


class DelegationTransportSelector:
    """Probes the emit daemon and selects the appropriate transport.

    Args:
        socket_path: Override the daemon socket path. If None, resolved from env.
        ping_timeout: Seconds to wait for the daemon ping reply.
    """

    def __init__(
        self,
        socket_path: str | None = None,
        ping_timeout: float = _PING_TIMEOUT_S,
    ) -> None:
        self._socket_path = socket_path or _resolve_socket_path()
        self._ping_timeout = ping_timeout

    def _daemon_reachable(self) -> bool:
        """Return True if the daemon socket exists and responds to a ping."""
        import json
        from pathlib import Path

        if not Path(self._socket_path).exists():
            logger.debug("emit daemon socket missing: %s", self._socket_path)
            return False

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self._ping_timeout)
            sock.connect(self._socket_path)
            sock.sendall(json.dumps({"command": "ping"}).encode() + b"\n")
            buf = bytearray()
            for _ in range(16):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                if b"\n" in buf:
                    break
            sock.close()
            resp = json.loads(buf.split(b"\n")[0])
            return resp.get("status") == "ok"  # type: ignore[no-any-return]
        except (OSError, ValueError, KeyError) as exc:
            logger.debug("emit daemon ping failed: %s", exc)
            return False

    def select(self) -> EnumDelegationTransport:
        """Probe the daemon and return the selected transport."""
        if self._daemon_reachable():
            logger.info("delegation transport: DAEMON (socket=%s)", self._socket_path)
            return EnumDelegationTransport.DAEMON
        logger.info(
            "delegation transport: INMEMORY (daemon unavailable at %s)",
            self._socket_path,
        )
        return EnumDelegationTransport.INMEMORY


def get_delegation_transport(
    socket_path: str | None = None,
    ping_timeout: float = _PING_TIMEOUT_S,
) -> EnumDelegationTransport:
    """Return the appropriate delegation transport based on daemon availability.

    Returns:
        EnumDelegationTransport.DAEMON if the emit daemon is reachable,
        EnumDelegationTransport.INMEMORY otherwise.
    """
    return DelegationTransportSelector(
        socket_path=socket_path,
        ping_timeout=ping_timeout,
    ).select()


__all__ = [
    "EnumDelegationTransport",
    "DelegationTransportSelector",
    "get_delegation_transport",
]
