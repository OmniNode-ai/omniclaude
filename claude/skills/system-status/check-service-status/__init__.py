"""
Check Service Status - Docker service health and container status

Monitors Docker container health, service availability, resource usage,
and restart counts for all platform services.
"""

from .execute import main


__all__ = ["main"]
