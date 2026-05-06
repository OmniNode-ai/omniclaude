#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse delegation hook runner (OMN-10607).

Invoked by pre_tool_use_delegation.sh with serialized tool input on stdin.
Runs SensitivityGate then TaskClassifier; prints a one-line result to stdout:

  not_delegatable  — gate or classifier rejected delegation
  DELEGATED: <task_type> routed to <model>  — placeholder until OMN-10610

Exit codes:
  0 — classification complete (check stdout for result)
  1 — unrecoverable error (caller treats as not_delegatable)
"""

from __future__ import annotations

import json
import sys
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


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

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
            result = gate.check(tool_text)
            if result.is_sensitive:
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
                print(f"DELEGATED: {task_type} routed to {model}")
                return 0
        except Exception:  # noqa: BLE001
            pass  # Fail open

    print("not_delegatable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
