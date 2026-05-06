# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for daemon graceful degradation (OMN-10622).

Covers:
  - daemon available (socket exists + ping returns ok) → DAEMON transport
  - daemon unavailable: socket path does not exist → INMEMORY transport
  - daemon unavailable: ping fails (connection refused) → INMEMORY transport
  - is_daemon_available() mirrors transport selection

Note: AF_UNIX paths on macOS are capped at 104 bytes, so tests use /tmp/<short>
rather than tmp_path (which generates a long path under /private/var/folders/...).
"""

from __future__ import annotations

import json
import socket
import threading
import uuid
from pathlib import Path

import pytest

from omniclaude.delegation.daemon_fallback import (
    EnumDelegationTransport,
    get_delegation_transport,
    is_daemon_available,
)
from omniclaude.delegation.transport import DelegationTransportSelector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_sock_path(prefix: str) -> str:
    """Return a short socket path under /tmp safe for AF_UNIX on macOS."""
    uid = uuid.uuid4().hex[:8]
    return f"/tmp/onex-test-{prefix}-{uid}.sock"


def _make_ping_server(sock_path: str) -> threading.Thread:
    """Start a minimal Unix socket server that replies ok to ping."""
    ready = threading.Event()

    def _serve() -> None:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(256)
            if not chunk:
                break
            data += chunk
        resp = json.dumps({"status": "ok", "queue_size": 0, "spool_size": 0})
        conn.sendall(resp.encode() + b"\n")
        conn.close()
        srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    ready.wait(timeout=2.0)
    return t


def _make_error_server(sock_path: str) -> threading.Thread:
    """Start a server that replies with status=error."""
    ready = threading.Event()

    def _serve() -> None:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        conn.recv(256)
        conn.sendall(json.dumps({"status": "error"}).encode() + b"\n")
        conn.close()
        srv.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    ready.wait(timeout=2.0)
    return t


# ---------------------------------------------------------------------------
# DelegationTransportSelector tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_daemon_available_returns_daemon_transport() -> None:
    sock_path = _short_sock_path("avail")
    try:
        t = _make_ping_server(sock_path)
        selector = DelegationTransportSelector(socket_path=sock_path, ping_timeout=2.0)
        result = selector.select()
        t.join(timeout=2.0)
        assert result == EnumDelegationTransport.DAEMON
    finally:
        Path(sock_path).unlink(missing_ok=True)


@pytest.mark.unit
def test_socket_missing_returns_inmemory() -> None:
    sock_path = _short_sock_path("miss")
    selector = DelegationTransportSelector(socket_path=sock_path)
    result = selector.select()
    assert result == EnumDelegationTransport.INMEMORY


@pytest.mark.unit
def test_ping_fails_connection_refused_returns_inmemory() -> None:
    """Socket file exists but nothing is listening — connect raises."""
    sock_path = _short_sock_path("dead")
    # bind() creates the socket file without listen() so Path.exists() passes
    # but connect() raises ConnectionRefusedError.
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(sock_path)
        selector = DelegationTransportSelector(socket_path=sock_path, ping_timeout=0.5)
        result = selector.select()
        assert result == EnumDelegationTransport.INMEMORY
    finally:
        srv.close()
        Path(sock_path).unlink(missing_ok=True)


@pytest.mark.unit
def test_ping_bad_response_returns_inmemory() -> None:
    """Daemon returns unexpected JSON — should degrade to INMEMORY."""
    sock_path = _short_sock_path("bad")
    try:
        t = _make_error_server(sock_path)
        selector = DelegationTransportSelector(socket_path=sock_path, ping_timeout=2.0)
        result = selector.select()
        t.join(timeout=2.0)
        assert result == EnumDelegationTransport.INMEMORY
    finally:
        Path(sock_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# get_delegation_transport() convenience function
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_delegation_transport_daemon() -> None:
    sock_path = _short_sock_path("gdt1")
    try:
        t = _make_ping_server(sock_path)
        result = get_delegation_transport(socket_path=sock_path, ping_timeout=2.0)
        t.join(timeout=2.0)
        assert result == EnumDelegationTransport.DAEMON
    finally:
        Path(sock_path).unlink(missing_ok=True)


@pytest.mark.unit
def test_get_delegation_transport_inmemory_no_socket() -> None:
    sock_path = _short_sock_path("gdt2")
    result = get_delegation_transport(socket_path=sock_path)
    assert result == EnumDelegationTransport.INMEMORY


# ---------------------------------------------------------------------------
# is_daemon_available() convenience function
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_daemon_available_true_when_daemon_up() -> None:
    sock_path = _short_sock_path("ida1")
    try:
        t = _make_ping_server(sock_path)
        result = is_daemon_available(socket_path=sock_path, ping_timeout=2.0)
        t.join(timeout=2.0)
        assert result is True
    finally:
        Path(sock_path).unlink(missing_ok=True)


@pytest.mark.unit
def test_is_daemon_available_false_when_socket_missing() -> None:
    sock_path = _short_sock_path("ida2")
    result = is_daemon_available(socket_path=sock_path)
    assert result is False


@pytest.mark.unit
def test_is_daemon_available_false_when_ping_fails() -> None:
    sock_path = _short_sock_path("ida3")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(sock_path)
        result = is_daemon_available(socket_path=sock_path, ping_timeout=0.5)
        assert result is False
    finally:
        srv.close()
        Path(sock_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# EnumDelegationTransport string values
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_enum_string_values() -> None:
    assert str(EnumDelegationTransport.DAEMON) == "daemon"
    assert str(EnumDelegationTransport.INMEMORY) == "inmemory"
