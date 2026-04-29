# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from omniclaude.hooks.opencode_emitter import (
    EVENT_TYPE,
    emit_opencode_cost_payloads,
    main,
)


class FakeCostProjectionSink:
    """Small idempotent stand-in for the llm_call_metrics unique input_hash gate."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def emit(self, event_type: str, payload: dict[str, Any]) -> bool:
        assert event_type == EVENT_TYPE
        self.rows.setdefault(str(payload["idempotency_key"]), payload)
        return True


def _create_fixture_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE session (
                id text PRIMARY KEY,
                directory text,
                time_created integer,
                time_updated integer,
                title text
            );
            CREATE TABLE message (
                id text PRIMARY KEY,
                session_id text NOT NULL,
                time_created integer NOT NULL,
                time_updated integer NOT NULL,
                data text NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO session (id, directory, time_created, time_updated, title)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "opencode-session-1",
                "/workspace/omni_home/omni_worktrees/OMN-10336/omniclaude",
                1776774286000,
                1776774300000,
                "opencode fixture",
            ),
        )
        connection.execute(
            """
            INSERT INTO message (id, session_id, time_created, time_updated, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "msg_assistant_1",
                "opencode-session-1",
                1776774286359,
                1776774291465,
                json.dumps(
                    {
                        "role": "assistant",
                        "cost": 0.006231,
                        "tokens": {
                            "total": 20609,
                            "input": 20587,
                            "output": 3,
                            "reasoning": 19,
                            "cache": {"write": 0, "read": 0},
                        },
                        "modelID": "gemini-2.5-flash",
                        "providerID": "google",
                        "time": {
                            "created": 1776774286359,
                            "completed": 1776774291465,
                        },
                        "finish": "stop",
                    }
                ),
            ),
        )


def test_opencode_session_emission_is_idempotent_on_rerun(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    _create_fixture_db(db_path)
    sink = FakeCostProjectionSink()
    env = {
        "OMNI_HOME": "/workspace/omni_home",
        "ONEX_MACHINE_ID": "machine-opencode-1",
    }

    first_count = emit_opencode_cost_payloads(
        db_path=db_path,
        env=env,
        emit=sink.emit,
    )
    second_count = emit_opencode_cost_payloads(
        db_path=db_path,
        env=env,
        emit=sink.emit,
    )

    assert first_count == 1
    assert second_count == 1
    assert len(sink.rows) == 1
    row = next(iter(sink.rows.values()))
    assert row["tool_source"] == "opencode"
    assert row["source"] == "opencode"
    assert row["usage_source"] == "API"
    assert row["repo_name"] == "omniclaude"
    assert row["machine_id"] == "machine-opencode-1"
    assert row["cost_usd"] == 0.006231
    assert row["input_hash"].startswith("sha256-")
    assert row["idempotency_key"].startswith("sha256-")


def test_opencode_scanner_absence_exits_zero(tmp_path: Path) -> None:
    assert main(["--db-path", str(tmp_path / "missing.db")]) == 0
