# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lightweight client-side intent drift detector for PostToolUse hooks.

Pure computation function that detects when a tool call suggests the
session has drifted from its original classified intent. Returns a
drift signal (score + severity) when drift is detected, or None when
the tool usage is consistent with the original intent.

This is a lightweight client-side approximation. The authoritative
server-side drift detector lives in omniintelligence's
NodeIntentDriftDetectCompute.

When drift is detected, the caller emits to
``onex.evt.omniintelligence.intent-drift-detected.v1`` via the
emit daemon.

Related:
    - OMN-6809: Intent drift events empty
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Intent-to-expected-tools mapping. Tools outside expected set raise drift score.
_INTENT_EXPECTED_TOOLS: dict[str, frozenset[str]] = {
    "code_generation": frozenset({"Write", "Edit", "Bash", "Read", "Glob", "Grep"}),
    "bug_fix": frozenset({"Read", "Edit", "Bash", "Grep", "Glob"}),
    "refactoring": frozenset({"Read", "Edit", "Grep", "Glob", "Bash"}),
    "documentation": frozenset({"Read", "Write", "Edit", "Glob"}),
    "testing": frozenset({"Read", "Write", "Edit", "Bash", "Grep", "Glob"}),
    "investigation": frozenset({"Read", "Grep", "Glob", "Bash"}),
    "devops": frozenset({"Bash", "Read", "Write", "Edit", "Glob"}),
    "conversation": frozenset(set()),  # No tools expected
}

# File extension patterns that suggest specific intents
_FILE_INTENT_SIGNALS: dict[str, str] = {
    ".test.": "testing",
    "_test.": "testing",
    "test_": "testing",
    ".spec.": "testing",
    ".md": "documentation",
    "README": "documentation",
    "CHANGELOG": "documentation",
    ".yml": "devops",
    ".yaml": "devops",
    "Dockerfile": "devops",
    ".tf": "devops",
}


@dataclass(frozen=True, slots=True)
class DriftSignal:
    """Detected intent drift signal."""

    drift_score: float
    severity: str
    original_intent: str
    detected_intent: str
    tool_name: str
    file_path: str


def detect_drift(
    *,
    original_intent: str,
    tool_name: str,
    file_path: str = "",
) -> DriftSignal | None:
    """Detect intent drift from a tool call.

    Pure computation -- no I/O, no side effects.

    Args:
        original_intent: The classified intent for the session.
        tool_name: The tool being used (e.g. "Read", "Edit", "Bash").
        file_path: Optional file path being operated on.

    Returns:
        DriftSignal if drift is detected, None otherwise.
    """
    if not original_intent or not tool_name:
        return None

    intent_lower = original_intent.lower().replace("-", "_").replace(" ", "_")
    expected_tools = _INTENT_EXPECTED_TOOLS.get(intent_lower)

    if expected_tools is None:
        # Unknown intent -- cannot detect drift
        return None

    # Check if tool is outside expected set for this intent
    tool_drift_score = 0.0
    if expected_tools and tool_name not in expected_tools:
        tool_drift_score = 0.4

    # Check file path for intent signals
    file_intent = _infer_intent_from_file(file_path)
    file_drift_score = 0.0
    if file_intent and file_intent != intent_lower:
        file_drift_score = 0.3

    total_score = min(1.0, tool_drift_score + file_drift_score)

    if total_score < 0.3:
        return None

    severity = "low"
    if total_score >= 0.7:
        severity = "high"
    elif total_score >= 0.5:
        severity = "medium"

    detected = file_intent or "unknown"

    return DriftSignal(
        drift_score=total_score,
        severity=severity,
        original_intent=original_intent,
        detected_intent=detected,
        tool_name=tool_name,
        file_path=file_path,
    )


def _infer_intent_from_file(file_path: str) -> str | None:
    """Infer intent from file path patterns."""
    if not file_path:
        return None

    for pattern, intent in _FILE_INTENT_SIGNALS.items():
        if pattern in file_path:
            return intent

    return None


__all__ = [
    "DriftSignal",
    "detect_drift",
]
