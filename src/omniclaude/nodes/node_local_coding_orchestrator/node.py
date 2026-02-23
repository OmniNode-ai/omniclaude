# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Node Local Coding Orchestrator - 100% contract-driven.

This module provides the NodeLocalCodingOrchestrator class, a minimal shell
that inherits from NodeOrchestrator. All orchestration logic is driven by the
contract.yaml.

Capability: local_coding.orchestration

The orchestrator reacts only to structured results produced by downstream
effect nodes. It has ZERO subprocess calls and ZERO direct API client imports.
All side effects are delegated to the effect nodes:
  - NodeGitEffect: git operations
  - NodeClaudeCodeSessionEffect: Claude Code session management
  - NodeLocalLlmInferenceEffect: local LLM inference
  - NodeLinearEffect: Linear ticket operations
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeLocalCodingOrchestrator(NodeOrchestrator):
    """Orchestrator for local coding workflow coordination.

    Capability: local_coding.orchestration

    INVARIANT: This node must never contain subprocess calls or API client imports.
    All external I/O is delegated to effect nodes.

    All behavior defined in contract.yaml.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the local coding orchestrator node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeLocalCodingOrchestrator"]
