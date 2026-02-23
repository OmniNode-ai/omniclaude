# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for local LLM inference backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_local_llm_inference_effect.models import (
    ModelLocalLlmInferenceRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import ModelSkillResult


@runtime_checkable
class ProtocolLocalLlmInference(Protocol):
    """Runtime-checkable protocol for local LLM inference backends.

    All inference backend implementations must implement this protocol.
    All operations emit ModelSkillResult envelopes.

    Supported backends: Ollama, llama.cpp (handler_key: 'ollama', 'llamacpp')

    Operation mapping (from node contract io_operations):
        - infer operation -> infer()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'ollama', 'llamacpp')."""
        ...

    async def infer(self, request: ModelLocalLlmInferenceRequest) -> ModelSkillResult:
        """Submit a prompt to the local LLM and return a response.

        Args:
            request: Inference request with prompt and optional model/parameters.

        Returns:
            ModelSkillResult with LLM response in output field.
            status=SUCCESS if inference completed successfully.
            status=FAILED if inference failed (error field populated).
        """
        ...


__all__ = ["ProtocolLocalLlmInference"]
