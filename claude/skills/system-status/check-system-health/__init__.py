"""
Check System Health - Comprehensive system health check

Performs a comprehensive health check across all infrastructure components
including databases, Kafka, Qdrant, Docker services, and pattern discovery.
"""

from .execute import main


__all__ = ["main"]
