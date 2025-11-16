#!/usr/bin/env python3
"""
Check Kafka Topics - Topic health and consumer status

Usage:
    python3 execute.py [--topics topic1,topic2] [--include-partitions]

Wildcard Behavior:
    - Patterns with '*' match against all topics (e.g., 'test-*')
    - Unmatched wildcards return {"exists": False, "matched": 0}
    - Stats failures include "error" field for diagnostics

Created: 2025-11-12
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from kafka_helper import check_kafka_connection, get_topic_stats, list_topics
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check Kafka topics")
    parser.add_argument("--topics", help="Comma-separated list of topics")
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
                        "broker": conn.get("broker"),
                        "status": "unreachable",
                        "error": conn.get("error"),
                    }
                )
            )
            return 1

        result = {"broker": conn.get("broker"), "status": "healthy"}

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
            topics_detail = {}

            for topic_pattern in topics_list:
                # Check if pattern contains wildcard
                if "*" in topic_pattern:
                    # Match pattern against all topics
                    matched = [
                        t
                        for t in all_topics["topics"]
                        if fnmatch.fnmatch(t, topic_pattern)
                    ]

                    if not matched:
                        # Unmatched wildcard - report as not existing
                        topics_detail[topic_pattern] = {"exists": False, "matched": 0}
                    else:
                        # Process matched topics
                        for topic in matched:
                            topic_info = {"exists": True}

                            if args.include_partitions:
                                stats = get_topic_stats(topic)
                                if stats["success"]:
                                    topic_info["partitions"] = stats.get("partitions")
                                else:
                                    # Stats query failed - include error
                                    topic_info["error"] = (
                                        f"Stats query failed: {stats.get('error', 'unknown error')}"
                                    )

                            topics_detail[topic] = topic_info
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
                        else:
                            # Stats query failed - include error
                            topics_detail[topic_pattern][
                                "error"
                            ] = f"Stats query failed: {stats.get('error', 'unknown error')}"

            result["topics"] = topics_detail

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
