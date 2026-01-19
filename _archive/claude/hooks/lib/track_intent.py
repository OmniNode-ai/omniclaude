#!/usr/bin/env python3
"""
Track Intent - Log user intent for analytics

Tracks and logs user intent classification for analytics and optimization.

Usage:
    echo "user prompt" | python3 track_intent.py --prompt - --agent AGENT --domain DOMAIN
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
# This enables imports like 'from hook_event_logger import ...' to work
# regardless of the current working directory
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import HookEventLogger with graceful fallback
_HookEventLoggerClass: type[Any] | None = None
try:
    from hook_event_logger import HookEventLogger

    _HookEventLoggerClass = HookEventLogger
except ImportError:
    _HookEventLoggerClass = None


logger = logging.getLogger(__name__)


def track_intent(
    prompt: str,
    agent: str,
    domain: str,
    purpose: str,
    correlation_id: str,
    session_id: str,
) -> str | None:
    """
    Track user intent event.

    Args:
        prompt: User prompt
        agent: Detected agent
        domain: Agent domain
        purpose: Agent purpose
        correlation_id: Correlation ID
        session_id: Session ID

    Returns:
        Event ID if logged successfully
    """
    try:
        # Use pre-imported class for graceful degradation
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        event_logger = _HookEventLoggerClass()

        # Classify intent from prompt
        intent_type = _classify_intent(prompt)

        return event_logger.log_event(
            source="IntentTracker",
            action="intent_tracked",
            resource="intent",
            resource_id=intent_type,
            payload={
                "prompt_preview": prompt[:200] if prompt else "",
                "intent_type": intent_type,
                "agent": agent,
                "domain": domain,
                "purpose": purpose,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            metadata={
                "hook_type": "IntentTracker",
                "correlation_id": correlation_id,
                "session_id": session_id,
                "agent_name": agent,
                "domain": domain,
            },
        )
    except Exception as e:
        logger.error(f"Failed to track intent: {e}")
        return None


def _classify_intent(prompt: str) -> str:
    """Classify the intent type from prompt."""
    prompt_lower = prompt.lower()

    if any(word in prompt_lower for word in ["fix", "bug", "error", "broken"]):
        return "bug_fix"
    elif any(word in prompt_lower for word in ["add", "create", "implement", "new"]):
        return "feature"
    elif any(word in prompt_lower for word in ["refactor", "improve", "optimize"]):
        return "refactor"
    elif any(word in prompt_lower for word in ["test", "testing", "spec"]):
        return "testing"
    elif any(word in prompt_lower for word in ["document", "docs", "readme"]):
        return "documentation"
    elif any(word in prompt_lower for word in ["review", "check", "analyze"]):
        return "review"
    else:
        return "general"


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Track user intent")
    parser.add_argument(
        "--prompt",
        required=True,
        help="User prompt (use - to read from stdin)",
    )
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--domain", required=True, help="Agent domain")
    parser.add_argument("--purpose", required=True, help="Agent purpose")
    parser.add_argument("--correlation-id", required=True, help="Correlation ID")
    parser.add_argument("--session-id", required=True, help="Session ID")

    args = parser.parse_args()

    # Read prompt from stdin if specified
    if args.prompt == "-":
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt

    event_id = track_intent(
        prompt=prompt,
        agent=args.agent,
        domain=args.domain,
        purpose=args.purpose,
        correlation_id=args.correlation_id,
        session_id=args.session_id,
    )

    if event_id:
        print(f"Intent tracked: {event_id}")
    else:
        print("Failed to track intent", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
