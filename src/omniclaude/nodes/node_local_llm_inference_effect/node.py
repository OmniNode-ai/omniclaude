# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Local LLM Inference Effect - 100% contract-driven.

This module provides the NodeLocalLlmInferenceEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: local_llm.inference

The node exposes local LLM inference:
- infer: Submit a prompt to the local LLM and return the response

All operations emit ModelSkillResult envelopes as output.

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolLocalLlmInference). The actual inference backend (e.g., Ollama, llama.cpp)
implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeLocalLlmInferenceEffect(NodeEffect):
    """Effect node for local LLM inference.

    Capability: local_llm.inference

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    Emits ModelSkillResult envelope on all operations.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the local LLM inference effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeLocalLlmInferenceEffect"]
