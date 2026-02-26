# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the NodeAgentInboxEffect node.

Effect node models - inter-agent message envelope and delivery result.
All models are frozen and inert (no logic methods).

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to
    import them, that is the signal to promote to omnibase_core.
"""

from .model_inbox_delivery_result import ModelInboxDeliveryResult
from .model_inbox_message import ModelInboxMessage, ModelMessageTrace

__all__ = [
    "ModelInboxDeliveryResult",
    "ModelInboxMessage",
    "ModelMessageTrace",
]
