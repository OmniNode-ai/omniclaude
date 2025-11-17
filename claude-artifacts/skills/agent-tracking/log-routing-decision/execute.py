#!/usr/bin/env python3
"""
Log Routing Decision Skill - Track agent routing decisions in PostgreSQL

Logs routing decisions made by the agent workflow coordinator, including
confidence scores, alternatives considered, and routing strategies used.

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

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
)


def log_routing_decision(args):
    """Log a routing decision to the database."""

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
        return handle_db_error(
            ValueError(
                f"Confidence score must be between 0.0 and 1.0, got {confidence}"
            ),
            "log_routing_decision",
        )

    # Prepare SQL
    sql = """
    INSERT INTO agent_routing_decisions (
        user_request,
        selected_agent,
        confidence_score,
        alternatives,
        reasoning,
        routing_strategy,
        context,
        routing_time_ms
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id, created_at
    """

    params = (
        (
            args.user_request
            if hasattr(args, "user_request") and args.user_request
            else ""
        ),
        args.agent,
        confidence,
        json.dumps(alternatives),
        args.reasoning if hasattr(args, "reasoning") and args.reasoning else None,
        args.strategy,
        json.dumps(context),
        int(args.latency_ms),
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            output = {
                "success": True,
                "routing_decision_id": str(row["id"]),
                "correlation_id": correlation_id,
                "selected_agent": args.agent,
                "confidence_score": confidence,
                "routing_strategy": args.strategy,
                "routing_time_ms": int(args.latency_ms),
                "created_at": row["created_at"].isoformat(),
            }
            print(json.dumps(output, indent=2))
            return 0
        else:
            error = {"success": False, "error": "No result returned from database"}
            print(json.dumps(error), file=sys.stderr)
            return 1

    except Exception as e:
        error_info = handle_db_error(e, "log_routing_decision")
        print(json.dumps(error_info), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent routing decision to PostgreSQL",
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

    return log_routing_decision(args)


if __name__ == "__main__":
    sys.exit(main())
