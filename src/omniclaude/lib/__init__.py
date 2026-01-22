"""Shared library code for OmniClaude.

This package provides shared functionality used across hooks, skills, and commands:
- core/: Core functionality (manifest injection, routing, action logging)
- models/: Pydantic models and data structures
- clients/: API clients (Linear, Kafka, PostgreSQL, etc.)
- utils/: Shared utilities (manifest loading, debug, error handling)

Usage:
    from omniclaude.lib.core import ActionLogger, ManifestInjector
    from omniclaude.lib.utils import PatternTracker, get_tracker
"""

from omniclaude.lib import clients, core, models, utils

__all__ = [
    "core",
    "models",
    "clients",
    "utils",
]
