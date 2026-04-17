# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for dispatch-scoped state prerequisite (OMN-9084).

Covers the ModelDispatchRecord Pydantic model, the YAML writer that persists
it under ``$ONEX_STATE_DIR/dispatches/<agent-id>.yaml`` at dispatch time, and
the JSONL reader that parses tool-call records appended by the PostToolUse
subagent tool-log hook.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.hooks.lib.dispatch_record_writer import (
    read_tool_call_jsonl,
    write_dispatch_record,
)
from omniclaude.hooks.model_dispatch_record import ModelDispatchRecord

pytestmark = pytest.mark.unit


def _make_record(agent_id: str = "worker-1") -> ModelDispatchRecord:
    return ModelDispatchRecord(
        agent_id=agent_id,
        dispatched_at=datetime(2026, 4, 17, 20, 0, 0, tzinfo=UTC),
        dispatcher="onex:dispatch_worker",
        ticket="OMN-9084",
        allowed_tools=["Read", "Grep"],
        prompt_digest="sha256:abcdef",
        parent_session_id="parent-session-xyz",
    )


def test_writer_appends_dispatch_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_dispatch_record persists the record at <state>/dispatches/<agent-id>.yaml."""
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    record = _make_record("worker-append")

    out_path = write_dispatch_record(record)

    assert out_path == tmp_path / "dispatches" / "worker-append.yaml"
    assert out_path.is_file()
    body = out_path.read_text(encoding="utf-8")
    assert "agent_id: worker-append" in body
    assert "ticket: OMN-9084" in body
    assert "Read" in body and "Grep" in body


def test_reader_parses_tool_call_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """read_tool_call_jsonl parses one dict per line and skips blanks."""
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    agent_id = "worker-read"
    jsonl_path = tmp_path / "dispatches" / agent_id / "tool-calls.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    lines = [
        {
            "ts": "2026-04-17T20:00:00Z",
            "agent_id": agent_id,
            "tool_name": "Read",
            "decision": "allow",
            "duration_ms": 12,
            "error": None,
        },
        {
            "ts": "2026-04-17T20:00:01Z",
            "agent_id": agent_id,
            "tool_name": "Bash",
            "decision": "allow",
            "duration_ms": 300,
            "error": None,
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n\n", encoding="utf-8"
    )

    parsed = list(read_tool_call_jsonl(agent_id))

    assert len(parsed) == 2
    assert parsed[0]["tool_name"] == "Read"
    assert parsed[1]["tool_name"] == "Bash"
    assert parsed[1]["duration_ms"] == 300


def test_writer_creates_missing_dispatches_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing $ONEX_STATE_DIR/dispatches/ is created on first write."""
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    dispatches_dir = tmp_path / "dispatches"
    assert not dispatches_dir.exists()

    write_dispatch_record(_make_record("worker-fresh"))

    assert dispatches_dir.is_dir()
    assert (dispatches_dir / "worker-fresh.yaml").is_file()
