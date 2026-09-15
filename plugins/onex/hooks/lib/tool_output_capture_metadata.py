#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Emit metadata about Bash output without changing the model-visible result."""

from __future__ import annotations

import json
import sys
from typing import Any


def build_capture_metadata(payload: dict[str, Any]) -> dict[str, object] | None:
    """Reduce one hook payload to contract-declared, content-free metadata."""
    from skill_output_suppressor import evaluate_payload

    if payload.get("tool_name") != "Bash":
        return None
    session_id = payload.get("session_id") or payload.get("sessionId")
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    evaluation = evaluate_payload(payload)
    return {
        "tool_name": "Bash",
        "suppression_decision": evaluation.decision.value,
        "correlation_id": session_id,
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "command_type": evaluation.command_type,
        "original_bytes": evaluation.original_bytes,
        "original_lines": evaluation.original_lines,
    }


def emit_metadata(payload: dict[str, Any]) -> bool:
    """Emit only a reduced payload through the local semantic daemon."""
    metadata = build_capture_metadata(payload)
    if metadata is None:
        return False
    from emit_client_wrapper import emit_event

    return emit_event("tool.output.captured", metadata)


def main() -> int:
    """Read one PostToolUse payload; stdout remains empty for every outcome."""
    try:
        raw = json.load(sys.stdin)
        if isinstance(raw, dict):
            emit_metadata(raw)
    except Exception:  # noqa: BLE001 -- advisory hook must never block Claude
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
