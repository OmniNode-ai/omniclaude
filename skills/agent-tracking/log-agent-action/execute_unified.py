#!/usr/bin/env python3
"""
Log Agent Action Skill - Unified Event Adapter Version

Publishes agent actions using the unified HookEventAdapter.

Usage:
  /log-agent-action --agent AGENT_NAME --action-type TYPE --action-name NAME --details JSON

Options:
  --agent: Agent name performing the action (required)
  --action-type: Type of action (tool_call|decision|error|success) (required)
  --action-name: Specific action name (required)
  --details: JSON object with action-specific details (optional)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --duration-ms: How long the action took in milliseconds (optional)
  --success: Whether action succeeded (default: true)
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


def main():
    parser = argparse.ArgumentParser(
        description="Log agent action via unified event adapter",
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--action-type", required=True, help="Action type")
    parser.add_argument("--action-name", required=True, help="Action name")

    # Optional arguments
    parser.add_argument("--details", help="JSON object with details")
    parser.add_argument("--correlation-id", help="Correlation ID")
    parser.add_argument("--duration-ms", type=int, help="Duration in milliseconds")
    parser.add_argument("--success", type=bool, default=True, help="Success flag")

    args = parser.parse_args()

    # Get or generate correlation ID
    correlation_id = args.correlation_id or get_correlation_id()

    # Parse details
    action_details = parse_json_param(args.details) if args.details else {}

    # Get adapter and publish
    adapter = get_hook_event_adapter()
    success = adapter.publish_agent_action(
        agent_name=args.agent,
        action_type=args.action_type,
        action_name=args.action_name,
        correlation_id=correlation_id,
        action_details=action_details,
        duration_ms=args.duration_ms,
        success=args.success,
    )

    if success:
        print(
            json.dumps(
                {
                    "success": True,
                    "correlation_id": correlation_id,
                    "agent_name": args.agent,
                    "action_type": args.action_type,
                    "published_via": "unified_event_adapter",
                },
                indent=2,
            )
        )
        return 0
    else:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Failed to publish agent action event",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
