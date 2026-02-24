# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeLocalLlmInferenceEffect - Contract-driven effect node for local LLM inference.

This package provides the NodeLocalLlmInferenceEffect node for local LLM
inference operations with pluggable backends (Ollama, llama.cpp, etc.).

Capability: local_llm.inference

All operations emit ModelSkillResult envelopes as output.

Exported Components:
    Node:
        NodeLocalLlmInferenceEffect - The effect node class (minimal shell)

    Models:
        ModelLocalLlmInferenceRequest - Input model for inference operations

    Protocols:
        ProtocolLocalLlmInference - Interface for inference backends
"""

from .models import ModelLocalLlmInferenceRequest
from .node import NodeLocalLlmInferenceEffect
from .protocols import ProtocolLocalLlmInference

__all__ = [
    # Node
    "NodeLocalLlmInferenceEffect",
    # Models
    "ModelLocalLlmInferenceRequest",
    # Protocols
    "ProtocolLocalLlmInference",
]
