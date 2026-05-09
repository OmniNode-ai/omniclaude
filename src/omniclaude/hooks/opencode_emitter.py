# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Scan opencode's SQLite session store into LLM cost telemetry payloads."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from omniclaude.hooks.session_cost_common import (
    derive_machine_id,
    derive_repo_name,
    estimate_cost_usd,
    stable_payload_hash,
)

EVENT_TYPE = "llm.cost.completed"
TOOL_SOURCE = "opencode"
DEFAULT_DB_PATH = Path("~/.local/share/opencode/opencode.db").expanduser()


@dataclass(frozen=True)
class OpencodeSessionRow:
    """Subset of the opencode session table needed for cost attribution."""

    session_id: str
    directory: str | None
    time_created: int | None
    time_updated: int | None
    title: str | None


@dataclass(frozen=True)
class AssistantUsageRecord:
    """Normalized assistant message cost fields from ``message.data`` JSON."""

    message_id: str
    model_id: str
    provider_id: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    time_created: int | None
    time_completed: int | None
    raw: Mapping[str, object]


def _sha256_key(value: object) -> str:
    return f"sha256-{stable_payload_hash(value)}"


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _coerce_non_negative_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _timestamp_iso(value: int | None) -> str:
    if value is None:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    timestamp = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message_time(data: Mapping[str, object], key: str) -> int | None:
    raw_time = data.get("time")
    if not isinstance(raw_time, Mapping):
        return None
    return _coerce_non_negative_int(raw_time.get(key))


def parse_assistant_usage_record(
    *, message_id: str, data_json: str
) -> AssistantUsageRecord | None:
    """Parse one opencode ``message.data`` JSON value."""
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("role") != "assistant":
        return None

    model_id = str(data.get("modelID") or "").strip()
    if not model_id:
        return None

    tokens = data.get("tokens")
    token_data = tokens if isinstance(tokens, Mapping) else {}
    prompt_tokens = _coerce_non_negative_int(token_data.get("input")) or 0
    completion_tokens = _coerce_non_negative_int(token_data.get("output")) or 0
    total_tokens = (
        _coerce_non_negative_int(token_data.get("total"))
        or prompt_tokens + completion_tokens
    )
    if prompt_tokens + completion_tokens == 0 and total_tokens > 0:
        prompt_tokens = total_tokens

    provider_id = data.get("providerID")
    return AssistantUsageRecord(
        message_id=message_id,
        model_id=model_id,
        provider_id=str(provider_id).strip() if provider_id is not None else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=_coerce_non_negative_float(data.get("cost")),
        time_created=_message_time(data, "created"),
        time_completed=_message_time(data, "completed"),
        raw=data,
    )


def _query_sessions(connection: sqlite3.Connection) -> Iterable[OpencodeSessionRow]:
    rows = connection.execute(
        """
        SELECT id, directory, time_created, time_updated, title
        FROM session
        ORDER BY time_updated ASC, id ASC
        """
    )
    for row in rows:
        yield OpencodeSessionRow(
            session_id=str(row[0]),
            directory=str(row[1]) if row[1] is not None else None,
            time_created=_coerce_non_negative_int(row[2]),
            time_updated=_coerce_non_negative_int(row[3]),
            title=str(row[4]) if row[4] is not None else None,
        )


def _query_usage_records(
    connection: sqlite3.Connection, session_id: str
) -> list[AssistantUsageRecord]:
    rows = connection.execute(
        """
        SELECT id, data
        FROM message
        WHERE session_id = ?
        ORDER BY time_created ASC, id ASC
        """,
        (session_id,),
    )
    records: list[AssistantUsageRecord] = []
    for message_id, data_json in rows:
        if not isinstance(data_json, str):
            continue
        record = parse_assistant_usage_record(
            message_id=str(message_id), data_json=data_json
        )
        if record is not None:
            records.append(record)
    return records


def _session_model_id(records: list[AssistantUsageRecord]) -> str:
    model_ids = {record.model_id for record in records}
    if len(model_ids) == 1:
        return records[-1].model_id
    return "opencode-mixed-models"


def _usage_source(records: list[AssistantUsageRecord]) -> str:
    usage_present = any(record.total_tokens > 0 for record in records)
    has_cost = any(record.cost_usd is not None for record in records)
    if usage_present and has_cost:
        return "API"
    if usage_present:
        return "ESTIMATED"
    return "MISSING"


def build_opencode_cost_payload(
    *,
    session: OpencodeSessionRow,
    records: list[AssistantUsageRecord],
    env: Mapping[str, str],
) -> dict[str, object] | None:
    """Build one deterministic cost payload for an opencode session."""
    if not records:
        return None

    prompt_tokens = sum(record.prompt_tokens for record in records)
    completion_tokens = sum(record.completion_tokens for record in records)
    total_tokens = sum(record.total_tokens for record in records)
    if total_tokens < prompt_tokens + completion_tokens:
        total_tokens = prompt_tokens + completion_tokens

    model_id = _session_model_id(records)
    usage_source = _usage_source(records)
    if usage_source == "API":
        cost_usd = round(sum(record.cost_usd or 0.0 for record in records), 6)
    elif usage_source == "ESTIMATED":
        cost_usd = estimate_cost_usd(
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    else:
        cost_usd = 0.0

    repo_name = derive_repo_name(env.get("OMNI_HOME"), session.directory)
    machine_id = derive_machine_id(dict(env))
    started_at = min(
        [
            value
            for value in [session.time_created, *(r.time_created for r in records)]
            if value is not None
        ],
        default=session.time_created,
    )
    ended_at = max(
        [
            value
            for value in [session.time_updated, *(r.time_completed for r in records)]
            if value is not None
        ],
        default=session.time_updated,
    )
    source_payload = {
        "tool_source": TOOL_SOURCE,
        "session": {
            "id": session.session_id,
            "directory": session.directory,
            "time_created": session.time_created,
            "time_updated": session.time_updated,
            "title": session.title,
        },
        "assistant_records": [record.raw for record in records],
    }
    input_hash = _sha256_key(source_payload)
    idempotency_key = _sha256_key(
        {
            "tool_source": TOOL_SOURCE,
            "session_id": session.session_id,
            "model_id": model_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "source_payload_hash": input_hash,
        }
    )

    emitted_at = _timestamp_iso(
        ended_at or session.time_updated or session.time_created
    )
    return {
        "session_id": session.session_id,
        "model_id": model_id,
        "provider_id": records[-1].provider_id,
        "correlation_id": session.session_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "estimated_cost_usd": cost_usd,
        "cost_usd": cost_usd,
        "timestamp_iso": emitted_at,
        "emitted_at": emitted_at,
        "request_type": "session",
        "reporting_source": "omniclaude",
        "tool_source": TOOL_SOURCE,
        "source": TOOL_SOURCE,
        "usage_source": usage_source,
        "request_count": len(records),
        "repo_name": repo_name,
        "machine_id": machine_id,
        "input_hash": input_hash,
        "idempotency_key": idempotency_key,
        "idempotency_version": "opencode-session-cost-v1",
    }


def scan_opencode_cost_payloads(
    *, db_path: Path = DEFAULT_DB_PATH, env: Mapping[str, str] | None = None
) -> list[dict[str, object]]:
    """Return cost payloads for all opencode sessions in ``db_path``."""
    if not db_path.is_file():
        return []

    payloads: list[dict[str, object]] = []
    # di-ok: read-only access to external opencode DB, no adapter abstraction applies
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        for session in _query_sessions(connection):
            records = _query_usage_records(connection, session.session_id)
            payload = build_opencode_cost_payload(
                session=session,
                records=records,
                env=env or os.environ,
            )
            if payload is not None:
                payloads.append(payload)
    return payloads


def emit_opencode_cost_payloads(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str, dict[str, object]], bool] | None = None,
) -> int:
    """Emit opencode session cost payloads and return the number accepted."""
    if emit is None:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        emit = emit_event

    accepted = 0
    for payload in scan_opencode_cost_payloads(db_path=db_path, env=env):
        if emit(EVENT_TYPE, payload):
            accepted += 1
    return accepted


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="write payloads to stdout instead of emitting via the hook daemon",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    db_path = args.db_path.expanduser()
    if not db_path.is_file():
        sys.stderr.write(
            f"opencode session db not found at {db_path}; nothing to emit\n"
        )
        return 0

    if args.jsonl:
        for payload in scan_opencode_cost_payloads(db_path=db_path, env=os.environ):
            sys.stdout.write(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
            )
        return 0

    emit_opencode_cost_payloads(db_path=db_path, env=os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
