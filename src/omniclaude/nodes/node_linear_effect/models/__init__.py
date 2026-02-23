# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for the NodeLinearEffect node.

This package contains Pydantic models for Linear ticketing operations:

- ModelLinearRequest: Input model for Linear operation requests
- ModelLinearResult: Output model for Linear operation results

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_linear_request import LinearOperation, ModelLinearRequest
from .model_linear_result import LinearResultStatus, ModelLinearResult

__all__ = [
    "LinearOperation",
    "ModelLinearRequest",
    "LinearResultStatus",
    "ModelLinearResult",
]
