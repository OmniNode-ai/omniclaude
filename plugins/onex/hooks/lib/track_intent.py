#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Track Intent - Log user intent for analytics

Stub module retained for CLI compatibility.  The PostgreSQL HookEventLogger
that previously powered track_intent was removed in OMN-5139 (Kafka is the
canonical observability path).  The function now returns None immediately.

Usage:
    echo "user prompt" | python3 track_intent.py --prompt - --agent AGENT --domain DOMAIN
"""

import argparse
import logging
import sys

logger = logging.getLogger(__name__)


def track_intent(
    prompt: str,
    agent: str,
    domain: str,
    purpose: str,
    correlation_id: str,
    session_id: str,
) -> str | None:
    """Track user intent event.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for CLI compat.
    """
    logger.info("Intent tracking skipped (PostgreSQL logger removed in OMN-5139)")
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
        # No longer an error — PostgreSQL logger was removed in OMN-5139
        sys.exit(0)


if __name__ == "__main__":
    main()
