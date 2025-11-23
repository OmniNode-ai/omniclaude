#!/usr/bin/env python3
"""
Skill: check-kafka-topics
Purpose: Check Kafka topic health and configuration

Description:
    Verifies Kafka broker connectivity and retrieves topic information
    including existence checks, partition details, and topic counts.
    Supports wildcard topic matching and selective topic checking.

Usage:
    python3 execute.py [--topics TOPICS] [--include-partitions]

    Options:
        --topics TOPICS          Comma-separated list of topics or patterns
                                Supports wildcards (e.g., agent.*, *.v1)
                                Default: all topics (count only)
        --include-partitions    Include partition details for each topic

Output:
    JSON object with the following structure:
    {
        "broker": "192.168.86.200:29092",
        "status": "healthy",
        "total_topics": 15,
        "topics": {
            "agent.routing.requested.v1": {
                "exists": true,
                "partitions": 3
            },
            "agent.routing.completed.v1": {
                "exists": true,
                "partitions": 3
            }
        }
    }

    With --include-partitions flag:
    {
        "broker": "192.168.86.200:29092",
        "status": "healthy",
        "total_topics": 15,
        "topics": {
            "agent.routing.requested.v1": {
                "exists": true,
                "partitions": {
                    "count": 3,
                    "details": [
                        {"partition": 0, "leader": 1, "replicas": [1]},
                        {"partition": 1, "leader": 1, "replicas": [1]},
                        {"partition": 2, "leader": 1, "replicas": [1]}
                    ]
                }
            }
        }
    }

Exit Codes:
    0: Success - Kafka broker reachable and topics retrieved
    1: Error - Kafka broker unreachable or topic query failed

Examples:
    # Check Kafka connection and topic count
    python3 execute.py

    # Check specific topics
    python3 execute.py --topics agent.routing.requested.v1,agent.routing.completed.v1

    # Check all agent topics with partitions
    python3 execute.py --topics "agent.*" --include-partitions

    # Check intelligence topics with partition details
    python3 execute.py --topics "*.intelligence.*" --include-partitions

Created: 2025-11-12
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# Security: Maximum length for topic patterns to prevent DoS via extremely long patterns
MAX_TOPIC_PATTERN_LENGTH = 256

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from kafka_helper import check_kafka_connection, get_topic_stats, list_topics
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check Kafka topics")
    parser.add_argument(
        "--topics",
        help=f"Comma-separated list of topics (max {MAX_TOPIC_PATTERN_LENGTH} chars per pattern)",
    )
    parser.add_argument(
        "--include-partitions", action="store_true", help="Include partition details"
    )
    args = parser.parse_args()

    try:
        # Check connection
        conn = check_kafka_connection()

        if not conn["reachable"]:
            print(
                format_json(
                    {
                        "success": False,
                        "broker": conn.get("broker"),
                        "status": "unreachable",
                        "error": conn.get("error"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            return 1

        result = {
            "success": True,
            "broker": conn.get("broker"),
            "status": "healthy",
        }

        # List all topics
        all_topics = list_topics()

        if not all_topics["success"]:
            result["status"] = "error"
            result["error"] = all_topics.get("error")
            print(format_json(result))
            return 1

        result["total_topics"] = all_topics["count"]

        # Check specific topics if requested
        if args.topics:
            topics_list = [t.strip() for t in args.topics.split(",")]

            # Validate topic pattern lengths to prevent DoS
            for pattern in topics_list:
                if len(pattern) > MAX_TOPIC_PATTERN_LENGTH:
                    result["success"] = False
                    result["status"] = "error"
                    result["error"] = (
                        f"Topic pattern exceeds maximum length of {MAX_TOPIC_PATTERN_LENGTH} characters: "
                        f"'{pattern[:50]}...' ({len(pattern)} chars)"
                    )
                    print(format_json(result))
                    return 1

            topics_detail = {}

            for topic_pattern in topics_list:
                # Check if pattern contains wildcard
                if "*" in topic_pattern:
                    # Match pattern against all topics
                    import fnmatch

                    matched = [
                        t
                        for t in all_topics["topics"]
                        if fnmatch.fnmatch(t, topic_pattern)
                    ]
                    for topic in matched:
                        stats = (
                            get_topic_stats(topic)
                            if args.include_partitions
                            else {"success": True}
                        )
                        if stats["success"]:
                            topics_detail[topic] = {
                                "exists": True,
                                "partitions": (
                                    stats.get("partitions")
                                    if args.include_partitions
                                    else None
                                ),
                            }
                else:
                    # Check specific topic
                    exists = topic_pattern in all_topics["topics"]
                    topics_detail[topic_pattern] = {"exists": exists}

                    if exists and args.include_partitions:
                        stats = get_topic_stats(topic_pattern)
                        if stats["success"]:
                            topics_detail[topic_pattern]["partitions"] = stats.get(
                                "partitions"
                            )

            result["topics"] = topics_detail

        # Add timestamp to response
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        print(format_json(result))
        return 0

    except Exception as e:
        print(
            format_json(
                {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
