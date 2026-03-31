#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Intent Drift Emitter -- PostToolUse drift detection and event emission.

Thin wrapper that:
1. Reads the session's classified intent from correlation state
2. Calls detect_drift() from intent_drift_detector.py
3. Formats the payload to match what omnidash's projectIntentDriftDetected expects
4. Emits to onex.evt.omniintelligence.intent-drift-detected.v1 via emit daemon

This is the canonical Phase 1 producer for the intent-drift-detected topic.

Non-blocking: called from a background subshell in PostToolUse. All failures
are logged and swallowed -- never raises, never blocks the hook.

CLI:
    python3 intent_drift_emitter.py \\
        --session-id <uuid> --tool-name <name> [--file-path <path>]

Related:
    - OMN-6809: Intent drift events empty
    - OMN-7141: Intent classification pipeline tuneup
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Path bootstrap for standalone script execution
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_log = logging.getLogger(__name__)


def build_drift_payload(
    *,
    session_id: str,
    original_intent: str,
    detected_intent: str,
    drift_score: float,
    severity: str,
    tool_name: str,
    file_path: str = "",
) -> dict[str, Any]:
    """Build the Kafka payload for intent-drift-detected.v1.

    Field names match what omnidash's projectIntentDriftDetected expects:
        session_id, original_intent, current_intent, drift_score, severity

    Note: DriftSignal uses 'detected_intent' but the projection expects
    'current_intent' -- this function performs the mapping.
    """
    return {
        "session_id": session_id,
        "original_intent": original_intent,
        "current_intent": detected_intent,
        "drift_score": drift_score,
        "severity": severity,
        "tool_name": tool_name,
        "file_path": file_path,
    }


def check_and_emit_drift(
    *,
    session_id: str,
    tool_name: str,
    file_path: str = "",
    state_dir: Path | None = None,
    emit_fn: Any | None = None,
) -> bool:
    """Check for intent drift and emit event if detected.

    Args:
        session_id: Current session UUID.
        tool_name: Tool being used (e.g. "Read", "Edit", "Bash").
        file_path: Optional file path being operated on.
        state_dir: Override state directory (for testing).
        emit_fn: Callable(event_type, payload_json) for event emission.
                 If None, uses emit_via_daemon from emit_client_wrapper.

    Returns:
        True if a drift event was emitted, False otherwise.
    """
    try:
        # 1. Read stored session intent
        from intent_classifier import get_intent_from_correlation

        intent_data = get_intent_from_correlation(state_dir=state_dir)
        if intent_data is None:
            _log.debug("No stored session intent -- skipping drift check")
            return False

        original_intent = intent_data.get("intent_class", "")
        if not original_intent:
            _log.debug("Empty intent_class in correlation state -- skipping")
            return False

        # 2. Detect drift
        from intent_drift_detector import DriftSignal, detect_drift

        signal: DriftSignal | None = detect_drift(
            original_intent=original_intent,
            tool_name=tool_name,
            file_path=file_path,
        )

        if signal is None:
            _log.debug(
                "No drift detected for tool=%s intent=%s", tool_name, original_intent
            )
            return False

        # 3. Build payload with field mapping
        payload = build_drift_payload(
            session_id=session_id,
            original_intent=signal.original_intent,
            detected_intent=signal.detected_intent,
            drift_score=signal.drift_score,
            severity=signal.severity,
            tool_name=signal.tool_name,
            file_path=signal.file_path,
        )

        # 4. Emit via daemon
        payload_json = json.dumps(payload)

        if emit_fn is not None:
            emit_fn("intent.drift.detected", payload_json)
        else:
            from emit_client_wrapper import emit_via_daemon

            emit_via_daemon("intent.drift.detected", payload_json)

        _log.debug(
            "Emitted intent-drift-detected: score=%.2f severity=%s",
            signal.drift_score,
            signal.severity,
        )
        return True

    except Exception as exc:  # noqa: BLE001
        _log.debug("Intent drift emitter failed (non-fatal): %s", exc)
        return False


# ---------------------------------------------------------------------------
# CLI entry point (for shell scripts)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point -- check drift and emit event.

    Always exits 0. Failures are swallowed (non-blocking).
    """
    parser = argparse.ArgumentParser(description="Intent drift emitter")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--file-path", default="")
    args = parser.parse_args()

    check_and_emit_drift(
        session_id=args.session_id,
        tool_name=args.tool_name,
        file_path=args.file_path,
    )


if __name__ == "__main__":
    main()
