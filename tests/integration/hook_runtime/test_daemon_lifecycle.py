# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Integration test: full hook runtime daemon lifecycle. [OMN-5311]"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from omniclaude.hook_runtime.delegation_state import DelegationConfig
from omniclaude.hook_runtime.server import HookRuntimeConfig, HookRuntimeServer


def _short_sock(name: str) -> str:
    return f"/tmp/omni-integ-{uuid.uuid4().hex[:8]}-{name}.sock"


async def _send(
    writer: asyncio.StreamWriter,
    req: dict[object, object],
) -> None:
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict[str, object]:
    line = await asyncio.wait_for(reader.readline(), timeout=2.0)
    result: dict[str, object] = json.loads(line)
    return result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_lifecycle() -> None:
    """Start daemon, send requests, verify enforcement, stop daemon."""
    socket_path = _short_sock("lifecycle")
    config = HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
        delegation=DelegationConfig(
            read_block_threshold=12,  # block after 13 reads (>12)
        ),
    )
    server = HookRuntimeServer(config=config)

    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # 1. Reset session
        await _send(
            writer, {"action": "reset_session", "session_id": "s1", "payload": {}}
        )
        resp = await _recv(reader)
        assert resp["decision"] == "ack"

        # 2. Record 12 read tools — should all pass
        for _ in range(12):
            await _send(
                writer,
                {
                    "action": "classify_tool",
                    "session_id": "s1",
                    "payload": {"tool_name": "Grep", "tool_input": {}},
                },
            )
            resp = await _recv(reader)
        # 12th should still pass (threshold is >12)
        assert resp["decision"] == "pass"

        # 3. 13th should block (13 > 12)
        await _send(
            writer,
            {
                "action": "classify_tool",
                "session_id": "s1",
                "payload": {"tool_name": "Grep", "tool_input": {}},
            },
        )
        resp = await _recv(reader)
        assert resp["decision"] == "block"
        assert resp["message"] is not None
        assert "13" in str(resp["message"])

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_session_isolation() -> None:
    """Two sessions have independent counters."""
    socket_path = _short_sock("multisess")
    config = HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
        delegation=DelegationConfig(read_block_threshold=2),
    )
    server = HookRuntimeServer(config=config)
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        # Session A: record 3 reads → should block
        for _ in range(3):
            await _send(
                writer,
                {
                    "action": "classify_tool",
                    "session_id": "a",
                    "payload": {"tool_name": "Read", "tool_input": {}},
                },
            )
            resp_a = await _recv(reader)
        assert resp_a["decision"] == "block"

        # Session B: record 1 read → should pass (independent counter)
        await _send(
            writer,
            {
                "action": "classify_tool",
                "session_id": "b",
                "payload": {"tool_name": "Read", "tool_input": {}},
            },
        )
        resp_b = await _recv(reader)
        assert resp_b["decision"] == "pass"
        counters_b = resp_b["counters"]
        assert isinstance(counters_b, dict)
        assert counters_b["read"] == 1

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_socket_cleanup_on_stop() -> None:
    """Socket file is removed after daemon stops."""
    import os

    socket_path = _short_sock("cleanup")
    config = HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
    )
    server = HookRuntimeServer(config=config)
    await server.start()
    assert os.path.exists(socket_path)

    await server.stop()
    assert not os.path.exists(socket_path)
