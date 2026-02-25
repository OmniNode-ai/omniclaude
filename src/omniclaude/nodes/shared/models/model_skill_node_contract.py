# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill node contract models — execution backend schema.

Defines the Pydantic models that represent the structure of a skill node
``contract.yaml``, including the ``execution`` block introduced in OMN-2798.
Used by OMN-2802 (T4) to load and validate all 61 skill node contracts at
startup.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ModelSkillNodeExecution(BaseModel):
    """Execution backend configuration for a skill node.

    Specifies which backend executes the skill and, for ``local_llm`` backends,
    the purpose of the model to select.

    Attributes:
        backend: Execution backend. ``claude_code`` uses the Claude Code
            subprocess runner. ``local_llm`` routes to a local LLM endpoint
            selected by ``model_purpose``.
        model_purpose: Purpose tag used to select the local LLM endpoint.
            Required when ``backend="local_llm"``, must be ``None`` when
            ``backend="claude_code"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["claude_code", "local_llm"] = "claude_code"
    model_purpose: (
        Literal["CODE_ANALYSIS", "REASONING", "ROUTING", "GENERAL"] | None
    ) = None

    @model_validator(mode="after")
    def _validate_purpose(self) -> ModelSkillNodeExecution:
        """Enforce backend/model_purpose consistency.

        Returns:
            The validated instance.

        Raises:
            ValueError: If ``model_purpose`` is missing for ``local_llm``, or
                present for ``claude_code``.
        """
        if self.backend == "local_llm" and self.model_purpose is None:
            raise ValueError("model_purpose required when backend=local_llm")
        if self.backend == "claude_code" and self.model_purpose is not None:
            raise ValueError("model_purpose must be null when backend=claude_code")
        return self


class ModelSkillNodeContract(BaseModel):
    """Structured representation of a skill node ``contract.yaml``.

    Holds the fields consumed by the dispatcher (T4/OMN-2802) at startup.
    Uses ``extra="ignore"`` so that fields not yet covered by this model
    (e.g. ``io_operations``, ``dependencies``) are silently tolerated.

    Attributes:
        name: Node name (e.g. ``"node_skill_local_review_orchestrator"``).
        node_type: ONEX node type string (e.g. ``"ORCHESTRATOR_GENERIC"``).
        execution: Execution backend configuration block.
        event_bus: Raw event bus configuration dict (subscribe/publish topics).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    node_type: str
    execution: ModelSkillNodeExecution = ModelSkillNodeExecution()
    event_bus: dict[str, Any]


__all__ = ["ModelSkillNodeContract", "ModelSkillNodeExecution"]
