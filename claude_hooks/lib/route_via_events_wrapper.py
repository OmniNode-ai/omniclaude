#!/usr/bin/env python3
"""
Event-Based Routing Wrapper for Bash Hooks

Simple wrapper script that provides bash-callable interface to
routing_event_client.py for use in user-prompt-submit hook.

Usage:
    python3 route_via_events_wrapper.py <user_request> <correlation_id>

Output:
    JSON response compatible with existing hook parsing:
    {
        "selected_agent": "agent-name",
        "confidence": 0.85,
        "method": "enhanced_fuzzy_matching",
        "reasoning": "Agent selected because...",
        "latency_ms": 150,
        "domain": "database_optimization",
        "purpose": "Optimize database queries",
        "domain_query": "...",
        "implementation_query": "..."
    }

Exit codes:
    0 - Success (routing completed)
    1 - Error (fallback response provided)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add agents/lib to path for routing_event_client
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent
        / "Volumes/PRO-G40/Code/omniclaude/agents/lib"
    ),
)
sys.path.insert(0, str(Path("/Volumes/PRO-G40/Code/omniclaude/agents/lib")))

try:
    from routing_event_client import route_via_events
except ImportError as e:
    # If routing_event_client not available, provide fallback response
    print(
        json.dumps(
            {
                "selected_agent": "polymorphic-agent",
                "confidence": 0.5,
                "method": "fallback",
                "reasoning": f"Event-based routing unavailable: {e}",
                "latency_ms": 0,
                "domain": "workflow_coordination",
                "purpose": "Intelligent coordinator for development workflows",
            }
        )
    )
    sys.exit(1)

# Suppress verbose logging unless DEBUG env var set
import os

if os.getenv("DEBUG") != "1":
    logging.basicConfig(level=logging.WARNING)
else:
    logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)


async def main():
    """Main routing request handler."""
    # Parse arguments
    if len(sys.argv) < 3:
        logger.error(
            "Usage: route_via_events_wrapper.py <user_request> <correlation_id>"
        )
        print(
            json.dumps(
                {
                    "selected_agent": "polymorphic-agent",
                    "confidence": 0.5,
                    "method": "fallback",
                    "reasoning": "Invalid arguments to routing wrapper",
                    "latency_ms": 0,
                    "domain": "workflow_coordination",
                    "purpose": "Intelligent coordinator for development workflows",
                }
            )
        )
        sys.exit(1)

    user_request = sys.argv[1]
    correlation_id = sys.argv[2]

    # Start timer
    import time

    start_time = time.time()

    try:
        # Call event-based routing with fallback enabled
        recommendations = await route_via_events(
            user_request=user_request,
            context={"correlation_id": correlation_id},
            max_recommendations=5,
            min_confidence=0.6,
            timeout_ms=5000,
            fallback_to_local=True,
        )

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Extract best recommendation
        if recommendations and len(recommendations) > 0:
            best = recommendations[0]

            # Format response compatible with existing hook
            response = {
                "selected_agent": best.get("agent_name", "polymorphic-agent"),
                "confidence": best.get("confidence", {}).get("total", 0.0),
                "method": "enhanced_fuzzy_matching",
                "reasoning": best.get("reason", ""),
                "latency_ms": latency_ms,
                "domain": best.get("domain", "general"),
                "purpose": best.get("purpose", ""),
                # Extract domain/implementation queries if available
                "domain_query": best.get("domain_query", ""),
                "implementation_query": best.get("implementation_query", ""),
            }

            print(json.dumps(response))
            sys.exit(0)
        else:
            # No recommendations, use fallback
            response = {
                "selected_agent": "polymorphic-agent",
                "confidence": 0.5,
                "method": "fallback",
                "reasoning": "No agent recommendations returned",
                "latency_ms": latency_ms,
                "domain": "workflow_coordination",
                "purpose": "Intelligent coordinator for development workflows",
            }
            print(json.dumps(response))
            sys.exit(0)

    except Exception as e:
        # Error occurred, provide fallback response
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Routing failed: {e}", exc_info=True)

        response = {
            "selected_agent": "polymorphic-agent",
            "confidence": 0.5,
            "method": "fallback",
            "reasoning": f"Routing error: {str(e)[:200]}",
            "latency_ms": latency_ms,
            "domain": "workflow_coordination",
            "purpose": "Intelligent coordinator for development workflows",
        }
        print(json.dumps(response))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
