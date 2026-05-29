#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse delegation hook runner (OMN-10607).

Invoked by pre_tool_use_delegation.sh with serialized tool input on stdin.
Runs SensitivityGate then TaskClassifier; prints a one-line result to stdout:

  not_delegatable            — gate or classifier rejected delegation
  not_delegatable:sensitive  — sensitivity gate blocked
  DELEGATED: <task_type> routed to <model>  — delegatable; JSON telemetry on next line

When delegatable, a second JSON line is printed immediately after DELEGATED:.
This JSON conforms to ModelHookDelegationTelemetry and contains runtime-compatible
fields (correlation_id, task_type, routing_policy_hash, tokens_input, tokens_output,
cost_usd, quality_result). All fields are NON-AUTHORITATIVE — see
hook_delegation_telemetry.py for per-field caveats.

The shell caller (pre_tool_use_delegation.sh) reads only the first line for its
exit-code decision; the second line is forwarded to emit_via_daemon for telemetry.

Exit codes:
  0 — classification complete (check stdout for result)
  1 — unrecoverable error (caller treats as not_delegatable)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from the plugin lib dir or repo root
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_PLUGIN_ROOT = _HERE.parent.parent  # hooks/lib -> hooks -> plugins/onex
_REPO_ROOT = _PLUGIN_ROOT.parent.parent  # plugins/onex -> omniclaude root

for _candidate in [
    _REPO_ROOT / "src",
    _REPO_ROOT,
]:
    if _candidate.exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _import_gate():  # type: ignore[return]
    try:
        from omniclaude.delegation.sensitivity_gate import SensitivityGate

        return SensitivityGate()
    except Exception:  # noqa: BLE001
        return None


def _import_classifier():  # type: ignore[return]
    try:
        from omniclaude.lib.task_classifier import TaskClassifier

        return TaskClassifier()
    except Exception:  # noqa: BLE001
        return None


def _import_telemetry():  # type: ignore[return]
    try:
        from hook_delegation_telemetry import (  # type: ignore[import-not-found]
            ModelHookDelegationTelemetry,
            build_routing_policy_hash,
        )

        return ModelHookDelegationTelemetry, build_routing_policy_hash
    except Exception:  # noqa: BLE001
        return None, None


def _build_telemetry_json(
    task_type: str,
    model: str,
    latency_ms: int,
    correlation_id: str,
    session_id: str,
) -> str:
    """Build NON-AUTHORITATIVE telemetry JSON for a delegatable classification.

    Returns an empty string when hook_delegation_telemetry is unavailable so
    the caller can skip emitting rather than failing.
    """
    TelemetryClass, hash_fn = _import_telemetry()
    if TelemetryClass is None or hash_fn is None:
        return ""
    try:
        telemetry = TelemetryClass(
            correlation_id=correlation_id,
            session_id=session_id,
            task_type=task_type,
            delegated_to=model,
            routing_policy_hash=hash_fn(),
            delegation_latency_ms=latency_ms,
            # tokens_input / tokens_output / cost_usd stay 0 — hook has no LLM usage
        )
        return json.dumps(telemetry.to_dict())
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    t0 = time.monotonic()

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    # Extract correlation_id and session_id forwarded from the shell hook
    correlation_id = ""
    session_id = ""
    if isinstance(payload, dict):
        correlation_id = str(payload.get("correlation_id", ""))
        session_id = str(payload.get("session_id", ""))
    # Fallback to env vars set by the shell hook wrapper
    if not correlation_id:
        correlation_id = os.environ.get("HOOK_CORRELATION_ID", "")
    if not session_id:
        session_id = os.environ.get("CLAUDE_SESSION_ID", "")

    # Flatten tool_input to a string for gate + classifier
    tool_input = (
        payload.get("tool_input", payload) if isinstance(payload, dict) else payload
    )
    if isinstance(tool_input, dict):
        tool_text = json.dumps(tool_input)
    else:
        tool_text = str(tool_input)

    # --- Sensitivity gate ---
    gate = _import_gate()
    if gate is not None:
        try:
            gate_result = gate.check(tool_text)
            if gate_result.is_sensitive:
                print("not_delegatable:sensitive")
                return 0
        except Exception:  # noqa: BLE001
            pass  # Fail open — proceed to classifier

    # --- Task classifier ---
    classifier = _import_classifier()
    if classifier is not None:
        try:
            score = classifier.is_delegatable(tool_text)
            if score.delegatable:
                model = score.delegate_to_model or "local-model"
                task_type = score.classified_intent
                latency_ms = int((time.monotonic() - t0) * 1000)
                print(f"DELEGATED: {task_type} routed to {model}")
                # Emit NON-AUTHORITATIVE telemetry on a second line.
                # Shell caller reads only the first line; this line is for
                # emit_via_daemon consumption.
                telemetry_json = _build_telemetry_json(
                    task_type=task_type,
                    model=model,
                    latency_ms=latency_ms,
                    correlation_id=correlation_id,
                    session_id=session_id,
                )
                if telemetry_json:
                    print(telemetry_json)
                return 0
        except Exception:  # noqa: BLE001
            pass  # Fail open

    print("not_delegatable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
