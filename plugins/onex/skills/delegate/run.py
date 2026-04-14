#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill — classify prompt and publish to delegation-request topic.

Invoked when the user runs /onex:delegate.  Classifies the prompt via
TaskClassifier, wraps it in a ModelEventEnvelope-compatible dict, and publishes
to onex.cmd.omnibase-infra.delegation-request.v1 via the omniclaude emit daemon.

Wire schema (plain dict — runtime-side validation by node_delegation_orchestrator):
  {
    "payload": {
      "prompt": str,
      "task_type": "test" | "document" | "research",
      "source_session_id": str | None,
      "source_file_path": str | None,
      "correlation_id": str (UUID4),
      "max_tokens": int,
      "emitted_at": str (ISO-8601),
    },
    "correlation_id": str,
    "event_type": "omnibase-infra.delegation-request",
    "source_tool": "omniclaude.delegate-skill",
  }
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------
_SKILL_DIR = Path(__file__).parent
_HOOKS_LIB = _SKILL_DIR.parent.parent / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _SKILL_DIR.parent.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    from omniclaude.lib.task_classifier import TaskClassifier, TaskIntent

    _HAS_CLASSIFIER = True
except ImportError:
    _HAS_CLASSIFIER = False

try:
    from omniclaude.hooks.topics import TopicBase as _TopicBase

    _DELEGATION_REQUEST_TOPIC: str = _TopicBase.DELEGATION_REQUEST
except (ImportError, AttributeError):
    _DELEGATION_REQUEST_TOPIC = ""  # fallback; emit still works via event_type key

DELEGATABLE: frozenset[object] = (
    frozenset({TaskIntent.TEST, TaskIntent.DOCUMENT, TaskIntent.RESEARCH})
    if _HAS_CLASSIFIER
    else frozenset()
)

# ---------------------------------------------------------------------------
# Core publish function
# ---------------------------------------------------------------------------


def classify_and_publish(
    prompt: str,
    source_file: str | None = None,
    max_tokens: int = 2048,
) -> dict:
    """Classify *prompt* and publish a delegation request via the emit daemon.

    Returns a result dict with keys: success, correlation_id, task_type, topic.
    On failure, returns success=False with an error message.
    """
    if not _HAS_CLASSIFIER:
        return {
            "success": False,
            "error": "TaskClassifier unavailable — omniclaude package not on sys.path",
        }

    classifier = TaskClassifier()
    result = classifier.classify(prompt)

    if result.intent not in DELEGATABLE:
        return {
            "success": False,
            "error": (
                f"Task type '{result.intent.value}' is not delegatable. "
                "Only test/document/research tasks can be delegated."
            ),
        }

    correlation_id = str(uuid.uuid4())
    now_iso = datetime.now(UTC).isoformat()

    delegation_payload = {
        "prompt": prompt,
        "task_type": result.intent.value,
        "source_session_id": os.environ.get("CLAUDE_SESSION_ID"),
        "source_file_path": source_file,
        "correlation_id": correlation_id,
        "max_tokens": max_tokens,
        "emitted_at": now_iso,
    }

    envelope = {
        "payload": delegation_payload,
        "correlation_id": correlation_id,
        "event_type": "omnibase-infra.delegation-request",
        "source_tool": "omniclaude.delegate-skill",
    }

    emitted = False
    try:
        from emit_client_wrapper import emit_event  # type: ignore[import-not-found]

        emitted = bool(emit_event("delegation.request", envelope))
    except ImportError:
        pass

    if not emitted:
        return {
            "success": False,
            "error": "emit_event returned falsy — delegation request not queued",
            "correlation_id": correlation_id,
            "topic": _DELEGATION_REQUEST_TOPIC,
            "envelope": envelope,
        }

    return {
        "success": True,
        "correlation_id": correlation_id,
        "task_type": result.intent.value,
        "topic": _DELEGATION_REQUEST_TOPIC,
    }


# ---------------------------------------------------------------------------
# CLI entry point (called from SKILL.md dispatch)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: python run.py <prompt> [--source-file <path>] [--max-tokens <n>]"""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Delegate skill — publish to delegation topic"
    )
    parser.add_argument("prompt", nargs="+", help="The task to delegate")
    parser.add_argument("--source-file", default=None)
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()

    prompt = " ".join(args.prompt)
    result = classify_and_publish(
        prompt=prompt,
        source_file=args.source_file,
        max_tokens=args.max_tokens,
    )

    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(
            f"\nDelegation queued — correlation_id={result['correlation_id']}\n"
            f"task_type={result['task_type']}\n"
            f"topic={result['topic']}",
            file=sys.stderr,
        )
    else:
        print(f"\nDelegation failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
