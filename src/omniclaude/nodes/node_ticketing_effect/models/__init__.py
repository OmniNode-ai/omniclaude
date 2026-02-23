# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for the NodeTicketingEffect node.

This package contains Pydantic models for vendor-agnostic ticketing operations:

- ModelTicketingRequest: Input model for ticketing operation requests
- ModelTicketingResult: Output model for ticketing operation results

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_ticketing_request import ModelTicketingRequest, TicketingOperation
from .model_ticketing_result import ModelTicketingResult, TicketingResultStatus

__all__ = [
    "TicketingOperation",
    "ModelTicketingRequest",
    "TicketingResultStatus",
    "ModelTicketingResult",
]
