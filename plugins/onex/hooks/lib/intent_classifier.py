#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Intent Classifier - Correlation state management for intent data

Stores and retrieves intent classification data in the correlation state file.
Intent classification itself flows through the Kafka event bus:
  hook emits onex.cmd.omniintelligence.claude-hook-event.v1
  → NodeIntentClassifierCompute handles it asynchronously
  → publishes onex.evt.omniintelligence.intent-classified.v1

The synchronous HTTP classify endpoint was removed in OMN-2875 — it never
existed and always returned 404.

The CLI entry point emits success=false so the shell hook proceeds without
synchronous classification (consistent with fire-and-forget event bus design).

Usage (as CLI):
    python3 intent_classifier.py --session-id <sid> --correlation-id <cid> \
        --prompt-b64 <base64-prompt>

Output JSON:
    {
        "success": false,
        "intent_id": "abc123",
        "intent_class": "GENERAL",
        "confidence": 0.0,
        "elapsed_ms": 0
    }
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

logger = logging.getLogger(__name__)

# Default intent class
_DEFAULT_INTENT_CLASS = "GENERAL"


def store_intent_in_correlation(
    *,
    intent_id: str,
    intent_class: str,
    confidence: float,
    state_dir: Path | None = None,
) -> bool:
    """Persist intent_id and intent_class in the correlation state file.

    Merges intent fields into the existing correlation state without
    overwriting other fields. Safe to call multiple times (idempotent).

    Args:
        intent_id: UUID for this intent classification.
        intent_class: Classified intent class string.
        confidence: Classification confidence score.
        state_dir: Override state directory (for testing).

    Returns:
        True if stored successfully, False on any failure.
    """
    try:
        if state_dir is None:
            state_dir = Path.home() / ".claude" / "hooks" / ".state"

        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = Path(state_dir) / "correlation_id.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)

        existing: dict[str, Any] = {}
        if state_file.exists():
            try:
                with open(state_file, encoding="utf-8") as fh:
                    existing = json.load(fh)
            except Exception:
                existing = {}

        existing["intent_id"] = intent_id
        existing["intent_class"] = intent_class
        existing["intent_confidence"] = confidence

        tmp = state_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(existing, fh)
        tmp.replace(state_file)

        return True

    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to persist intent in correlation state: %s", exc)
        return False


def get_intent_from_correlation(
    state_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Retrieve stored intent from the correlation state file.

    Args:
        state_dir: Override state directory (for testing).

    Returns:
        Dict with intent_id, intent_class, intent_confidence or None if absent.
    """
    try:
        if state_dir is None:
            state_dir = Path.home() / ".claude" / "hooks" / ".state"

        state_file = Path(state_dir) / "correlation_id.json"
        if not state_file.exists():
            return None

        with open(state_file, encoding="utf-8") as fh:
            state: dict[str, Any] = json.load(fh)

        if "intent_id" not in state or "intent_class" not in state:
            return None

        return {
            "intent_id": state["intent_id"],
            "intent_class": state["intent_class"],
            "intent_confidence": state.get("intent_confidence", 0.0),
        }

    except Exception:  # pylint: disable=broad-except
        return None


# ---------------------------------------------------------------------------
# CLI entry point (for shell scripts)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point — reads args, emits success=false (classification is async).

    Intent classification flows through the Kafka event bus, not synchronous HTTP.
    This CLI exists to satisfy the shell hook invocation contract; it always
    returns success=false so the hook proceeds without inline intent context.

    Always exits 0. Output is JSON on stdout.
    """
    import argparse

    logging.basicConfig(
        level=logging.WARNING,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(
        description="Intent classifier CLI (event-bus mode)"
    )
    parser.add_argument("--session-id", default="", help="Session ID")
    parser.add_argument("--correlation-id", default="", help="Correlation ID")
    parser.add_argument(
        "--prompt-b64",
        default="",
        help="Base64-encoded prompt (mutually exclusive with --prompt-stdin)",
    )
    parser.add_argument(
        "--prompt-stdin",
        action="store_true",
        help="Read raw prompt from stdin",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Skip storing result in correlation file (for testing)",
    )
    args = parser.parse_args()

    # Consume stdin/prompt args to maintain CLI compatibility; value is unused
    # because classification is handled asynchronously by NodeIntentClassifierCompute.
    if args.prompt_stdin:
        try:
            raw_b64 = sys.stdin.read().strip()
            base64.b64decode(raw_b64).decode("utf-8", "replace")
        except Exception:
            pass
    elif args.prompt_b64:
        try:
            base64.b64decode(args.prompt_b64).decode("utf-8", "replace")
        except Exception:
            pass

    result: dict[str, Any] = {
        "success": False,
        "intent_id": str(uuid.uuid4()),
        "intent_class": _DEFAULT_INTENT_CLASS,
        "confidence": 0.0,
        "elapsed_ms": 0,
    }

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
