#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Emit a cost event JSON file after each codex CLI invocation.

Discovery (2026-05-01): `codex review --commit <sha>` does not support --json
and produces no token usage in its output. Token usage IS available from
`codex exec --json` via `turn.completed` JSONL events, but the hostile_reviewer
uses `codex review`, not `codex exec`. Therefore usage_source is UNKNOWN for
all hostile_reviewer codex invocations.

Usage:
    emit_codex_invocation_cost(
        result=subprocess_result,
        session_id="...",
        correlation_id="...",
    )
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path


def emit_codex_invocation_cost(
    *,
    correlation_id: str | None = None,
    session_id: str | None = None,
    omni_home: str | None = None,
) -> Path | None:
    """Write a cost event JSON file for one codex CLI invocation.

    Token counts are always 0 / usage_source UNKNOWN because `codex review`
    does not expose token usage in its output.

    Returns the path written, or None if OMNI_HOME is not set.
    """
    resolved_omni_home = omni_home or os.environ.get("OMNI_HOME", "")
    if not resolved_omni_home:
        print(
            "[codex_cost_wrapper] OMNI_HOME not set; cost event not written",
            file=sys.stderr,
        )
        return None

    from plugins.onex.hooks.lib.session_id import resolve_session_id  # noqa: PLC0415

    resolved_session_id = (
        session_id or resolve_session_id(default="") or str(uuid.uuid4())
    )
    resolved_correlation_id = correlation_id or str(uuid.uuid4())
    emitted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    event: dict[str, object] = {
        "model_name": "codex",
        "model_id": "codex",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "session_id": resolved_session_id,
        "correlation_id": resolved_correlation_id,
        "usage_source": "UNKNOWN",
        "reporting_source": "codex",
        "estimation_method": "codex_cli_no_usage_output",
        "emitted_at": emitted_at,
    }

    events_dir = Path(resolved_omni_home) / ".onex_state" / "llm-cost-events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_path = events_dir / f"codex-{resolved_correlation_id}.json"
    event_path.write_text(
        json.dumps(event, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return event_path
