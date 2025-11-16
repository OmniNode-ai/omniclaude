#!/usr/bin/env python3
"""
Docker Helper - Shared utilities for Docker operations

Provides functions for:
- Container status checking
- Health check status
- Resource usage monitoring
- Log retrieval and error detection

Usage:
    from docker_helper import list_containers, get_container_status, check_container_health

Created: 2025-11-12
"""

import json
import os
import re
import subprocess

# Import type-safe configuration (Phase 2 - Pydantic Settings migration)
import sys
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


def list_containers(name_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    List all Docker containers, optionally filtered by name.

    Args:
        name_filter: Optional filter for container names (e.g., "archon-", "omninode-")

    Returns:
        Dictionary with container list
    """
    try:
        cmd = ["docker", "ps", "-a", "--format", "{{json .}}"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=get_timeout_seconds()
        )

        if result.returncode != 0:
            return {
                "success": False,
                "containers": [],
                "count": 0,
                "error": result.stderr.strip(),
            }

        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                container = json.loads(line)
                # Apply name filter if specified
                if name_filter is None or name_filter in container.get("Names", ""):
                    containers.append(
                        {
                            "name": container.get("Names", ""),
                            "status": container.get("Status", ""),
                            "state": container.get("State", ""),
                            "image": container.get("Image", ""),
                            "ports": container.get("Ports", ""),
                            "id": container.get("ID", ""),
                        }
                    )
            except json.JSONDecodeError:
                continue

        return {
            "success": True,
            "containers": containers,
            "count": len(containers),
            "error": None,
        }
    except Exception as e:
        return {"success": False, "containers": [], "count": 0, "error": str(e)}


def get_container_status(container_name: str) -> Dict[str, Any]:
    """
    Get detailed status for a specific container.

    Args:
        container_name: Name of the container

    Returns:
        Dictionary with container status details
    """
    try:
        # Get container inspect data
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "container": container_name,
                "status": "not_found",
                "error": "Container not found",
            }

        inspect_data = json.loads(result.stdout)[0]
        state = inspect_data.get("State", {})
        config = inspect_data.get("Config", {})

        # Get health status if available
        health_status = "unknown"
        if "Health" in state:
            health_status = state["Health"].get("Status", "unknown")

        # Calculate uptime
        started_at = state.get("StartedAt", "")

        return {
            "success": True,
            "container": container_name,
            "status": state.get("Status", "unknown"),
            "running": state.get("Running", False),
            "health": health_status,
            "started_at": started_at,
            "restart_count": state.get("RestartCount", 0),
            "image": config.get("Image", ""),
            "error": None,
        }
    except Exception as e:
        return {"success": False, "container": container_name, "error": str(e)}


def check_container_health(container_name: str) -> Dict[str, Any]:
    """
    Check health status of a container.

    Args:
        container_name: Name of the container

    Returns:
        Dictionary with health check details
    """
    status = get_container_status(container_name)

    if not status["success"]:
        return status

    return {
        "success": True,
        "container": container_name,
        "healthy": status.get("health") == "healthy",
        "health_status": status.get("health", "unknown"),
        "running": status.get("running", False),
        "error": None,
    }


def get_container_stats(container_name: str) -> Dict[str, Any]:
    """
    Get resource usage stats for a container.

    Args:
        container_name: Name of the container

    Returns:
        Dictionary with CPU and memory usage
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "stats",
                container_name,
                "--no-stream",
                "--format",
                "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "container": container_name,
                "error": result.stderr.strip(),
            }

        # Parse stats output
        output = result.stdout.strip()
        parts = output.split("|")

        if len(parts) != 3:
            return {
                "success": False,
                "container": container_name,
                "error": "Could not parse stats output",
            }

        cpu_percent = parts[0].replace("%", "").strip()
        mem_usage = parts[1].strip()  # e.g., "123MiB / 2GiB"
        mem_percent = parts[2].replace("%", "").strip()

        return {
            "success": True,
            "container": container_name,
            "cpu_percent": float(cpu_percent) if cpu_percent else 0.0,
            "memory_usage": mem_usage,
            "memory_percent": float(mem_percent) if mem_percent else 0.0,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "container": container_name, "error": str(e)}


def get_container_logs(container_name: str, tail: int = 50) -> Dict[str, Any]:
    """
    Get recent logs from a container.

    Args:
        container_name: Name of the container
        tail: Number of lines to retrieve (default: 50)

    Returns:
        Dictionary with logs and error detection
    """
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container_name],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        # Combine stdout and stderr
        logs = result.stdout + result.stderr
        log_lines = logs.strip().split("\n")

        # Detect errors in logs
        error_patterns = [r"error", r"exception", r"failed", r"fatal", r"critical"]

        errors = []
        for line in log_lines:
            line_lower = line.lower()
            for pattern in error_patterns:
                if re.search(pattern, line_lower):
                    errors.append(line)
                    break

        return {
            "success": True,
            "container": container_name,
            "log_lines": log_lines,
            "log_count": len(log_lines),
            "errors": errors,
            "error_count": len(errors),
            "error": None,
        }
    except Exception as e:
        return {"success": False, "container": container_name, "error": str(e)}


def get_service_summary(name_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    Get summary of all services matching filter.

    Args:
        name_filter: Optional filter for service names

    Returns:
        Dictionary with service summary
    """
    containers_result = list_containers(name_filter)

    if not containers_result["success"]:
        return containers_result

    running = 0
    stopped = 0
    unhealthy = 0

    for container in containers_result["containers"]:
        state = container.get("state", "").lower()
        status = container.get("status", "").lower()

        if state == "running":
            running += 1
            if "unhealthy" in status:
                unhealthy += 1
        else:
            stopped += 1

    return {
        "success": True,
        "total": containers_result["count"],
        "running": running,
        "stopped": stopped,
        "unhealthy": unhealthy,
        "healthy": running - unhealthy,
        "error": None,
    }


if __name__ == "__main__":
    # Test docker helper functions
    print("Testing Docker Helper...")
    print("\n1. Listing all containers...")
    containers = list_containers()
    print(json.dumps(containers, indent=2))

    print("\n2. Getting service summary...")
    summary = get_service_summary()
    print(json.dumps(summary, indent=2))

    if containers["success"] and containers["count"] > 0:
        test_container = containers["containers"][0]["name"]
        print(f"\n3. Getting status for container: {test_container}")
        status = get_container_status(test_container)
        print(json.dumps(status, indent=2))
