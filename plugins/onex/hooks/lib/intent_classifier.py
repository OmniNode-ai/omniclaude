#!/usr/bin/env python3
"""
Intent Classifier - Async intent classification for UserPromptSubmit

Classifies user prompts against the omniintelligence intent classification
service. Non-blocking: the classification result is stored in the correlation
file for downstream consumption. Exits 0 on all failures.

Design:
- 1s wall-clock timeout (consistent with context injection budget)
- Falls back gracefully when the service is unavailable
- Stores intent_id + intent_class in correlation state for PostToolUse hooks

Usage (as CLI):
    python3 intent_classifier.py --session-id <sid> --correlation-id <cid> \
        --prompt-b64 <base64-prompt>

Output JSON:
    {
        "success": true,
        "intent_id": "abc123",
        "intent_class": "SECURITY",
        "confidence": 0.94,
        "elapsed_ms": 42
    }
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

logger = logging.getLogger(__name__)

# Timeout for classification HTTP call (seconds)
_CLASSIFICATION_TIMEOUT_S = 0.9  # 100ms margin below 1s wall-clock budget

# Default intent class when classification fails
_DEFAULT_INTENT_CLASS = "GENERAL"


def _get_classification_url() -> str:
    """Resolve the intent classification endpoint URL.

    Priority:
    1. OMNICLAUDE_INTENT_API_URL env var (explicit override)
    2. INTELLIGENCE_SERVICE_URL env var + /api/v1/intent/classify path
    3. http://localhost:8053/api/v1/intent/classify (last resort)
    """
    import os

    explicit = os.environ.get("OMNICLAUDE_INTENT_API_URL", "").strip()
    if explicit:
        return explicit

    base = os.environ.get("INTELLIGENCE_SERVICE_URL", "").strip()
    if base:
        return base.rstrip("/") + "/api/v1/intent/classify"

    return "http://localhost:8053/api/v1/intent/classify"


def classify_intent(
    *,
    prompt: str,
    session_id: str = "",
    correlation_id: str = "",
    timeout_s: float = _CLASSIFICATION_TIMEOUT_S,
) -> dict[str, Any]:
    """Classify user prompt intent via omniintelligence HTTP API.

    Non-blocking design: returns empty result dict on any failure so callers
    can proceed without classification. Never raises.

    Args:
        prompt: User prompt text to classify.
        session_id: Session identifier for request context.
        correlation_id: Correlation ID for distributed tracing.
        timeout_s: HTTP request timeout (default 0.9s).

    Returns:
        Dict with keys:
            success (bool): True if classification succeeded.
            intent_id (str): UUID for this classification.
            intent_class (str): Classified intent (e.g. "SECURITY", "GENERAL").
            confidence (float): Classification confidence 0.0-1.0.
            elapsed_ms (int): Time taken in milliseconds.
    """
    start = time.monotonic()
    intent_id = str(uuid.uuid4())
    empty_result: dict[str, Any] = {
        "success": False,
        "intent_id": intent_id,
        "intent_class": _DEFAULT_INTENT_CLASS,
        "confidence": 0.0,
        "elapsed_ms": 0,
    }

    try:
        url = _get_classification_url()
        payload = json.dumps(
            {
                "prompt": prompt,
                "session_id": session_id,
                "correlation_id": correlation_id,
                "intent_id": intent_id,
            }
        ).encode("utf-8")

        req = urllib.request.Request(  # noqa: S310  # nosec B310
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310  # nosec B310
            raw = resp.read().decode("utf-8")

        data: dict[str, Any] = json.loads(raw)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        intent_class = str(data.get("intent_class", _DEFAULT_INTENT_CLASS)).upper()
        confidence = float(data.get("confidence", 0.0))
        returned_intent_id = str(data.get("intent_id", intent_id))

        return {
            "success": True,
            "intent_id": returned_intent_id,
            "intent_class": intent_class,
            "confidence": confidence,
            "elapsed_ms": elapsed_ms,
        }

    except urllib.error.URLError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Intent classification service unavailable: %s", exc)
        empty_result["elapsed_ms"] = elapsed_ms
        return empty_result

    except TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Intent classification timed out after %.1fs", timeout_s)
        empty_result["elapsed_ms"] = elapsed_ms
        return empty_result

    except Exception as exc:  # pylint: disable=broad-except
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Intent classification failed: %s", exc)
        empty_result["elapsed_ms"] = elapsed_ms
        return empty_result


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
    """CLI entry point — reads args, classifies prompt, stores result.

    Always exits 0. Output is JSON on stdout.
    """
    import argparse
    import os

    logging.basicConfig(
        level=logging.WARNING,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Classify user prompt intent")
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

    # Resolve prompt
    if args.prompt_stdin:
        # stdin carries the base64-encoded prompt (same convention as
        # local_delegation_handler.py --prompt-stdin).  Decode it so the
        # classifier works on the actual prompt text, not the base64 bytes.
        raw_b64 = sys.stdin.read().strip()
        try:
            prompt = base64.b64decode(raw_b64).decode("utf-8", "replace")
        except Exception:
            prompt = ""
    elif args.prompt_b64:
        try:
            prompt = base64.b64decode(args.prompt_b64).decode("utf-8", "replace")
        except Exception:
            prompt = ""
    else:
        prompt = ""

    if not prompt.strip():
        result: dict[str, Any] = {
            "success": False,
            "intent_id": str(uuid.uuid4()),
            "intent_class": _DEFAULT_INTENT_CLASS,
            "confidence": 0.0,
            "elapsed_ms": 0,
        }
        print(json.dumps(result))
        sys.exit(0)

    result = classify_intent(
        prompt=prompt,
        session_id=args.session_id,
        correlation_id=args.correlation_id,
    )

    # Store in correlation state unless suppressed
    if not args.no_store and result.get("success"):
        state_dir_env = os.environ.get("OMNICLAUDE_STATE_DIR", "")
        state_dir: Path | None = Path(state_dir_env) if state_dir_env else None
        store_intent_in_correlation(
            intent_id=result["intent_id"],
            intent_class=result["intent_class"],
            confidence=float(result.get("confidence", 0.0)),
            state_dir=state_dir,
        )

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
