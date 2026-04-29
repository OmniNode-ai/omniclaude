# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Normalize Claude SessionEnd token usage into llm.cost.completed payloads."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from omniclaude.hooks.session_cost_common import (
    build_cost_payload,
    derive_machine_id,
    derive_repo_name,
    stable_payload_hash,
)


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _nested_get(data: Mapping[str, object], path: tuple[str, ...]) -> object | None:
    current: object = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def extract_session_tokens(
    session_end_payload: Mapping[str, object],
) -> tuple[int, int] | None:
    """Extract token usage from Claude SessionEnd payload fields."""
    prompt_count = _coerce_non_negative_int(
        _nested_get(
            session_end_payload, ("context_window", "current_usage", "input_tokens")
        )
    )
    completion_count = _coerce_non_negative_int(
        _nested_get(
            session_end_payload, ("context_window", "current_usage", "output_tokens")
        )
    )
    if prompt_count is None and completion_count is None:
        return None
    return prompt_count or 0, completion_count or 0


def read_accumulator_tokens(accumulator_path: Path) -> tuple[int, int] | None:
    """Read accumulated token usage from the checked SessionEnd accumulator."""
    try:
        raw = json.loads(accumulator_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    input_tokens = _coerce_non_negative_int(raw.get("total_input_tokens")) or 0
    output_tokens = _coerce_non_negative_int(raw.get("total_output_tokens")) or 0
    if input_tokens + output_tokens <= 0:
        return None
    return input_tokens, output_tokens


def find_accumulator_path(session_id: str | None, accumulator_dir: Path) -> Path | None:
    """Resolve the accumulator for the current session only."""
    if not session_id:
        return None
    candidate = accumulator_dir / f"omniclaude-session-{session_id}.json"
    return candidate if candidate.is_file() else None


def _session_id_from_accumulator(path: Path) -> str | None:
    name = path.name
    prefix = "omniclaude-session-"
    suffix = ".json"
    if name.startswith(prefix) and name.endswith(suffix):
        return name[len(prefix) : -len(suffix)]
    return None


def _payload_timestamp(session_end_payload: Mapping[str, object]) -> str:
    for key in ("emitted_at", "timestamp_iso", "timestamp", "ended_at"):
        value = session_end_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_session_cost_payload(
    *,
    session_end_payload: Mapping[str, object],
    env: dict[str, str],
    session_id: str | None = None,
    correlation_id: str | None = None,
    accumulator_dir: Path = Path("/tmp"),  # noqa: S108  # nosec B108 - Claude accumulator lives in /tmp.
) -> dict[str, object] | None:
    """Build a canonical cost payload from SessionEnd JSON and accumulator state."""
    usage_origin = "session_end"
    tokens = extract_session_tokens(session_end_payload)
    accumulator_path: Path | None = None

    resolved_session_id = (
        (session_id or "").strip()
        or str(session_end_payload.get("sessionId") or "").strip()
        or str(session_end_payload.get("session_id") or "").strip()
    )
    if tokens is None or sum(tokens) <= 0:
        accumulator_path = find_accumulator_path(
            resolved_session_id or None, accumulator_dir
        )
        if accumulator_path is not None:
            tokens = read_accumulator_tokens(accumulator_path)
            usage_origin = "accumulator"
            if not resolved_session_id:
                resolved_session_id = (
                    _session_id_from_accumulator(accumulator_path) or ""
                )

    if tokens is None or sum(tokens) <= 0:
        return None

    if not resolved_session_id:
        resolved_session_id = (
            f"claude-session-{stable_payload_hash(session_end_payload)[:24]}"
        )

    project_dir = (
        env.get("CLAUDE_PROJECT_DIR")
        or env.get("HOOK_ORIGINAL_CWD")
        or env.get("PWD")
        or None
    )
    repo_name = derive_repo_name(env.get("OMNI_HOME"), project_dir)
    machine_id = derive_machine_id(env)
    model_id = session_end_payload.get("model") or session_end_payload.get("model_id")
    input_hash_source: dict[str, object] = {
        "session_end": session_end_payload,
        "usage_origin": usage_origin,
        "prompt_tokens": tokens[0],
        "completion_tokens": tokens[1],
        "repo_name": repo_name,
        "machine_id": machine_id,
    }
    if accumulator_path is not None:
        input_hash_source["accumulator_file"] = accumulator_path.name

    return build_cost_payload(
        session_id=resolved_session_id,
        model_id=str(model_id) if model_id is not None else None,
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        correlation_id=correlation_id,
        emitted_at=_payload_timestamp(session_end_payload),
        repo_name=repo_name,
        machine_id=machine_id,
        input_hash_source=input_hash_source,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--correlation-id", default="")
    parser.add_argument("--accumulator-dir", default="/tmp")  # noqa: S108  # nosec B108
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        session_end_payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"invalid SessionEnd JSON: {exc}\n")
        return 2
    if not isinstance(session_end_payload, dict):
        sys.stderr.write("SessionEnd JSON must be an object\n")
        return 2

    payload = normalize_session_cost_payload(
        session_end_payload=session_end_payload,
        env=dict(os.environ),
        session_id=args.session_id,
        correlation_id=args.correlation_id,
        accumulator_dir=Path(args.accumulator_dir),
    )
    if payload is None:
        return 1

    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
