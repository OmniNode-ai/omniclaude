# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for the NodeLocalLlmInferenceEffect node.

This package contains Pydantic models for local LLM inference:

- ModelLocalLlmInferenceRequest: Input model for inference requests

Output model is ModelSkillResult from omniclaude.nodes.shared.models.

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_local_llm_inference_request import ModelLocalLlmInferenceRequest

__all__ = [
    "ModelLocalLlmInferenceRequest",
]
