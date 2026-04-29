# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from omniclaude.hooks.opencode_emitter import (
    AssistantUsageRecord,
    OpencodeSessionRow,
    build_opencode_cost_payload,
    parse_assistant_usage_record,
    scan_opencode_cost_payloads,
)


def _assistant_message(
    *,
    cost: float | None = 0.012345,
    input_tokens: int = 1200,
    output_tokens: int = 345,
    model_id: str = "claude-sonnet-4-5-20250929",
) -> str:
    payload: dict[str, object] = {
        "role": "assistant",
        "cost": cost,
        "tokens": {
            "total": input_tokens + output_tokens,
            "input": input_tokens,
            "output": output_tokens,
        },
        "modelID": model_id,
        "providerID": "anthropic",
        "time": {"created": 1776774286359, "completed": 1776774291465},
    }
    if cost is None:
        payload.pop("cost")
    return json.dumps(payload)


def _create_opencode_db(path: Path) -> None:
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


def _insert_session(
    path: Path,
    *,
    session_id: str = "ses_001",
    directory: str = "/workspace/omni_home/omni_worktrees/OMN-10336/omniclaude",
    message_data: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO session (id, directory, time_created, time_updated, title)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, directory, 1776774286000, 1776774292000, "test session"),
        )
        connection.execute(
            """
            INSERT INTO message (id, session_id, time_created, time_updated, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "msg_001",
                session_id,
                1776774286359,
                1776774291465,
                message_data or _assistant_message(),
            ),
        )


def test_parse_assistant_usage_record_reads_opencode_message_data() -> None:
    record = parse_assistant_usage_record(
        message_id="msg_001",
        data_json=_assistant_message(),
    )

    assert record is not None
    assert record.model_id == "claude-sonnet-4-5-20250929"
    assert record.provider_id == "anthropic"
    assert record.prompt_tokens == 1200
    assert record.completion_tokens == 345
    assert record.total_tokens == 1545
    assert record.cost_usd == 0.012345


def test_parse_assistant_usage_record_ignores_non_assistant() -> None:
    assert (
        parse_assistant_usage_record(
            message_id="msg_user",
            data_json=json.dumps({"role": "user", "text": "hello"}),
        )
        is None
    )


def test_build_payload_uses_api_usage_source_when_tokens_and_cost_exist() -> None:
    record = parse_assistant_usage_record(
        message_id="msg_001",
        data_json=_assistant_message(cost=0.25),
    )
    assert isinstance(record, AssistantUsageRecord)

    payload = build_opencode_cost_payload(
        session=OpencodeSessionRow(
            session_id="ses_001",
            directory="/workspace/omni_home/omniclaude",
            time_created=1776774286000,
            time_updated=1776774292000,
            title="test session",
        ),
        records=[record],
        env={"OMNI_HOME": "/workspace/omni_home", "ONEX_MACHINE_ID": "machine-1"},
    )

    assert payload is not None
    assert payload["tool_source"] == "opencode"
    assert payload["source"] == "opencode"
    assert payload["usage_source"] == "API"
    assert payload["cost_usd"] == 0.25
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] == "machine-1"
    assert re.fullmatch(r"sha256-[0-9a-f]{64}", str(payload["idempotency_key"]))
    assert re.fullmatch(r"sha256-[0-9a-f]{64}", str(payload["input_hash"]))


def test_build_payload_estimates_when_tokens_exist_without_cost() -> None:
    record = parse_assistant_usage_record(
        message_id="msg_001",
        data_json=_assistant_message(cost=None),
    )
    assert isinstance(record, AssistantUsageRecord)

    payload = build_opencode_cost_payload(
        session=OpencodeSessionRow(
            session_id="ses_estimated",
            directory="/workspace/omni_home/omniclaude",
            time_created=1776774286000,
            time_updated=1776774292000,
            title=None,
        ),
        records=[record],
        env={"OMNI_HOME": "/workspace/omni_home"},
    )

    assert payload is not None
    assert payload["usage_source"] == "ESTIMATED"
    assert payload["cost_usd"] > 0
    assert payload["machine_id"] is None


def test_build_payload_marks_missing_without_tokens_or_cost() -> None:
    record = parse_assistant_usage_record(
        message_id="msg_001",
        data_json=_assistant_message(cost=None, input_tokens=0, output_tokens=0),
    )
    assert isinstance(record, AssistantUsageRecord)

    payload = build_opencode_cost_payload(
        session=OpencodeSessionRow(
            session_id="ses_missing",
            directory="/tmp/outside",
            time_created=1776774286000,
            time_updated=1776774292000,
            title=None,
        ),
        records=[record],
        env={"OMNI_HOME": "/workspace/omni_home", "HOSTNAME": "ignored"},
    )

    assert payload is not None
    assert payload["usage_source"] == "MISSING"
    assert payload["cost_usd"] == 0.0
    assert payload["repo_name"] is None
    assert payload["machine_id"] is None


def test_scan_opencode_cost_payloads_reads_sqlite_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    _create_opencode_db(db_path)
    _insert_session(db_path)

    payloads = scan_opencode_cost_payloads(
        db_path=db_path,
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "ONEX_MACHINE_ID": "machine-scan",
        },
    )

    assert len(payloads) == 1
    assert payloads[0]["session_id"] == "ses_001"
    assert payloads[0]["request_count"] == 1
    assert payloads[0]["repo_name"] == "omniclaude"
    assert payloads[0]["machine_id"] == "machine-scan"


def test_scan_absent_database_returns_empty_list(tmp_path: Path) -> None:
    assert scan_opencode_cost_payloads(db_path=tmp_path / "missing.db", env={}) == []
