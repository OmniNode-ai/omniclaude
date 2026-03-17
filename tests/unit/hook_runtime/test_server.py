"""Unit tests for hook runtime async socket server. [OMN-5306]"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from omniclaude.hook_runtime.delegation_state import DelegationConfig
from omniclaude.hook_runtime.server import HookRuntimeConfig, HookRuntimeServer


def _short_socket_path() -> str:
    """Generate a short socket path in /tmp (AF_UNIX path limit ~104 chars on macOS)."""
    return f"/tmp/omni-test-{uuid.uuid4().hex[:8]}.sock"


def default_server_config(socket_path: str) -> HookRuntimeConfig:
    """Return a minimal server config using a temp socket path."""
    return HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
        delegation=DelegationConfig(
            bash_readonly_patterns=[r"^git\s+", r"^cat\s+"],
            bash_compound_deny_patterns=[r"&&"],
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_ping() -> None:
    socket_path = _short_socket_path()
    server = HookRuntimeServer(config=default_server_config(socket_path))
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"action":"ping","session_id":"test"}\n')
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line)
        assert resp["decision"] == "ack"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_classify_tool_read() -> None:
    socket_path = _short_socket_path()
    server = HookRuntimeServer(config=default_server_config(socket_path))
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        req = {
            "action": "classify_tool",
            "session_id": "s1",
            "payload": {"tool_name": "Read", "tool_input": {}},
        }
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line)
        assert resp["decision"] == "pass"
        assert resp["counters"]["read"] == 1
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_reset_session() -> None:
    socket_path = _short_socket_path()
    server = HookRuntimeServer(config=default_server_config(socket_path))
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Record some tools first
        req = {
            "action": "classify_tool",
            "session_id": "s2",
            "payload": {"tool_name": "Read", "tool_input": {}},
        }
        writer.write((json.dumps(req) + "\n").encode())
        await writer.drain()
        await asyncio.wait_for(reader.readline(), timeout=2.0)

        # Reset session
        reset_req = {"action": "reset_session", "session_id": "s2", "payload": {}}
        writer.write((json.dumps(reset_req) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line)
        assert resp["decision"] == "ack"

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_stale_socket_cleaned() -> None:
    """Starting a server should clean up a stale socket file."""
    socket_path = _short_socket_path()

    # Create a stale socket file (not a real socket — simulates stale)
    with open(socket_path, "w") as f:
        f.write("stale")

    server = HookRuntimeServer(config=default_server_config(socket_path))
    await server.start()
    try:
        # Should have replaced the stale file with a real socket
        assert os.path.exists(socket_path)
        # Quick ping to confirm it works
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"action":"ping","session_id":"test"}\n')
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        resp = json.loads(line)
        assert resp["decision"] == "ack"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
