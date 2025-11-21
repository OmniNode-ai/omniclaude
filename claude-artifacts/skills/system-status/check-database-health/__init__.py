"""
Check Database Health - PostgreSQL database health and connectivity

Monitors PostgreSQL connection health, query performance, table statistics,
and database metrics for the OmniNode platform.
"""

from .execute import main


__all__ = ["main"]
