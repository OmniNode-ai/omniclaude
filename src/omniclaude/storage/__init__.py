"""Storage adapters for session snapshots.

This module provides storage adapters for persisting aggregated session data
to various backends (PostgreSQL, file system, etc.).
"""

from __future__ import annotations

from .config import ConfigSessionStorage
from .session_snapshot_store import SessionSnapshotStore

__all__ = ["ConfigSessionStorage", "SessionSnapshotStore"]
