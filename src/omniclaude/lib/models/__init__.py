# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic models and data structures.

This package contains shared data models:
- Hook event models (UserPromptSubmit, PreToolUse, PostToolUse, Stop)
- Hook response models (HookResult, HookContinue, HookBlock)
- Agent models (AgentManifest, RoutingDecision, etc.)
- Action logging models
- Intelligence context models
"""

from .intelligence_context import (
    DEFAULT_NODE_TYPE_INTELLIGENCE,
    IntelligenceContext,
    NodeTypeIntelligence,
    get_default_intelligence,
)

__all__ = [
    "IntelligenceContext",
    "NodeTypeIntelligence",
    "DEFAULT_NODE_TYPE_INTELLIGENCE",
    "get_default_intelligence",
]
