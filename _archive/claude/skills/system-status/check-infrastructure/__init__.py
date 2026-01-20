"""
Check Infrastructure - Infrastructure service availability and health

Monitors external infrastructure services including Qdrant, Memgraph,
Kafka, and other platform dependencies.
"""

from .execute import main

__all__ = ["main"]
