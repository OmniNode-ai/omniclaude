# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Backends for the NodeLocalLlmInferenceEffect node.

This package contains pluggable inference backend implementations that
satisfy ProtocolLocalLlmInference.

Exported:
    VllmInferenceBackend: vLLM/OpenAI-compatible backend using httpx.
"""

from .backend_vllm import VllmInferenceBackend

__all__ = [
    "VllmInferenceBackend",
]
