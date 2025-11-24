#!/usr/bin/env python3
"""
Skill: check-pattern-discovery
Purpose: Check Qdrant pattern collections and statistics

Description:
    Retrieves statistics about Qdrant vector collections used for pattern
    discovery including total vector counts, collection counts, and detailed
    per-collection metrics. Used to verify pattern discovery infrastructure
    is healthy and populated with data.

Usage:
    python3 execute.py [--detailed]

    Options:
        --detailed              Include detailed statistics for each collection
                               (vector counts, indexing status, health)

Output:
    JSON object with the following structure:
    {
        "total_patterns": 15689,
        "collection_count": 4,
        "collections": {
            "archon_vectors": 7118,
            "code_generation_patterns": 8571,
            "archon-intelligence": 0,
            "quality_vectors": 0
        }
    }

    With --detailed flag:
    {
        "total_patterns": 15689,
        "collection_count": 4,
        "collections": {
            "archon_vectors": {
                "vectors": 7118,
                "status": "green",
                "indexed_vectors": 7118
            },
            "code_generation_patterns": {
                "vectors": 8571,
                "status": "green",
                "indexed_vectors": 8571
            }
        }
    }

Exit Codes:
    0: Success - pattern collections retrieved successfully
    1: Error - Qdrant connection failed or collection query error

Examples:
    # Check basic collection stats
    python3 execute.py

    # Check detailed collection information
    python3 execute.py --detailed

Created: 2025-11-12
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from qdrant_helper import get_all_collections_stats
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check pattern discovery")
    parser.add_argument(
        "--detailed", action="store_true", help="Include detailed stats"
    )
    args = parser.parse_args()

    try:
        stats = get_all_collections_stats()

        if not stats["success"]:
            print(format_json({"success": False, "error": stats.get("error")}))
            return 1

        result = {
            "total_patterns": stats.get("total_vectors", 0),
            "collection_count": stats.get("collection_count", 0),
        }

        if args.detailed:
            collections_detail = {}
            for name, info in stats.get("collections", {}).items():
                # Reuse stats already fetched by get_all_collections_stats()
                # No redundant API call needed - info already contains full stats
                collections_detail[name] = {
                    "vectors": info.get("vectors_count", 0),
                    "status": info.get("status", "unknown"),
                    "indexed_vectors": info.get("indexed_vectors_count", 0),
                }

            result["collections"] = collections_detail
        else:
            result["collections"] = stats.get("collections", {})

        # Add success and timestamp to response
        result["success"] = True
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
