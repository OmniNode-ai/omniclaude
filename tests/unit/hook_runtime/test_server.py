# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
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
async def test_publish_delegation_event_writes_to_sqlite(tmp_path: object) -> None:
    """publish_delegation_event action projects a row to SQLite via the bus (OMN-10718)."""
    from pathlib import Path as _Path  # noqa: PLC0415

    from omniclaude.delegation.sqlite_adapter import (
        SQLiteProjectionAdapter,  # noqa: PLC0415
    )

    socket_path = _short_socket_path()
    db_path = _Path(str(tmp_path)) / "test_proj.sqlite"  # type: ignore[arg-type]

    # Patch SQLiteProjectionAdapter.__init__ to use the temp db_path.
    import omniclaude.hook_runtime.server as _server_mod  # noqa: PLC0415

    _orig_cls = _server_mod.SQLiteProjectionAdapter

    class _PatchedAdapter(SQLiteProjectionAdapter):
        def __init__(self) -> None:
            super().__init__(db_path=db_path)

    _server_mod.SQLiteProjectionAdapter = _PatchedAdapter  # type: ignore[assignment]
    server = HookRuntimeServer(config=default_server_config(socket_path))
    try:
        await server.start()

        reader, writer = await asyncio.open_unix_connection(socket_path)
        request = {
            "action": "publish_delegation_event",
            "session_id": "test-session",
            "payload": {
                "correlation_id": "pub-evt-001",
                "session_id": "test-session",
                "task_type": "test",
                "delegated_to": "Qwen3-Coder-30B",
                "model_name": "Qwen3-Coder-30B",
                "delegated_by": "onex.delegate-skill.inprocess",
                "quality_gate_passed": True,
                "delegation_latency_ms": 500,
                "cost_savings_usd": 0.01,
                "tokens_input": 100,
                "tokens_output": 50,
                "delegation_success": True,
            },
        }
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=3.0)
        resp = json.loads(line)
        assert resp["decision"] == "ack"
        writer.close()
        await writer.wait_closed()

        # Allow the async bus subscriber handler to complete.
        await asyncio.sleep(0.1)

        # Verify the row landed in SQLite.
        adapter = SQLiteProjectionAdapter(db_path=db_path)
        try:
            rows = adapter.query(
                "delegation_events", filters={"correlation_id": "pub-evt-001"}
            )
            assert len(rows) == 1
            assert rows[0]["task_type"] == "test"
            assert rows[0]["delegated_to"] == "Qwen3-Coder-30B"
            assert rows[0]["latency_ms"] == 500
        finally:
            adapter.close()
    finally:
        await server.stop()
        _server_mod.SQLiteProjectionAdapter = _orig_cls  # type: ignore[assignment]


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
