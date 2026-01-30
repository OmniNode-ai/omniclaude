# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract-driven registration for omniclaude handlers.

This package provides automatic handler discovery and registration
based on handler contracts defined in contracts/handlers/**/contract.yaml.

Ticket: OMN-1605 - Implement contract-driven handler registration loader
"""

from __future__ import annotations

from omniclaude.contracts.loader import ContractLoader, ContractLoadError
from omniclaude.contracts.registration import (
    HandlerRegistrationError,
    register_all_handlers,
    register_handler_from_contract,
)

__all__ = [
    "ContractLoadError",
    "ContractLoader",
    "HandlerRegistrationError",
    "register_all_handlers",
    "register_handler_from_contract",
]
