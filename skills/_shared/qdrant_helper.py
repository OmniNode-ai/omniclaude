#!/usr/bin/env python3
"""
Qdrant Helper - Shared utilities for Qdrant operations

Provides functions for:
- Qdrant connectivity checking
- Collection listing and stats
- Vector count monitoring
- Search performance checking

Usage:
    from qdrant_helper import check_qdrant_connection, list_collections, get_collection_stats

Created: 2025-11-12
"""

import json

# Add path for config module (type-safe Pydantic Settings)
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config import settings


def get_timeout_seconds() -> float:
    """
    Get timeout value in seconds from type-safe configuration.

    Returns timeout from Pydantic Settings (default: 5 seconds).
    Configurable via REQUEST_TIMEOUT_MS environment variable.

    Returns:
        Timeout in seconds (float)

    Note:
        Timeout strategy: All helper subprocess/network calls use the same
        timeout to prevent infinite hangs. Default is 5 seconds, configurable
        via .env file (REQUEST_TIMEOUT_MS=5000). Valid range: 100-60000ms.
    """
    return settings.request_timeout_ms / 1000.0


def get_qdrant_url() -> str:
    """
    Get Qdrant URL from type-safe configuration.

    Uses Pydantic Settings framework for validated configuration.

    Returns:
        Qdrant URL (e.g., "http://localhost:6333")

    Note:
        Configuration is loaded from .env file and validated on import.
        Default values: QDRANT_HOST=localhost, QDRANT_PORT=6333
    """
    return f"http://{settings.qdrant_host}:{settings.qdrant_port}"


def check_qdrant_connection() -> Dict[str, Any]:
    """
    Check if Qdrant is reachable and responsive.

    Returns:
        Dictionary with connection status
    """
    qdrant_url = get_qdrant_url()

    try:
        req = urllib.request.Request(f"{qdrant_url}/", method="GET")  # noqa: S310
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=get_timeout_seconds()
        ) as response:
            if response.status == 200:
                return {
                    "status": "connected",
                    "url": qdrant_url,
                    "reachable": True,
                    "error": None,
                }
            else:
                return {
                    "status": "error",
                    "url": qdrant_url,
                    "reachable": False,
                    "error": f"HTTP {response.status}",
                }
    except urllib.error.URLError as e:
        return {
            "status": "unreachable",
            "url": qdrant_url,
            "reachable": False,
            "error": str(e.reason),
        }
    except Exception as e:
        return {
            "status": "error",
            "url": qdrant_url,
            "reachable": False,
            "error": str(e),
        }


def list_collections() -> Dict[str, Any]:
    """
    List all Qdrant collections.

    Returns:
        Dictionary with collection list
    """
    qdrant_url = get_qdrant_url()

    try:
        req = urllib.request.Request(  # noqa: S310
            f"{qdrant_url}/collections", method="GET"
        )
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=get_timeout_seconds()
        ) as response:
            if response.status != 200:
                return {
                    "success": False,
                    "collections": [],
                    "count": 0,
                    "error": f"HTTP {response.status}",
                }

            data = json.loads(response.read().decode())
            collections = data.get("result", {}).get("collections", [])

            collection_names = [c.get("name") for c in collections]

            return {
                "success": True,
                "collections": collection_names,
                "count": len(collection_names),
                "error": None,
            }
    except Exception as e:
        return {"success": False, "collections": [], "count": 0, "error": str(e)}


def get_collection_stats(collection_name: str) -> Dict[str, Any]:
    """
    Get statistics for a specific collection.

    Args:
        collection_name: Name of the collection

    Returns:
        Dictionary with collection statistics
    """
    qdrant_url = get_qdrant_url()

    try:
        req = urllib.request.Request(  # noqa: S310
            f"{qdrant_url}/collections/{collection_name}", method="GET"
        )
        with urllib.request.urlopen(  # noqa: S310
            req, timeout=get_timeout_seconds()
        ) as response:
            if response.status != 200:
                return {
                    "success": False,
                    "collection": collection_name,
                    "error": f"HTTP {response.status}",
                }

            data = json.loads(response.read().decode())
            result = data.get("result", {})

            return {
                "success": True,
                "collection": collection_name,
                "vectors_count": result.get("points_count", 0),
                "indexed_vectors_count": result.get("indexed_vectors_count", 0),
                "status": result.get("status", "unknown"),
                "optimizer_status": result.get("optimizer_status", {}),
                "error": None,
            }
    except Exception as e:
        return {"success": False, "collection": collection_name, "error": str(e)}


def get_all_collections_stats() -> Dict[str, Any]:
    """
    Get statistics for all collections.

    Returns:
        Dictionary with stats for all collections
    """
    collections_result = list_collections()

    if not collections_result["success"]:
        return collections_result

    collections_stats = {}
    total_vectors = 0

    for collection_name in collections_result["collections"]:
        stats = get_collection_stats(collection_name)
        if stats["success"]:
            collections_stats[collection_name] = {
                "vectors_count": stats["vectors_count"],
                "indexed_vectors_count": stats["indexed_vectors_count"],
                "status": stats["status"],
            }
            total_vectors += stats["vectors_count"]
        else:
            # Include failed collections with error details
            collections_stats[collection_name] = {
                "vectors_count": 0,
                "indexed_vectors_count": 0,
                "status": "error",
                "error": stats.get("error", "Unknown error"),
            }

    return {
        "success": True,
        "collections": collections_stats,
        "collection_count": len(collections_stats),
        "total_vectors": total_vectors,
        "error": None,
    }


def check_collection_exists(collection_name: str) -> bool:
    """
    Check if a collection exists.

    Args:
        collection_name: Name of the collection to check

    Returns:
        True if collection exists, False otherwise
    """
    collections_result = list_collections()
    if not collections_result["success"]:
        return False

    return collection_name in collections_result["collections"]


def get_collection_health(collection_name: str) -> Dict[str, Any]:
    """
    Check health of a collection.

    Args:
        collection_name: Name of the collection

    Returns:
        Dictionary with health status
    """
    stats = get_collection_stats(collection_name)

    if not stats["success"]:
        return {
            "success": False,
            "collection": collection_name,
            "healthy": False,
            "error": stats["error"],
        }

    # Collection is healthy if status is "green" or "yellow" and has vectors
    status = stats.get("status", "unknown").lower()
    vectors_count = stats.get("vectors_count", 0)

    healthy = status in ["green", "yellow"] and vectors_count > 0

    return {
        "success": True,
        "collection": collection_name,
        "healthy": healthy,
        "status": status,
        "vectors_count": vectors_count,
        "error": None,
    }


if __name__ == "__main__":
    # Test qdrant helper functions
    print("Testing Qdrant Helper...")
    print("\n1. Checking Qdrant connection...")
    conn = check_qdrant_connection()
    print(json.dumps(conn, indent=2))

    print("\n2. Listing collections...")
    collections = list_collections()
    print(json.dumps(collections, indent=2))

    print("\n3. Getting all collections stats...")
    all_stats = get_all_collections_stats()
    print(json.dumps(all_stats, indent=2))
