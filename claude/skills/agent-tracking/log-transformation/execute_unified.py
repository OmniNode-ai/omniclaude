#!/usr/bin/env python3
"""
Log Transformation Skill - Unified Event Adapter Version

Publishes agent transformations using the unified HookEventAdapter.

Usage:
  /log-transformation --agent AGENT_NAME --transformation-type TYPE

Options:
  --agent: Agent performing transformation (required)
  --transformation-type: Type of transformation (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --input-data: JSON object with input data (optional)
  --output-data: JSON object with output data (optional)
  --metadata: JSON object with transformation metadata (optional)
"""

import argparse
import json
import sys
from pathlib import Path


# Add claude_hooks/lib to path (5 parents from claude/skills/agent-tracking/log-transformation/)
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent.parent / "claude_hooks" / "lib")
)
from hook_event_adapter import get_hook_event_adapter


# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id, parse_json_param


def main():
    parser = argparse.ArgumentParser(
        description="Log agent transformation via unified event adapter",
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument(
        "--transformation-type", required=True, help="Transformation type"
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID")
    parser.add_argument("--input-data", help="JSON object with input data")
    parser.add_argument("--output-data", help="JSON object with output data")
    parser.add_argument("--metadata", help="JSON object with metadata")

    args = parser.parse_args()

    # Get or generate correlation ID
    correlation_id = args.correlation_id or get_correlation_id()

    # Parse JSON parameters
    input_data = parse_json_param(args.input_data) if args.input_data else {}
    output_data = parse_json_param(args.output_data) if args.output_data else {}
    metadata = parse_json_param(args.metadata) if args.metadata else {}

    # Get adapter and publish
    adapter = get_hook_event_adapter()
    success = adapter.publish_transformation(
        agent_name=args.agent,
        transformation_type=args.transformation_type,
        correlation_id=correlation_id,
        input_data=input_data,
        output_data=output_data,
        metadata=metadata,
    )

    if success:
        print(
            json.dumps(
                {
                    "success": True,
                    "correlation_id": correlation_id,
                    "agent_name": args.agent,
                    "transformation_type": args.transformation_type,
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
                    "error": "Failed to publish transformation event",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
