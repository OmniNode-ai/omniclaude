#!/usr/bin/env python3
"""
Check Infrastructure - Infrastructure component connectivity and health

Usage:
    python3 execute.py [--components kafka,postgres,qdrant] [--detailed]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from kafka_helper import check_kafka_connection, list_topics
    from qdrant_helper import check_qdrant_connection, get_all_collections_stats
    from db_helper import execute_query
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def check_kafka(detailed: bool = False):
    """Check Kafka infrastructure."""
    conn = check_kafka_connection()
    topics = list_topics() if detailed else {"count": 0}

    return {
        "status": conn.get("status"),
        "broker": conn.get("broker"),
        "reachable": conn.get("reachable"),
        "topics": topics.get("count") if detailed else None,
        "error": conn.get("error")
    }


def check_postgres(detailed: bool = False):
    """Check PostgreSQL infrastructure."""
    try:
        # Check table count
        result = execute_query(
            "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'public'"
        )

        if result["success"] and result["rows"]:
            table_count = result["rows"][0]["count"]

            response = {
                "status": "connected",
                "host": f"{result.get('host', 'unknown')}:{result.get('port', 'unknown')}",
                "database": result.get("database", "unknown"),
                "tables": table_count,
                "error": None
            }

            # Add connection count if detailed
            if detailed:
                conn_result = execute_query(
                    "SELECT count(*) as count FROM pg_stat_activity"
                )
                if conn_result["success"] and conn_result["rows"]:
                    response["connections"] = conn_result["rows"][0]["count"]

            return response
        else:
            return {
                "status": "error",
                "error": result.get("error", "Unknown error")
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def check_qdrant(detailed: bool = False):
    """Check Qdrant infrastructure."""
    conn = check_qdrant_connection()
    stats = get_all_collections_stats() if detailed else {}

    response = {
        "status": conn.get("status"),
        "url": conn.get("url"),
        "reachable": conn.get("reachable"),
        "error": conn.get("error")
    }

    if detailed and stats.get("success"):
        response["collections"] = stats.get("collection_count")
        response["total_vectors"] = stats.get("total_vectors")
        response["collections_detail"] = {
            name: info["vectors_count"]
            for name, info in stats.get("collections", {}).items()
        }

    return response


def main():
    parser = argparse.ArgumentParser(description="Check infrastructure")
    parser.add_argument("--components", help="Comma-separated list of components")
    parser.add_argument("--detailed", action="store_true", help="Include detailed stats")
    args = parser.parse_args()

    # Determine which components to check
    if args.components:
        components = [c.strip() for c in args.components.split(",")]
    else:
        components = ["kafka", "postgres", "qdrant"]

    result = {}

    try:
        if "kafka" in components:
            result["kafka"] = check_kafka(args.detailed)

        if "postgres" in components:
            result["postgres"] = check_postgres(args.detailed)

        if "qdrant" in components:
            result["qdrant"] = check_qdrant(args.detailed)

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
