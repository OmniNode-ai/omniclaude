"""
Debug utilities for Docker service management and monitoring.

This module provides utilities for interacting with Docker services in the
OmniClaude infrastructure, including status checking, log retrieval, and
service listing.

Example Usage:
    ```python
    from agents.lib.debug_utils import (
        get_docker_service_status,
        get_docker_logs,
        list_docker_services
    )

    # Check status of a specific service
    status = get_docker_service_status("archon-intelligence")
    print(f"Service status: {status['state']} ({status['status']})")

    # Get recent logs from a service
    logs = get_docker_logs("archon-intelligence", tail=50)
    print(logs)

    # List all running services with filter
    services = list_docker_services(filter_prefix="archon")
    for service in services:
        print(f"{service['name']}: {service['status']}")
    ```

Author: OmniClaude Framework
Version: 1.0.0
"""

import json
import logging
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class DockerCommandError(Exception):
    """Raised when a Docker command fails."""

    pass


def get_docker_service_status(
    service_name: str, include_health: bool = True
) -> Dict[str, Any]:
    """
    Get the status of a Docker service/container.

    Args:
        service_name: Name of the Docker container/service
        include_health: Whether to include health check information

    Returns:
        Dictionary containing service status information:
        {
            "name": str,
            "state": str,  # "running", "exited", "paused", etc.
            "status": str,  # Full status string
            "health": str,  # "healthy", "unhealthy", "starting", None
            "uptime": str,  # How long container has been running
            "exists": bool  # Whether container exists
        }

    Raises:
        DockerCommandError: If Docker command fails

    Example:
        >>> status = get_docker_service_status("archon-intelligence")
        >>> print(f"Service is {status['state']}")
        Service is running
        >>> if status['health']:
        ...     print(f"Health: {status['health']}")
        Health: healthy
    """
    try:
        # Check if container exists
        check_cmd = [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{service_name}$",
            "--format",
            "{{.Names}}",
        ]
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            raise DockerCommandError(
                f"Failed to check container existence: {result.stderr}"
            )

        exists = bool(result.stdout.strip())

        if not exists:
            return {
                "name": service_name,
                "state": "not_found",
                "status": "Container does not exist",
                "health": None,
                "uptime": None,
                "exists": False,
            }

        # Get container status using docker inspect
        inspect_cmd = ["docker", "inspect", service_name]
        result = subprocess.run(inspect_cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            raise DockerCommandError(f"Failed to inspect container: {result.stderr}")

        inspect_data = json.loads(result.stdout)[0]
        state_data = inspect_data.get("State", {})

        # Extract basic status
        status_info = {
            "name": service_name,
            "state": state_data.get("Status", "unknown"),
            "status": state_data.get("Status", "unknown"),
            "health": None,
            "uptime": None,
            "exists": True,
        }

        # Add health information if available and requested
        if include_health and "Health" in state_data:
            status_info["health"] = state_data["Health"].get("Status", "unknown")

        # Calculate uptime if running
        if state_data.get("Running"):
            started_at = state_data.get("StartedAt")
            if started_at:
                # Docker returns ISO format timestamp
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                uptime = datetime.now(started.tzinfo) - started

                # Format uptime in human-readable format
                days = uptime.days
                hours, remainder = divmod(uptime.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                if days > 0:
                    status_info["uptime"] = f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    status_info["uptime"] = f"{hours}h {minutes}m"
                else:
                    status_info["uptime"] = f"{minutes}m {seconds}s"

        # Add detailed status if container is not running
        if not state_data.get("Running"):
            if state_data.get("ExitCode"):
                status_info["status"] = f"exited (code {state_data['ExitCode']})"

        return status_info

    except subprocess.TimeoutExpired:
        raise DockerCommandError(
            f"Docker command timed out for service: {service_name}"
        )
    except json.JSONDecodeError as e:
        raise DockerCommandError(f"Failed to parse Docker inspect output: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting service status: {e}")
        raise DockerCommandError(f"Unexpected error: {e}")


def get_docker_logs(
    service_name: str,
    tail: Optional[int] = 100,
    since: Optional[str] = None,
    follow: bool = False,
    timestamps: bool = True,
    search_pattern: Optional[str] = None,
) -> str:
    """
    Get logs from a Docker service/container.

    Args:
        service_name: Name of the Docker container/service
        tail: Number of lines to retrieve from end of logs (None = all)
        since: Show logs since timestamp (e.g., "2023-01-01T00:00:00")
               or relative (e.g., "10m", "1h")
        follow: Whether to follow log output (stream mode)
        timestamps: Whether to include timestamps in output
        search_pattern: Optional grep pattern to filter logs

    Returns:
        String containing the logs

    Raises:
        DockerCommandError: If Docker command fails

    Example:
        >>> # Get last 50 lines
        >>> logs = get_docker_logs("archon-intelligence", tail=50)
        >>> print(logs)

        >>> # Get logs from last 10 minutes with error filter
        >>> logs = get_docker_logs(
        ...     "archon-intelligence",
        ...     since="10m",
        ...     search_pattern="ERROR"
        ... )
        >>> print(logs)

        >>> # Get all logs without timestamps
        >>> logs = get_docker_logs(
        ...     "archon-qdrant",
        ...     tail=None,
        ...     timestamps=False
        ... )
    """
    try:
        # Build docker logs command
        cmd = ["docker", "logs"]

        if tail is not None:
            cmd.extend(["--tail", str(tail)])

        if since:
            cmd.extend(["--since", since])

        if follow:
            cmd.append("-f")

        if timestamps:
            cmd.append("-t")

        cmd.append(service_name)

        # Execute docker logs command
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30 if not follow else None
        )

        if result.returncode != 0:
            raise DockerCommandError(f"Failed to get logs: {result.stderr}")

        # Combine stdout and stderr (Docker logs can output to both)
        logs = result.stdout
        if result.stderr:
            logs += "\n" + result.stderr

        # Apply search pattern if specified
        if search_pattern and logs:
            try:
                grep_result = subprocess.run(
                    ["grep", "-i", search_pattern],
                    input=logs,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                # grep returns 1 if no matches found, which is not an error
                if grep_result.returncode == 0:
                    logs = grep_result.stdout
                elif grep_result.returncode == 1:
                    logs = ""  # No matches
                else:
                    logger.warning(f"grep failed with code {grep_result.returncode}")
            except Exception as e:
                logger.warning(f"Failed to apply search pattern: {e}")

        return logs

    except subprocess.TimeoutExpired:
        raise DockerCommandError(
            f"Docker logs command timed out for service: {service_name}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting logs: {e}")
        raise DockerCommandError(f"Unexpected error: {e}")


def list_docker_services(
    filter_prefix: Optional[str] = None,
    include_stopped: bool = False,
    format_output: str = "dict",
) -> List[Dict[str, Any]]:
    """
    List Docker services/containers.

    Args:
        filter_prefix: Optional prefix to filter container names (e.g., "archon")
        include_stopped: Whether to include stopped containers
        format_output: Output format - "dict" (default) or "table"

    Returns:
        List of dictionaries containing service information:
        [
            {
                "name": str,
                "status": str,
                "ports": str,
                "image": str,
                "created": str
            },
            ...
        ]

    Raises:
        DockerCommandError: If Docker command fails

    Example:
        >>> # List all running archon services
        >>> services = list_docker_services(filter_prefix="archon")
        >>> for service in services:
        ...     print(f"{service['name']}: {service['status']}")
        archon-intelligence: Up 2 hours (healthy)
        archon-qdrant: Up 2 hours

        >>> # List all containers including stopped
        >>> all_services = list_docker_services(include_stopped=True)
        >>> print(f"Total containers: {len(all_services)}")

        >>> # Get formatted table output
        >>> services = list_docker_services(
        ...     filter_prefix="omninode",
        ...     format_output="table"
        ... )
    """
    try:
        # Build docker ps command
        cmd = ["docker", "ps"]

        if include_stopped:
            cmd.append("-a")

        # Use custom format for consistent parsing
        format_str = "{{.Names}}||{{.Status}}||{{.Ports}}||{{.Image}}||{{.CreatedAt}}"
        cmd.extend(["--format", format_str])

        if filter_prefix:
            cmd.extend(["--filter", f"name={filter_prefix}"])

        # Execute command
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode != 0:
            raise DockerCommandError(f"Failed to list containers: {result.stderr}")

        # Parse output
        services = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("||")
            if len(parts) >= 5:
                service_info = {
                    "name": parts[0].strip(),
                    "status": parts[1].strip(),
                    "ports": parts[2].strip(),
                    "image": parts[3].strip(),
                    "created": parts[4].strip(),
                }
                services.append(service_info)

        # Sort by name for consistent output
        services.sort(key=lambda x: x["name"])

        return services

    except subprocess.TimeoutExpired:
        raise DockerCommandError("Docker ps command timed out")
    except Exception as e:
        logger.error(f"Unexpected error listing services: {e}")
        raise DockerCommandError(f"Unexpected error: {e}")


def restart_docker_service(
    service_name: str, wait_healthy: bool = True, timeout: int = 60
) -> bool:
    """
    Restart a Docker service/container.

    Args:
        service_name: Name of the Docker container/service
        wait_healthy: Whether to wait for health check to pass
        timeout: Maximum seconds to wait for health check

    Returns:
        True if restart successful (and healthy if wait_healthy=True)

    Raises:
        DockerCommandError: If restart fails

    Example:
        >>> success = restart_docker_service("archon-intelligence")
        >>> print(f"Restart {'successful' if success else 'failed'}")
    """
    try:
        # Execute restart
        cmd = ["docker", "restart", service_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise DockerCommandError(f"Failed to restart service: {result.stderr}")

        # Wait for healthy status if requested
        if wait_healthy:
            import time

            start_time = time.time()

            while time.time() - start_time < timeout:
                status = get_docker_service_status(service_name)

                if status["state"] == "running":
                    # If no health check, just verify running
                    if status["health"] is None:
                        return True
                    # If has health check, wait for healthy
                    elif status["health"] == "healthy":
                        return True

                time.sleep(2)

            # Timeout waiting for healthy
            logger.warning(f"Timeout waiting for {service_name} to become healthy")
            return False

        return True

    except subprocess.TimeoutExpired:
        raise DockerCommandError(
            f"Docker restart command timed out for service: {service_name}"
        )
    except Exception as e:
        logger.error(f"Unexpected error restarting service: {e}")
        raise DockerCommandError(f"Unexpected error: {e}")


def check_docker_network(
    network_name: str = "omninode-bridge-network",
) -> Dict[str, Any]:
    """
    Check Docker network status and connected containers.

    Args:
        network_name: Name of the Docker network to check

    Returns:
        Dictionary containing network information:
        {
            "exists": bool,
            "driver": str,
            "containers": List[str],
            "subnet": str
        }

    Raises:
        DockerCommandError: If Docker command fails

    Example:
        >>> network_info = check_docker_network("omninode-bridge-network")
        >>> print(f"Connected containers: {', '.join(network_info['containers'])}")
    """
    try:
        cmd = ["docker", "network", "inspect", network_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode != 0:
            return {"exists": False, "driver": None, "containers": [], "subnet": None}

        network_data = json.loads(result.stdout)[0]

        # Extract container names
        containers = []
        for container_id, container_info in network_data.get("Containers", {}).items():
            containers.append(container_info.get("Name", container_id[:12]))

        # Extract subnet
        subnet = None
        ipam_config = network_data.get("IPAM", {}).get("Config", [])
        if ipam_config:
            subnet = ipam_config[0].get("Subnet")

        return {
            "exists": True,
            "driver": network_data.get("Driver", "unknown"),
            "containers": sorted(containers),
            "subnet": subnet,
        }

    except subprocess.TimeoutExpired:
        raise DockerCommandError("Docker network inspect command timed out")
    except json.JSONDecodeError as e:
        raise DockerCommandError(f"Failed to parse network inspect output: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking network: {e}")
        raise DockerCommandError(f"Unexpected error: {e}")


# Convenience function for common OmniClaude services
def check_omniclaude_services() -> Dict[str, Dict[str, Any]]:
    """
    Check status of all OmniClaude infrastructure services.

    Returns:
        Dictionary mapping service names to their status information

    Example:
        >>> services = check_omniclaude_services()
        >>> for name, status in services.items():
        ...     health = f" ({status['health']})" if status['health'] else ""
        ...     print(f"{name}: {status['state']}{health}")
        archon-intelligence: running (healthy)
        archon-qdrant: running
        archon-bridge: running (healthy)
    """
    service_names = [
        "archon-intelligence",
        "archon-qdrant",
        "archon-bridge",
        "archon-search",
        "archon-memgraph",
        "archon-kafka-consumer",
        "archon-server",
        "omninode-bridge-redpanda",
    ]

    services_status = {}
    for service in service_names:
        try:
            services_status[service] = get_docker_service_status(service)
        except DockerCommandError as e:
            logger.error(f"Failed to get status for {service}: {e}")
            services_status[service] = {
                "name": service,
                "state": "error",
                "status": str(e),
                "health": None,
                "uptime": None,
                "exists": False,
            }

    return services_status


if __name__ == "__main__":
    """
    Demo/test script showing usage of debug utilities.
    """
    print("=== OmniClaude Docker Debug Utilities Demo ===\n")

    # Check all OmniClaude services
    print("Checking OmniClaude infrastructure services...")
    services = check_omniclaude_services()

    for name, status in services.items():
        health_str = f" ({status['health']})" if status["health"] else ""
        uptime_str = f" - Up {status['uptime']}" if status["uptime"] else ""
        print(f"  {name}: {status['state']}{health_str}{uptime_str}")

    # Get logs from archon-intelligence
    print("\n" + "=" * 60)
    print("Sample logs from archon-intelligence (last 10 lines):")
    print("=" * 60)
    try:
        logs = get_docker_logs("archon-intelligence", tail=10, timestamps=False)
        print(logs)
    except DockerCommandError as e:
        print(f"Failed to get logs: {e}")

    # Check network
    print("\n" + "=" * 60)
    print("Docker network information:")
    print("=" * 60)
    try:
        network_info = check_docker_network("omninode-bridge-network")
        if network_info["exists"]:
            print(f"  Driver: {network_info['driver']}")
            print(f"  Subnet: {network_info['subnet']}")
            print(f"  Connected containers ({len(network_info['containers'])}):")
            for container in network_info["containers"]:
                print(f"    - {container}")
        else:
            print("  Network not found")
    except DockerCommandError as e:
        print(f"Failed to check network: {e}")
