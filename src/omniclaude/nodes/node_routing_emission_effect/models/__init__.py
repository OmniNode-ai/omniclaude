# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the NodeRoutingEmissionEffect node.

Effect node models - routing event emission request/result.
All models are frozen and inert (no logic methods).

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to
    import them, that is the signal to promote to omnibase_core.
"""

from .model_emission_request import ModelEmissionRequest
from .model_emission_result import ModelEmissionResult

__all__ = [
    "ModelEmissionRequest",
    "ModelEmissionResult",
]
