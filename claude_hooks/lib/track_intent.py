#!/usr/bin/env python3
"""Track user intent patterns for analytics.

This script captures user intents (natural language requests) and tracks them
as patterns in the Phase 4 Pattern Traceability system. This enables analytics
like "When users ask for X, what patterns emerge in the generated code?"

Usage:
    python3 track_intent.py \
        --prompt "optimize my API performance" \
        --agent "agent-performance" \
        --domain "api_development" \
        --purpose "Performance optimization" \
        --correlation-id "abc-123" \
        --session-id "def-456"
"""

import sys
import argparse
import hashlib
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from pattern_tracker_sync import PatternTrackerSync


def generate_intent_id(prompt: str, agent: str) -> str:
    """Generate deterministic intent pattern ID.

    Args:
        prompt: User's natural language request
        agent: Agent name being invoked

    Returns:
        16-character hex string identifier
    """
    combined = f"{agent}:{prompt[:200]}"  # Agent + first 200 chars
    hash_obj = hashlib.sha256(combined.encode())
    return f"intent-{hash_obj.hexdigest()[:12]}"


def extract_intent_summary(prompt: str, max_length: int = 100) -> str:
    """Extract concise intent summary from prompt.

    Args:
        prompt: Full user prompt
        max_length: Maximum summary length

    Returns:
        Concise intent summary
    """
    # Remove agent invocation syntax
    summary = prompt.strip()
    for prefix in ["@", "^", "use "]:
        if summary.startswith(prefix):
            parts = summary.split(None, 1)
            if len(parts) > 1:
                summary = parts[1]

    # Truncate if too long
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."

    return summary


def main():
    parser = argparse.ArgumentParser(description="Track user intent patterns")
    parser.add_argument("--prompt", required=True, help="User's natural language prompt")
    parser.add_argument("--agent", required=True, help="Agent name being invoked")
    parser.add_argument("--domain", required=True, help="Agent domain")
    parser.add_argument("--purpose", required=True, help="Agent purpose")
    parser.add_argument("--correlation-id", required=True, help="Request correlation ID")
    parser.add_argument("--session-id", required=False, help="Session ID (optional)")
    args = parser.parse_args()

    try:
        # Initialize tracker with session ID
        tracker = PatternTrackerSync(session_id=args.session_id)

        # Generate intent ID
        intent_id = generate_intent_id(args.prompt, args.agent)
        intent_summary = extract_intent_summary(args.prompt)

        print(f"📝 [track_intent] Tracking intent: {intent_summary}", file=sys.stderr)
        print(f"   Agent: {args.agent}", file=sys.stderr)
        print(f"   Intent ID: {intent_id}", file=sys.stderr)

        # Track intent as a pattern
        pattern_id = tracker.track_pattern_creation(
            code=args.prompt,  # User's natural language request
            context={
                "event_type": "pattern_created",  # Use valid event type
                "tool": "UserPromptSubmit",
                "language": "natural_language",
                "file_path": f"intents/{args.agent}/{intent_id}.txt",
                "agent_invoked": args.agent,
                "agent_domain": args.domain,
                "agent_purpose": args.purpose,
                "correlation_id": args.correlation_id,
                "session_id": tracker.session_id,
                "intent_type": "agent_request",
                "intent_summary": intent_summary,
                "source": "claude_code_hook",
                "timestamp": datetime.utcnow().isoformat(),
                "quality_score": 1.0,  # Intents don't have quality violations
                "violations_found": 0,
                "reason": f"User requested {args.agent} agent for: {intent_summary}"
            }
        )

        if pattern_id:
            print(f"✅ [track_intent] Intent pattern tracked: {pattern_id}", file=sys.stderr)
            print(f"   This intent can be correlated with generated code patterns", file=sys.stderr)
            print(f"   Correlation ID: {args.correlation_id}", file=sys.stderr)
            sys.exit(0)
        else:
            print(f"❌ [track_intent] Intent tracking returned None", file=sys.stderr)
            # Don't fail the hook - just log
            sys.exit(0)

    except Exception as e:
        print(f"❌ [track_intent] Unexpected exception: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        # Don't fail the hook - graceful degradation
        sys.exit(0)


if __name__ == "__main__":
    main()
