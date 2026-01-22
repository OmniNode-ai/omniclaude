"""Shared library code for OmniClaude.

This package provides shared functionality used across hooks, skills, and commands:
- core/: Core functionality (manifest injection, routing, action logging)
- models/: Pydantic models and data structures
- clients/: API clients (Linear, Kafka, PostgreSQL, etc.)
- utils/: Shared utilities (manifest loading, debug, error handling)
- errors: ONEX-compliant error handling (EnumCoreErrorCode, OnexError)

Usage:
    from omniclaude.lib.core import ActionLogger, ManifestInjector
    from omniclaude.lib.utils import PatternTracker, get_tracker
    from omniclaude.lib.errors import EnumCoreErrorCode, OnexError
"""

from omniclaude.lib import clients, core, errors, models, utils

__all__ = [
    "core",
    "errors",
    "models",
    "clients",
    "utils",
]
