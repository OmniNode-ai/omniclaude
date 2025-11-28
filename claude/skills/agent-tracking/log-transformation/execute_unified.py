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


# Add agents/lib to path (5 parents from claude/skills/agent-tracking/log-transformation/)
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent.parent / "agents" / "lib")
)
from transformation_event_publisher import publish_transformation_event_sync


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

    # Build context snapshot from input/output/metadata
    context_snapshot = {}
    if input_data:
        context_snapshot["input_data"] = input_data
    if output_data:
        context_snapshot["output_data"] = output_data
    if metadata:
        context_snapshot["metadata"] = metadata

    # Publish transformation event using transformation_event_publisher
    success = publish_transformation_event_sync(
        source_agent=args.agent,
        target_agent=args.agent,  # Same agent for unified logging
        transformation_reason=args.transformation_type,
        correlation_id=correlation_id,
        context_snapshot=context_snapshot if context_snapshot else None,
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
