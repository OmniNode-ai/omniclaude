#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Commit Intent Binder -- M1 (OMN-2492).

Detects git commits in PostToolUse Bash tool output, reads the active
intent_id from the correlation state file, and emits an intent-to-commit
binding event via the emit daemon.

Design constraints:
    - NEVER raises or exits non-zero -- all failures are logged and swallowed
    - Non-blocking: called from a background subshell in the PostToolUse hook
    - Correlation state is read-only (written by intent_classifier.py)
    - Emit daemon call is best-effort; data loss is acceptable

CLI:
    echo '<tool_info_json>' | python commit_intent_binder.py \\
        --session-id <uuid> [--state-dir ~/.claude/hooks/.state]

Storage layout (read-only):
    ~/.claude/hooks/.state/correlation_id.json   (written by intent_classifier)

Emit event type: ``intent.commit.bound`` (added to SUPPORTED_EVENT_TYPES)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap: allow running as a standalone script or via pytest
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATE_DIR_DEFAULT = Path.home() / ".claude" / "hooks" / ".state"

# Regex: match a git commit SHA in tool output.
# Accepts both long (40-char) and short (7-12 char) hex SHAs that appear
# after common git commit output markers.
_COMMIT_SHA_RE = re.compile(
    r"(?:^\[|\s\[)(?:[^\]]*?\s)?([0-9a-f]{7,40})\]",
    re.MULTILINE,
)

# Also match "master|main|<branch> <sha>" format:  "[main abc1234]"
_GIT_COMMIT_LINE_RE = re.compile(
    r"\[[\w/.\-]+ ([0-9a-f]{7,40})\]",
)


# ---------------------------------------------------------------------------
# Public dataclass: binding record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentCommitBinding:
    """Immutable binding record linking an intent_id to a commit SHA.

    Fields:
        intent_id: UUID string from correlation state (may be empty).
        commit_sha: Git commit SHA extracted from tool output.
        session_id: Claude Code session ID.
        correlation_id: Correlation ID from session state (may be empty).
        bound_at: ISO-8601 timestamp of binding creation.
    """

    intent_id: str
    commit_sha: str
    session_id: str
    correlation_id: str
    bound_at: str


# ---------------------------------------------------------------------------
# Commit detection
# ---------------------------------------------------------------------------


def detect_commit_sha(tool_name: str, tool_response: Any) -> str | None:
    """Extract a git commit SHA from a Bash PostToolUse payload.

    Args:
        tool_name: Name of the tool that was invoked ("Bash").
        tool_response: The ``tool_response`` field from PostToolUse stdin JSON.

    Returns:
        Commit SHA string on success, None if no commit detected or tool is
        not a Bash invocation that produced a git commit.
    """
    if tool_name != "Bash":
        return None

    # tool_response may be a string or a nested object
    output: str = ""
    if isinstance(tool_response, str):
        output = tool_response
    elif isinstance(tool_response, dict):
        output = (
            tool_response.get("output")
            or tool_response.get("content")
            or tool_response.get("stdout")
            or ""
        )
        if not isinstance(output, str):
            output = str(output)

    if not output:
        return None

    # Quick heuristic: "git commit" lines always contain "[<branch> <sha>]"
    match = _GIT_COMMIT_LINE_RE.search(output)
    if match:
        return match.group(1)

    # Broader fallback for other git output formats
    match = _COMMIT_SHA_RE.search(output)
    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------------------------
# Intent reader
# ---------------------------------------------------------------------------


def read_intent_from_state(state_dir: Path | None = None) -> dict[str, str]:
    """Read intent_id, intent_class, and correlation_id from state file.

    Returns:
        Dict with keys ``intent_id``, ``intent_class``, ``correlation_id``.
        Values are empty strings if not present or on any error.
    """
    result: dict[str, str] = {
        "intent_id": "",
        "intent_class": "",
        "correlation_id": "",
    }
    sd = state_dir or _STATE_DIR_DEFAULT
    state_file = sd / "correlation_id.json"
    try:
        if not state_file.exists():
            return result
        data = json.loads(state_file.read_text(encoding="utf-8"))
        result["intent_id"] = data.get("intent_id", "") or ""
        result["intent_class"] = data.get("intent_class", "") or ""
        result["correlation_id"] = data.get("correlation_id", "") or ""
    except Exception as exc:  # noqa: BLE001
        _log.debug("Could not read intent state from %s: %s", state_file, exc)
    return result


# ---------------------------------------------------------------------------
# Emit binding
# ---------------------------------------------------------------------------


def emit_binding(binding: IntentCommitBinding) -> bool:
    """Emit an intent-to-commit binding event via the emit daemon.

    Uses ``emit_client_wrapper.emit_event``.  Returns True on success,
    False on any failure (never raises).
    """
    try:
        from emit_client_wrapper import emit_event

        payload: dict[str, Any] = {
            "intent_id": binding.intent_id,
            "commit_sha": binding.commit_sha,
            "session_id": binding.session_id,
            "correlation_id": binding.correlation_id,
            "bound_at": binding.bound_at,
        }
        return emit_event("intent.commit.bound", payload)
    except Exception as exc:  # noqa: BLE001
        _log.warning("emit_binding failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------


def process_tool_use(
    tool_info: dict[str, Any],
    *,
    session_id: str = "",
    state_dir: Path | None = None,
    now_iso: str | None = None,
) -> IntentCommitBinding | None:
    """Process a PostToolUse payload and emit a binding if a commit is found.

    This is the primary callable for tests and the shell hook integration.

    Args:
        tool_info: Parsed JSON from PostToolUse stdin.
        session_id: Session ID (falls back to ``tool_info["sessionId"]``).
        state_dir: Override for state directory (tests only).
        now_iso: Explicit ISO-8601 timestamp (tests only; defaults to utcnow).

    Returns:
        IntentCommitBinding if a commit was detected and a binding was
        created.  None otherwise.
    """
    try:
        tool_name: str = tool_info.get("tool_name", "") or ""
        tool_response: Any = tool_info.get("tool_response")
        if not session_id:
            session_id = tool_info.get("sessionId") or tool_info.get("session_id") or ""

        sha = detect_commit_sha(tool_name, tool_response)
        if sha is None:
            return None

        state = read_intent_from_state(state_dir)
        ts = now_iso or datetime.now(UTC).isoformat()

        binding = IntentCommitBinding(
            intent_id=state["intent_id"],
            commit_sha=sha,
            session_id=session_id,
            correlation_id=state["correlation_id"],
            bound_at=ts,
        )

        try:
            emit_binding(binding)
        except Exception as emit_exc:  # noqa: BLE001
            _log.warning("emit_binding raised (non-fatal): %s", emit_exc)

        _log.info(
            "Bound commit %s to intent %s (session=%s)",
            sha,
            state["intent_id"] or "(none)",
            session_id,
        )
        return binding

    except Exception as exc:  # noqa: BLE001
        _log.warning("process_tool_use error (non-fatal): %s", exc)
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point -- always exits 0."""
    parser = argparse.ArgumentParser(
        description="Bind git commits to active intent (PostToolUse hook)",
    )
    parser.add_argument("--session-id", default="", help="Claude Code session ID")
    parser.add_argument(
        "--state-dir",
        default="",
        help="Override correlation state directory (testing)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(fh)

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        tool_info = json.loads(raw)
        state_dir = Path(args.state_dir) if args.state_dir else None
        process_tool_use(
            tool_info,
            session_id=args.session_id,
            state_dir=state_dir,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("commit_intent_binder CLI error (non-fatal): %s", exc)

    sys.exit(0)


if __name__ == "__main__":
    main()


__all__ = [
    "IntentCommitBinding",
    "detect_commit_sha",
    "emit_binding",
    "process_tool_use",
    "read_intent_from_state",
]
