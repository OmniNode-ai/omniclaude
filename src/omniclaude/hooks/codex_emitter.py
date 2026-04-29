# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Normalize Codex JSONL session logs into llm.cost.completed payloads."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from omniclaude.hooks.session_cost_common import (
    build_cost_payload,
    derive_machine_id,
    derive_repo_name,
    stable_payload_hash,
)

EVENT_TYPE = "llm.cost.completed"
TOOL_SOURCE = "codex"
NO_LOG_MESSAGE = "codex session log not found; nothing to emit"
DEFAULT_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
DEFAULT_STATE_FILE = (
    Path.home() / ".cache" / "omniclaude" / ("codex-session-cost-emitted.json")
)


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def discover_codex_session_logs(sessions_dir: Path) -> list[Path]:
    """Return Codex session JSONL logs in deterministic oldest-first order."""
    try:
        logs = [path for path in sessions_dir.glob("*/*/*/*.jsonl") if path.is_file()]
    except OSError:
        return []
    return sorted(logs, key=lambda path: (path.stat().st_mtime, str(path)))


def _record_payload(record: Mapping[str, object]) -> Mapping[str, object]:
    payload = record.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _event_payload_type(record: Mapping[str, object]) -> str | None:
    if record.get("type") != "event_msg":
        return None
    event_payload = _record_payload(record)
    value = event_payload.get("type")
    return value if isinstance(value, str) else None


def _find_session_meta(records: Iterable[Mapping[str, object]]) -> Mapping[str, object]:
    for record in records:
        if record.get("type") == "session_meta":
            return _record_payload(record)
    return {}


def _find_latest_token_usage(
    records: Iterable[Mapping[str, object]],
) -> tuple[Mapping[str, object], str | None]:
    latest_usage: Mapping[str, object] = {}
    latest_timestamp: str | None = None
    for record in records:
        if _event_payload_type(record) != "token_count":
            continue
        payload = _record_payload(record)
        info = payload.get("info")
        if not isinstance(info, Mapping):
            continue
        total_usage = info.get("total_token_usage")
        if isinstance(total_usage, Mapping):
            latest_usage = total_usage
            timestamp = record.get("timestamp")
            latest_timestamp = timestamp if isinstance(timestamp, str) else None
    return latest_usage, latest_timestamp


def _find_task_complete_timestamp(
    records: Iterable[Mapping[str, object]],
) -> str | None:
    for record in records:
        if _event_payload_type(record) != "task_complete":
            continue
        payload = _record_payload(record)
        completed_at = _coerce_non_negative_int(payload.get("completed_at"))
        if completed_at is not None:
            return datetime.fromtimestamp(completed_at, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and timestamp.strip():
            return timestamp.strip()
    return None


def _tokens_from_usage(usage: Mapping[str, object]) -> tuple[int, int, str]:
    prompt_count = _coerce_non_negative_int(usage.get("input_tokens"))
    completion_count = _coerce_non_negative_int(usage.get("output_tokens"))
    if prompt_count is not None or completion_count is not None:
        return prompt_count or 0, completion_count or 0, "API"

    total_tokens = _coerce_non_negative_int(usage.get("total_tokens"))
    if total_tokens is not None:
        return total_tokens, 0, "ESTIMATED"

    return 0, 0, "MISSING"


def _model_id(meta: Mapping[str, object]) -> str:
    for key in ("model", "model_id", "model_slug"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    provider = meta.get("model_provider") or meta.get("provider")
    if isinstance(provider, str) and provider.strip():
        return f"codex-{provider.strip()}"
    return "codex-unknown"


def _session_id_from_path(path: Path) -> str:
    digest = stable_payload_hash({"path": str(path), "name": path.name})
    return f"codex-session-{digest[:24]}"


def _prefixed_idempotency_key(
    *,
    session_id: str,
    repo_name: str | None,
    machine_id: str | None,
) -> str:
    digest = stable_payload_hash(
        {
            "event_type": EVENT_TYPE,
            "session_id": session_id,
            "repo_name": repo_name,
            "machine_id": machine_id,
            "tool_source": TOOL_SOURCE,
        }
    )
    return f"sha256-{digest}"


def normalize_codex_session_log(
    log_path: Path,
    *,
    env: dict[str, str],
) -> dict[str, object] | None:
    """Build a canonical cost payload from one Codex session JSONL file."""
    records = _read_jsonl(log_path)
    if not records:
        return None

    meta = _find_session_meta(records)
    session_id = str(meta.get("id") or "").strip() or _session_id_from_path(log_path)
    cwd = str(meta.get("cwd") or "").strip() or None
    repo_name = derive_repo_name(env.get("OMNI_HOME"), cwd)
    machine_id = derive_machine_id(env)
    token_usage, token_timestamp = _find_latest_token_usage(records)
    prompt_tokens, completion_tokens, usage_source = _tokens_from_usage(token_usage)
    emitted_at = (
        _find_task_complete_timestamp(records)
        or token_timestamp
        or str(meta.get("timestamp") or "").strip()
        or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    input_hash_source: dict[str, object] = {
        "log_file": log_path.name,
        "session_id": session_id,
        "cwd": cwd,
        "token_usage": dict(token_usage),
        "usage_source": usage_source,
        "tool_source": TOOL_SOURCE,
    }
    payload = build_cost_payload(
        session_id=session_id,
        model_id=_model_id(meta),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        correlation_id=None,
        emitted_at=emitted_at,
        repo_name=repo_name,
        machine_id=machine_id,
        input_hash_source=input_hash_source,
    )
    payload["idempotency_key"] = _prefixed_idempotency_key(
        session_id=session_id,
        repo_name=repo_name,
        machine_id=machine_id,
    )
    payload["idempotency_version"] = "codex-session-cost-v1"
    payload["tool_source"] = TOOL_SOURCE
    payload["usage_source"] = usage_source
    payload["codex_log_path"] = str(log_path)
    payload["codex_cli_version"] = meta.get("cli_version")
    payload["codex_originator"] = meta.get("originator")
    return payload


def _load_emitted_keys(state_file: Path) -> set[str]:
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    keys = raw.get("idempotency_keys") if isinstance(raw, dict) else None
    if not isinstance(keys, list):
        return set()
    return {key for key in keys if isinstance(key, str)}


def _write_emitted_keys(state_file: Path, keys: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"idempotency_keys": sorted(keys)}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def emit_codex_session_costs(
    *,
    sessions_dir: Path,
    state_file: Path,
    env: dict[str, str],
    emit_func: Callable[[str, dict[str, object]], bool],
) -> tuple[int, int]:
    """Emit unseen Codex session cost payloads.

    Returns ``(emitted_count, skipped_count)``.
    """
    logs = discover_codex_session_logs(sessions_dir)
    if not logs:
        sys.stderr.write(f"{NO_LOG_MESSAGE}\n")
        return 0, 0

    emitted_keys = _load_emitted_keys(state_file)
    emitted_count = 0
    skipped_count = 0
    changed = False
    for log_path in logs:
        payload = normalize_codex_session_log(log_path, env=env)
        if payload is None:
            continue
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or key in emitted_keys:
            skipped_count += 1
            continue
        if emit_func(EVENT_TYPE, payload):
            emitted_keys.add(key)
            emitted_count += 1
            changed = True
    if changed:
        _write_emitted_keys(state_file, emitted_keys)
    return emitted_count, skipped_count


def _default_emit(event_type: str, payload: dict[str, object]) -> bool:
    try:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event
    except ImportError:
        sys.stderr.write("emit client unavailable; codex cost payload not emitted\n")
        return False
    return bool(emit_event(event_type, payload))


def _stdout_emit(event_type: str, payload: dict[str, object]) -> bool:
    sys.stdout.write(
        json.dumps(
            {"event_type": event_type, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return True


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", default=str(DEFAULT_CODEX_SESSIONS_DIR))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="write normalized events to stdout instead of the emit daemon",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    emit_func = _stdout_emit if args.stdout else _default_emit
    emitted_count, skipped_count = emit_codex_session_costs(
        sessions_dir=Path(args.sessions_dir).expanduser(),
        state_file=Path(args.state_file).expanduser(),
        env=dict(os.environ),
        emit_func=emit_func,
    )
    sys.stderr.write(
        f"codex session cost scan complete: emitted={emitted_count} "
        f"skipped={skipped_count}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
