#!/usr/bin/env python3
"""
Check Pattern Discovery - Qdrant pattern collections and stats

Usage:
    python3 execute.py [--detailed]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from qdrant_helper import get_all_collections_stats, get_collection_stats
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
                # Get full stats for each collection
                coll_stats = get_collection_stats(name)
                if coll_stats["success"]:
                    collections_detail[name] = {
                        "vectors": coll_stats.get("vectors_count", 0),
                        "status": coll_stats.get("status", "unknown"),
                        "indexed_vectors": coll_stats.get("indexed_vectors_count", 0),
                    }

            result["collections"] = collections_detail
        else:
            result["collections"] = stats.get("collections", {})

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
