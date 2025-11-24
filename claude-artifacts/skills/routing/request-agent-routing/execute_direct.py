#!/usr/bin/env python3
"""
Request Agent Routing Skill - Direct Router Version

Falls back to direct AgentRouter execution when Kafka service is unavailable.
Uses local Python execution with no event bus dependency.

Usage:
  python3 execute_direct.py --user-request "optimize my database queries" --max-recommendations 3

Options:
  --user-request: User's task description (required)
  --context: JSON object with execution context (optional)
  --max-recommendations: Number of recommendations to return (default: 5)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)

Output: JSON with recommendations or error
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4


# Determine project root (skills are in ~/.claude/skills, not in project)
# Respect explicit environment variable - only fallback if NOT explicitly set
_explicit_omniclaude_path = os.environ.get("OMNICLAUDE_PATH")
if _explicit_omniclaude_path:
    # Environment variable explicitly set - respect it (validation happens below)
    OMNICLAUDE_PATH = Path(_explicit_omniclaude_path)
else:
    # No explicit env var - try default then fallbacks
    OMNICLAUDE_PATH = Path.home() / "Code" / "omniclaude"
    if not OMNICLAUDE_PATH.exists():
        # Fallback to common locations only when env var not set
        for fallback in [
            Path("/Users") / "Shared" / "omniclaude",
            Path("/Volumes/PRO-G40/Code/omniclaude"),
        ]:
            if fallback.exists():
                OMNICLAUDE_PATH = fallback
                break

# Validate OMNICLAUDE_PATH before adding to sys.path
if not OMNICLAUDE_PATH.exists():
    print(
        json.dumps(
            {
                "success": False,
                "error": f"OMNICLAUDE_PATH not found: {OMNICLAUDE_PATH}",
                "hint": "Set OMNICLAUDE_PATH environment variable or ensure omniclaude directory exists in ~/Code/",
            }
        )
    )
    sys.exit(1)

sys.path.insert(0, str(OMNICLAUDE_PATH))
from config import settings


# Add _shared to path for utilities
shared_path = Path(__file__).parent.parent.parent / "_shared"
if not shared_path.exists():
    print(
        json.dumps(
            {
                "success": False,
                "error": f"Shared utilities path not found: {shared_path}",
                "hint": "Ensure skills/_shared directory exists",
            }
        )
    )
    sys.exit(1)

sys.path.insert(0, str(shared_path))
from db_helper import get_correlation_id


# Add agents/lib to path for AgentRouter
agents_lib_path = OMNICLAUDE_PATH / "agents" / "lib"
if not agents_lib_path.exists():
    print(
        json.dumps(
            {
                "success": False,
                "error": f"AgentRouter library path not found: {agents_lib_path}",
                "hint": "Ensure OMNICLAUDE_PATH is set correctly and agents/lib directory exists",
            }
        )
    )
    sys.exit(1)

sys.path.insert(0, str(agents_lib_path))


def request_routing_direct(
    user_request, context=None, max_recommendations=5, correlation_id=None
):
    """
    Request routing via direct AgentRouter (fallback).

    Args:
        user_request: User's task description
        context: Optional execution context dictionary
        max_recommendations: Number of recommendations
        correlation_id: Optional correlation ID

    Returns:
        Dictionary with routing result
    """
    start_time = time.time()

    try:
        # Import AgentRouter (lazy to avoid import errors)
        from agent_router import AgentRouter

        # Initialize router
        router = AgentRouter()

        # Route request
        recommendations = router.route(
            user_request=user_request,
            context=context or {},
            max_recommendations=max_recommendations,
        )

        # Calculate routing time
        routing_time_ms = int((time.time() - start_time) * 1000)

        # Convert recommendations to JSON-serializable format
        recommendations_data = []
        for rec in recommendations:
            recommendations_data.append(
                {
                    "agent_name": rec.agent_name,
                    "agent_title": rec.agent_title,
                    "confidence": {
                        "total": rec.confidence.total,
                        "trigger_score": rec.confidence.trigger_score,
                        "context_score": rec.confidence.context_score,
                        "capability_score": rec.confidence.capability_score,
                        "historical_score": rec.confidence.historical_score,
                        "explanation": rec.confidence.explanation,
                    },
                    "reason": rec.reason,
                    "definition_path": rec.definition_path,
                }
            )

        # Get routing stats
        routing_stats = router.get_routing_stats()

        return {
            "success": True,
            "correlation_id": correlation_id or str(uuid4()),
            "recommendations": recommendations_data,
            "routing_metadata": {
                "routing_time_ms": routing_time_ms,
                "cache_hit": False,  # Direct routing has no persistent cache
                "candidates_evaluated": len(recommendations),
                "routing_strategy": "enhanced_fuzzy_matching",
                "method": "direct",
                "cache_hit_rate": routing_stats.get("cache_hit_rate", 0.0),
            },
        }

    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"Agent registry not found: {e}",
            "correlation_id": correlation_id or str(uuid4()),
            "fallback_attempted": False,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Direct routing failed: {e}",
            "correlation_id": correlation_id or str(uuid4()),
            "fallback_attempted": False,
        }


def main():
    """Main entry point for skill."""
    parser = argparse.ArgumentParser(
        description="Request agent routing via direct AgentRouter (fallback)"
    )
    parser.add_argument("--user-request", required=True, help="User's task description")
    parser.add_argument(
        "--context",
        help="Execution context as JSON (optional)",
        default="{}",
    )
    parser.add_argument(
        "--max-recommendations",
        type=int,
        default=5,
        help="Maximum number of recommendations (default: 5)",
    )
    parser.add_argument(
        "--correlation-id",
        help="Correlation ID for tracking (optional, auto-generated)",
    )

    args = parser.parse_args()

    # Parse context JSON
    try:
        context = json.loads(args.context) if args.context else {}
    except json.JSONDecodeError as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Invalid context JSON: {e}",
                }
            )
        )
        sys.exit(1)

    # Get or generate correlation ID
    correlation_id = args.correlation_id or get_correlation_id()

    # Request routing via direct AgentRouter
    result = request_routing_direct(
        user_request=args.user_request,
        context=context,
        max_recommendations=args.max_recommendations,
        correlation_id=correlation_id,
    )

    # Output result as JSON
    print(json.dumps(result, indent=2))

    # Exit with success/failure code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
