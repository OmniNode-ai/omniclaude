"""OmniClaude - Claude Code hooks and learning loop integration.

This package provides ONEX-compatible event schemas for Claude Code hooks,
enabling integration with the omnibase ecosystem for learning and intelligence.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("omniclaude")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
