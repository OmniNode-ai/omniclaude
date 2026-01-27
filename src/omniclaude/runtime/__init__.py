# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Runtime wiring and service registration for omniclaude.

This package provides the manual service wiring for the MVP implementation.
A follow-up ticket will implement contract-driven handler registration where
the loader reads handler contracts and auto-registers handlers.

Exported:
    wire_omniclaude_services: Async function to register handlers with container
"""

from .wiring import wire_omniclaude_services

__all__ = [
    "wire_omniclaude_services",
]
