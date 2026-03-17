"""Unit tests for hook runtime daemon socket protocol models. [OMN-5304]"""

import json

import pytest

from omniclaude.hook_runtime.protocol import (
    HookRuntimeRequest,
    HookRuntimeResponse,
    parse_hook_runtime_request,
)


@pytest.mark.unit
def test_request_roundtrip() -> None:
    req = HookRuntimeRequest(
        action="classify_tool",
        session_id="abc-123",
        payload={"tool_name": "Bash", "command": "gh pr list"},
    )
    raw = req.model_dump_json()
    parsed = parse_hook_runtime_request(json.loads(raw))
    assert parsed.action == "classify_tool"
    assert parsed.session_id == "abc-123"


@pytest.mark.unit
def test_response_block() -> None:
    resp = HookRuntimeResponse(
        decision="block",
        message="DELEGATION ENFORCER [HARD BLOCK]: 13 read-only tool calls...",
        counters={"read": 13, "write": 0, "total": 13},
    )
    assert resp.decision == "block"


@pytest.mark.unit
def test_response_pass() -> None:
    resp = HookRuntimeResponse(
        decision="pass",
        message=None,
        counters={"read": 1, "write": 0, "total": 1},
    )
    assert resp.decision == "pass"
