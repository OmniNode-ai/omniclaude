#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Publish Intelligence Request - Request intelligence from RAG system

Publishes intelligence requests to the event bus and optionally
writes results to a file.

Usage:
    python3 publish_intelligence_request.py \
        --query-type domain \
        --query "API design patterns" \
        --correlation-id UUID \
        --agent-name agent-api \
        --output-file /tmp/intelligence.json
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def publish_intelligence_request(
    query_type: str,
    query: str,
    correlation_id: str,
    agent_name: str,
    agent_domain: str = "general",
    output_file: str | None = None,
    match_count: int = 5,
    timeout_ms: int = 2000,
) -> dict[str, Any] | None:
    """
    Publish intelligence request to event bus.

    Args:
        query_type: Type of query (domain, implementation, etc.)
        query: Search query string
        correlation_id: Correlation ID for tracking
        agent_name: Requesting agent name
        agent_domain: Agent domain
        output_file: Optional file to write results
        match_count: Number of results to request
        timeout_ms: Timeout in milliseconds

    Returns:
        Intelligence response or None
    """
    start_time = time.time()

    try:
        from hook_event_adapter import get_hook_event_adapter

        adapter = get_hook_event_adapter()

        # Create intelligence request
        request = {
            "query_type": query_type,
            "query": query,
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "match_count": match_count,
            "timeout_ms": timeout_ms,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Publish request (non-blocking)
        if hasattr(adapter, "publish_intelligence_request"):
            adapter.publish_intelligence_request(
                query_type=query_type,
                query=query,
                correlation_id=correlation_id,
                agent_name=agent_name,
            )
            logger.info(f"Intelligence request published: {query_type}")

        # For now, return placeholder response
        # Full implementation would wait for Kafka response
        response = {
            "query_type": query_type,
            "query": query,
            "results": [],
            "result_count": 0,
            "latency_ms": int((time.time() - start_time) * 1000),
            "status": "pending",  # Results will be available async
            "correlation_id": correlation_id,
        }

        # Write to output file if specified
        if output_file:
            try:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(response, indent=2))
                logger.info(f"Intelligence request written to {output_file}")
            except Exception as e:
                logger.warning(f"Failed to write output file: {e}")

        return response

    except ImportError:
        logger.warning("Hook event adapter not available")
        return None
    except Exception as e:
        logger.error(f"Failed to publish intelligence request: {e}")
        return None


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Publish intelligence request")
    parser.add_argument(
        "--query-type",
        required=True,
        help="Type of query (domain, implementation)",
    )
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--correlation-id", required=True, help="Correlation ID")
    parser.add_argument("--agent-name", required=True, help="Agent name")
    parser.add_argument("--agent-domain", default="general", help="Agent domain")
    parser.add_argument("--output-file", help="Output file path")
    parser.add_argument("--match-count", type=int, default=5, help="Number of matches")
    parser.add_argument("--timeout-ms", type=int, default=2000, help="Timeout in ms")

    args = parser.parse_args()

    result = publish_intelligence_request(
        query_type=args.query_type,
        query=args.query,
        correlation_id=args.correlation_id,
        agent_name=args.agent_name,
        agent_domain=args.agent_domain,
        output_file=args.output_file,
        match_count=args.match_count,
        timeout_ms=args.timeout_ms,
    )

    if result:
        print(json.dumps(result, indent=2))
    else:
        print("Failed to publish intelligence request", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
