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
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config import settings


def validate_qdrant_url(url: str) -> str:
    """
    Validate Qdrant URL to prevent SSRF (Server-Side Request Forgery) attacks.

    Security checks:
    - Requires HTTPS in production environments
    - Validates hostname against whitelist
    - Blocks dangerous ports (SSH, Telnet, RDP, etc.)
    - Prevents access to internal services

    Args:
        url: The Qdrant URL to validate

    Returns:
        The validated URL (unchanged if valid)

    Raises:
        ValueError: If URL fails security validation

    Example:
        >>> validate_qdrant_url("http://localhost:6333")  # OK in dev
        'http://localhost:6333'
        >>> validate_qdrant_url("https://qdrant.internal:6333")  # OK in prod
        'https://qdrant.internal:6333'
        >>> validate_qdrant_url("http://internal-admin:80")  # BLOCKED
        ValueError: Qdrant host not in whitelist: internal-admin

    Note:
        This prevents environment variable compromise from enabling SSRF attacks
        where an attacker could access internal services (databases, admin panels,
        cloud metadata endpoints, etc.) via the Qdrant client.
    """
    parsed = urllib.parse.urlparse(url)

    # Get environment (default to 'development' if not set)
    environment = os.getenv("ENVIRONMENT", "development").lower()

    # Require HTTPS in production
    if environment == "production" and parsed.scheme != "https":
        raise ValueError(
            f"HTTPS required for production Qdrant (got: {parsed.scheme}). "
            f"Set QDRANT_URL to use https:// in production environment."
        )

    # Whitelist allowed hosts (add your production Qdrant hosts here)
    allowed_hosts = [
        "localhost",
        "127.0.0.1",
        "::1",  # IPv6 localhost
        "qdrant.internal",  # Internal DNS name
        "192.168.86.101",  # Archon server IP
        "192.168.86.200",  # OmniNode bridge IP (fallback)
    ]

    # Additional allowed hosts from environment (comma-separated)
    extra_hosts = os.getenv("QDRANT_ALLOWED_HOSTS", "")
    if extra_hosts:
        allowed_hosts.extend(h.strip() for h in extra_hosts.split(",") if h.strip())

    if parsed.hostname not in allowed_hosts:
        raise ValueError(
            f"Qdrant host not in whitelist: {parsed.hostname}. "
            f"Allowed hosts: {', '.join(allowed_hosts)}. "
            f"Add to QDRANT_ALLOWED_HOSTS environment variable if needed."
        )

    # Validate port is in valid range (if specified)
    # Note: Port 0 is parsed as None by urllib, so we need explicit checks
    if parsed.port is not None:
        if not (1 <= parsed.port <= 65535):
            raise ValueError(f"Invalid port number: {parsed.port}. Must be 1-65535.")

    # Handle special case: port 0 in URL string (parsed.port becomes None)
    # Check if URL explicitly contains ":0" which is invalid
    if ":0" in url or url.endswith(":0/") or ":0/" in url:
        raise ValueError("Invalid port number: 0. Must be 1-65535.")

    # Block dangerous ports that could be used for SSRF attacks
    dangerous_ports = [
        22,  # SSH
        23,  # Telnet
        25,  # SMTP
        3389,  # RDP
        5432,  # PostgreSQL (prevent DB access via Qdrant)
        6379,  # Redis (prevent cache access)
        27017,  # MongoDB
        3306,  # MySQL
        1521,  # Oracle
        9092,  # Kafka (prevent message bus access)
    ]

    if parsed.port and parsed.port in dangerous_ports:
        raise ValueError(
            f"Dangerous port blocked: {parsed.port}. "
            f"This port is commonly used for sensitive services and should not "
            f"be accessed via Qdrant client."
        )

    return url


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
    Get Qdrant URL from type-safe configuration with SSRF protection.

    Uses Pydantic Settings framework for validated configuration.
    Applies security validation to prevent SSRF attacks.

    Returns:
        Validated Qdrant URL (e.g., "http://localhost:6333" or "https://qdrant.internal:6333")

    Raises:
        ValueError: If URL fails SSRF validation checks

    Note:
        Configuration is loaded from .env file and validated on import.
        Default values: QDRANT_HOST=localhost, QDRANT_PORT=6333, QDRANT_URL=http://localhost:6333

        URL Resolution Priority:
        1. Use QDRANT_URL directly if it contains a protocol (http:// or https://)
        2. Otherwise, construct from QDRANT_HOST + QDRANT_PORT with protocol based on ENVIRONMENT

        Security features:
        - HTTPS enforcement in production (ENVIRONMENT=production)
        - Hostname whitelist validation
        - Dangerous port blocking (SSH, DB, etc.)
        - Connection timeout (5 seconds default)

        To use HTTPS in production:
        Option 1 (Recommended - Explicit):
        1. Set QDRANT_URL=https://your-qdrant-host:6333 in .env
        2. Ensure TLS certificate is valid

        Option 2 (Environment-based):
        1. Set ENVIRONMENT=production in .env
        2. Set QDRANT_HOST=your-qdrant-host
        3. Set QDRANT_PORT=6333
        4. Protocol will auto-select HTTPS

        To allow additional hosts:
        Set QDRANT_ALLOWED_HOSTS=host1.com,host2.com in .env
    """
    # Determine environment first
    environment = os.getenv("ENVIRONMENT", "development").lower()

    # Priority 1: Use settings.qdrant_url if it contains a protocol
    # This allows explicit HTTPS/HTTP configuration via QDRANT_URL env var
    if settings.qdrant_url and (
        str(settings.qdrant_url).startswith("http://")
        or str(settings.qdrant_url).startswith("https://")
    ):
        url = str(settings.qdrant_url)

        # Security check: Ensure protocol matches environment requirements
        # In production, HTTP URLs from .env should be rejected
        if environment == "production" and url.startswith("http://"):
            # Fall through to Priority 2 to construct HTTPS URL
            pass
        else:
            # Use the provided URL directly (Pydantic already validated it as HttpUrl)
            # Validate URL for SSRF protection
            return validate_qdrant_url(url)

    # Priority 2: Construct URL from host+port with environment-based protocol
    # Use HTTPS in production, HTTP in development
    protocol = "https" if environment == "production" else "http"

    # Construct URL from settings
    url = f"{protocol}://{settings.qdrant_host}:{settings.qdrant_port}"

    # Validate URL for SSRF protection
    return validate_qdrant_url(url)


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
        # URL-encode collection name to prevent URL injection attacks
        encoded_collection = urllib.parse.quote(collection_name, safe="")
        req = urllib.request.Request(  # noqa: S310
            f"{qdrant_url}/collections/{encoded_collection}", method="GET"
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
