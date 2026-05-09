# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PostToolUse cost accounting for OMN-10619.

Records per-tool-call cost data to SQLite. For delegated calls (Agent/Task that
were intercepted by the PreToolUse model router), records the actual model used
and estimates savings vs the Opus baseline. For non-delegated calls, records the
Opus baseline cost.

All savings are counterfactual estimates labeled with baseline_model and
pricing_manifest_version. Token counts carry a token_provenance field:
MEASURED when the tool response includes usage data, ESTIMATED otherwise.

Import-safety: sqlite_adapter is imported lazily so this module loads cleanly
even when the adapter hasn't landed yet (other tasks in the OMN-10604 wave).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

# Pricing manifest — all prices in USD per 1M tokens.
# Labeled so every record carries the version it was computed from.
PRICING_MANIFEST_VERSION = "2026-05-06-v1"
PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    # Local models have zero marginal API cost
    "local": {"input": 0.00, "output": 0.00},
}
BASELINE_MODEL = "claude-opus-4-6"

# Delegation result file written by PreToolUse model router hook.
# Convention from OMN-10606: PreToolUse writes the delegation result here
# after intercepting an Agent/Task call.
_DELEGATION_RESULT_FILENAME = "pending_result.json"


def _delegation_result_path() -> Path | None:
    state_dir = os.environ.get("ONEX_STATE_DIR", "")
    if not state_dir:
        return None
    return Path(state_dir) / "delegation" / _DELEGATION_RESULT_FILENAME


def _db_path() -> Path | None:
    state_dir = os.environ.get("ONEX_STATE_DIR", "")
    if not state_dir:
        return None
    return Path(state_dir) / "hooks" / "cost_accounting.db"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            is_delegated INTEGER NOT NULL DEFAULT 0,
            actual_model TEXT NOT NULL,
            baseline_model TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            token_provenance TEXT NOT NULL,
            actual_cost_usd REAL NOT NULL,
            baseline_cost_usd REAL NOT NULL,
            savings_usd REAL NOT NULL,
            savings_method TEXT NOT NULL,
            pricing_manifest_version TEXT NOT NULL
        )
    """)
    conn.commit()


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = PRICING_USD_PER_1M.get(model, PRICING_USD_PER_1M[BASELINE_MODEL])
    return (
        input_tokens * pricing["input"] + output_tokens * pricing["output"]
    ) / 1_000_000


def _savings_method(actual_model: str) -> str:
    pricing = PRICING_USD_PER_1M.get(actual_model)
    if pricing and pricing["input"] == 0.0 and pricing["output"] == 0.0:
        return "zero_marginal_api_cost"
    return "counterfactual_price_difference"


def _extract_token_counts(
    hook_event: dict[str, Any],
    delegation_result: dict[str, Any] | None,
) -> tuple[int, int, str]:
    """Return (input_tokens, output_tokens, provenance)."""
    # Prefer usage data from delegation result (more authoritative)
    if delegation_result:
        usage = delegation_result.get("usage", {})
        if usage.get("input_tokens") or usage.get("output_tokens"):
            return (
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                "MEASURED",
            )

    # Try tool_response usage
    tool_response = hook_event.get("tool_response", {})
    usage = tool_response.get("usage", {})
    if usage.get("input_tokens") or usage.get("output_tokens"):
        return (
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            "MEASURED",
        )

    # Estimate from response content length as rough proxy
    content = str(tool_response.get("content", "") or tool_response.get("output", ""))
    estimated_output = max(1, len(content) // 4)
    return (0, estimated_output, "ESTIMATED")


def record_tool_call(hook_event: dict[str, Any]) -> dict[str, Any] | None:
    """Record cost data for one tool call. Returns delegation result dict if present.

    Returns the delegation result so the shell hook can inject it as
    hookSpecificOutput.additionalContext (the proven OMN-10606 mechanism).
    Returns None when no delegation result is pending.
    """
    tool_name = hook_event.get("tool_name", "unknown")
    session_id = hook_event.get("session_id", os.environ.get("CLAUDE_SESSION_ID", ""))

    # Load pending delegation result if one exists
    delegation_result: dict[str, Any] | None = None
    result_path = _delegation_result_path()
    if result_path and result_path.exists():
        try:
            raw = result_path.read_text(encoding="utf-8")
            delegation_result = json.loads(raw)
            result_path.unlink(missing_ok=True)
        except Exception:
            delegation_result = None

    is_delegated = delegation_result is not None
    actual_model = (
        delegation_result.get("model", "local") if delegation_result else BASELINE_MODEL
    )

    input_tokens, output_tokens, token_provenance = _extract_token_counts(
        hook_event, delegation_result
    )

    actual_cost = _cost_usd(actual_model, input_tokens, output_tokens)
    baseline_cost = _cost_usd(BASELINE_MODEL, input_tokens, output_tokens)
    savings = max(0.0, baseline_cost - actual_cost)
    savings_method = _savings_method(actual_model) if is_delegated else "baseline_self"

    record: dict[str, Any] = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": tool_name,
        "is_delegated": int(is_delegated),
        "actual_model": actual_model,
        "baseline_model": BASELINE_MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "token_provenance": token_provenance,
        "actual_cost_usd": actual_cost,
        "baseline_cost_usd": baseline_cost,
        "savings_usd": savings,
        "savings_method": savings_method,
        "pricing_manifest_version": PRICING_MANIFEST_VERSION,
    }

    _write_record(record)
    return delegation_result if is_delegated else None


def _write_record(record: dict[str, Any]) -> None:
    db = _db_path()
    if db is None:
        return

    try:
        from plugins.onex.hooks.lib.cost_accounting_adapter import insert_cost_record

        db.parent.mkdir(parents=True, exist_ok=True)
        insert_cost_record(str(db), _ensure_schema, record)
    except Exception:
        pass


if __name__ == "__main__":
    import sys

    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    if tool_name not in ("Agent", "Task", "TaskCreate", "TaskUpdate"):
        sys.exit(0)

    delegation_result = record_tool_call(event)

    if delegation_result:
        context = delegation_result.get("context", "")
        if context:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": str(context),
                }
            }
            print(json.dumps(out))
