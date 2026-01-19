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
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
# Import shared timeout utility to avoid duplication

from .common_utils import get_timeout_seconds


def list_containers(name_filter: str | None = None) -> dict[str, Any]:
    """
    List all Docker containers, optionally filtered by name.

    Args:
        name_filter: Optional filter for container names. Supports:
                    - Simple substring: "archon-" matches any name containing "archon-"
                    - Regex pattern: "archon-|omninode-|omniclaude-" matches any of the prefixes

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
                "return_code": result.returncode,
            }

        # Compile regex if filter contains regex patterns ("|" character)
        filter_regex = None
        if name_filter and "|" in name_filter:
            try:
                filter_regex = re.compile(name_filter)
            except re.error:
                # If regex compilation fails, fall back to substring matching
                pass

        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                container = json.loads(line)
                container_name = container.get("Names", "")

                # Apply name filter if specified
                if name_filter is None:
                    matches = True
                elif filter_regex:
                    # Use regex matching if pattern was compiled
                    matches = filter_regex.search(container_name) is not None
                else:
                    # Fall back to simple substring matching
                    matches = name_filter in container_name

                if matches:
                    containers.append(
                        {
                            "name": container_name,
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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "containers": [],
            "count": 0,
            "error": f"Docker command timed out after {get_timeout_seconds()}s",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "containers": [],
            "count": 0,
            "error": "Docker CLI not found. Ensure Docker is installed.",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError, Exception) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        # Exception: catch-all for unexpected errors (JSON decode, etc.)
        return {
            "success": False,
            "containers": [],
            "count": 0,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def get_container_status(container_name: str) -> dict[str, Any]:
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
                "return_code": result.returncode,
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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "container": container_name,
            "error": f"Docker inspect timed out after {get_timeout_seconds()}s",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "container": container_name,
            "error": "Docker CLI not found. Ensure Docker is installed.",
            "return_code": 1,
        }
    except json.JSONDecodeError as e:
        # JSONDecodeError: Docker returned invalid JSON
        return {
            "success": False,
            "container": container_name,
            "error": f"Invalid JSON from Docker: {str(e)}",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "container": container_name,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def check_container_health(container_name: str) -> dict[str, Any]:
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
        "return_code": 0,
    }


def get_container_stats(container_name: str) -> dict[str, Any]:
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
                "return_code": result.returncode,
            }

        # Parse stats output
        output = result.stdout.strip()
        parts = output.split("|")

        if len(parts) != 3:
            return {
                "success": False,
                "container": container_name,
                "error": "Could not parse stats output",
                "return_code": 0,
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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "container": container_name,
            "error": f"Docker stats timed out after {get_timeout_seconds()}s",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "container": container_name,
            "error": "Docker CLI not found. Ensure Docker is installed.",
            "return_code": 1,
        }
    except ValueError as e:
        # ValueError: float conversion errors from stats parsing
        return {
            "success": False,
            "container": container_name,
            "error": f"Failed to parse stats: {str(e)}",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "container": container_name,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def get_container_logs(container_name: str, tail: int = 50) -> dict[str, Any]:
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

        # Check if Docker command failed
        if result.returncode != 0:
            return {
                "success": False,
                "container": container_name,
                "error": f"Docker logs failed: {result.stderr.strip()}",
                "return_code": result.returncode,
            }

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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "container": container_name,
            "error": f"Docker logs timed out after {get_timeout_seconds()}s",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "container": container_name,
            "error": "Docker CLI not found. Ensure Docker is installed.",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "container": container_name,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def get_service_summary(name_filter: str | None = None) -> dict[str, Any]:
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
        "return_code": 0,
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
