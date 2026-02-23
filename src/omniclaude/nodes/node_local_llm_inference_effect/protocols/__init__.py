# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeLocalLlmInferenceEffect node.

This package defines the protocol interface for local LLM inference backends.

Exported:
    ProtocolLocalLlmInference: Runtime-checkable protocol for inference backends

Operation Mapping (from node contract io_operations):
    - infer operation -> ProtocolLocalLlmInference.infer()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Return ModelSkillResult envelopes for all operations
"""

from .protocol_local_llm_inference import ProtocolLocalLlmInference

__all__ = [
    "ProtocolLocalLlmInference",
]
