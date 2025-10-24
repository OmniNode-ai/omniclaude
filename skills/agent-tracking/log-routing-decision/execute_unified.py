#!/usr/bin/env python3
"""
Log Routing Decision Skill - Unified Event Adapter Version

Publishes routing decisions using the unified HookEventAdapter instead of
direct Kafka calls. This ensures consistent event publishing across all hooks.

Usage:
  /log-routing-decision --agent AGENT_NAME --confidence 0.95 --strategy enhanced_fuzzy_matching --latency-ms 45

Options:
  --agent: Selected agent name (required)
  --confidence: Confidence score 0.0-1.0 (required)
  --strategy: Routing strategy used (required)
  --latency-ms: Routing latency in milliseconds (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --user-request: Original user request text (optional)
  --alternatives: JSON array of alternative agents considered (optional)
  --reasoning: Reasoning for agent selection (optional)
  --context: JSON object with additional context (optional)
"""

import argparse
import json
import sys
from pathlib import Path

# Add hooks/lib to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "hooks" / "lib"))
from hook_event_adapter import get_hook_event_adapter

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id, parse_json_param


def log_routing_decision_unified(args):
    """Log routing decision using unified event adapter."""

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse JSON parameters
    alternatives = (
        parse_json_param(args.alternatives)
        if hasattr(args, "alternatives") and args.alternatives
        else []
    )
    context = (
        parse_json_param(args.context)
        if hasattr(args, "context") and args.context
        else {}
    )

    # Add correlation_id to context
    context["correlation_id"] = correlation_id

    # Validate confidence score
    confidence = float(args.confidence)
    if confidence < 0.0 or confidence > 1.0:
        error = {
            "success": False,
            "error": f"Confidence score must be between 0.0 and 1.0, got {confidence}",
        }
        print(json.dumps(error), file=sys.stderr)
        return 1

    # Get hook event adapter
    adapter = get_hook_event_adapter()

    # Publish routing decision event
    success = adapter.publish_routing_decision(
        agent_name=args.agent,
        confidence=confidence,
        strategy=args.strategy,
        latency_ms=int(args.latency_ms),
        correlation_id=correlation_id,
        user_request=(
            args.user_request
            if hasattr(args, "user_request") and args.user_request
            else None
        ),
        alternatives=alternatives,
        reasoning=(
            args.reasoning if hasattr(args, "reasoning") and args.reasoning else None
        ),
        context=context,
    )

    if success:
        output = {
            "success": True,
            "correlation_id": correlation_id,
            "selected_agent": args.agent,
            "confidence_score": confidence,
            "routing_strategy": args.strategy,
            "routing_time_ms": int(args.latency_ms),
            "published_via": "unified_event_adapter",
            "topic": "agent-routing-decisions",
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        error = {
            "success": False,
            "error": "Failed to publish routing decision event",
            "hint": "Check hook_event_adapter logs for details",
        }
        print(json.dumps(error), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent routing decision via unified event adapter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Selected agent name")
    parser.add_argument(
        "--confidence", required=True, type=float, help="Confidence score (0.0-1.0)"
    )
    parser.add_argument("--strategy", required=True, help="Routing strategy used")
    parser.add_argument(
        "--latency-ms", required=True, type=int, help="Routing latency in milliseconds"
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--user-request", help="Original user request text")
    parser.add_argument("--alternatives", help="JSON array of alternative agents")
    parser.add_argument("--reasoning", help="Reasoning for agent selection")
    parser.add_argument("--context", help="JSON object with additional context")

    args = parser.parse_args()

    return log_routing_decision_unified(args)


if __name__ == "__main__":
    sys.exit(main())
