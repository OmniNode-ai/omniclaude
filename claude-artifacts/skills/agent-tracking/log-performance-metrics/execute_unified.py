#!/usr/bin/env python3
"""
Log Performance Metrics Skill - Unified Event Adapter Version

Publishes agent performance metrics using the unified HookEventAdapter.

Usage:
  /log-performance-metrics --agent AGENT_NAME --metric-name NAME --metric-value 123.45

Options:
  --agent: Agent name (required)
  --metric-name: Metric name (required)
  --metric-value: Metric value (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --metric-type: Metric type (gauge|counter|histogram) (default: gauge)
  --metric-unit: Metric unit (ms|bytes|count|etc) (optional)
  --tags: JSON object with metric tags (optional)
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
        description="Log agent performance metrics via unified event adapter",
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument("--metric-name", required=True, help="Metric name")
    parser.add_argument(
        "--metric-value", required=True, type=float, help="Metric value"
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID")
    parser.add_argument("--metric-type", default="gauge", help="Metric type")
    parser.add_argument("--metric-unit", help="Metric unit")
    parser.add_argument("--tags", help="JSON object with tags")

    args = parser.parse_args()

    # Get or generate correlation ID
    correlation_id = args.correlation_id or get_correlation_id()

    # Parse tags
    tags = parse_json_param(args.tags) if args.tags else {}

    # Get adapter and publish
    adapter = get_hook_event_adapter()
    success = adapter.publish_performance_metrics(
        agent_name=args.agent,
        metric_name=args.metric_name,
        metric_value=args.metric_value,
        correlation_id=correlation_id,
        metric_type=args.metric_type,
        metric_unit=args.metric_unit,
        tags=tags,
    )

    if success:
        print(
            json.dumps(
                {
                    "success": True,
                    "correlation_id": correlation_id,
                    "agent_name": args.agent,
                    "metric_name": args.metric_name,
                    "metric_value": args.metric_value,
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
                    "error": "Failed to publish performance metrics event",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
