# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Skill node: omninode_dev_setup orchestrator."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.node import (
        NodeSkillOmninodeDevSetupOrchestrator,
    )

__all__ = ["NodeSkillOmninodeDevSetupOrchestrator"]


def __getattr__(name: str) -> object:
    # The shell starts a new Python process for each model-file operation.
    # Those handlers need Pydantic and YAML, not the full ONEX orchestrator.
    if name == "NodeSkillOmninodeDevSetupOrchestrator":
        from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.node import (
            NodeSkillOmninodeDevSetupOrchestrator,
        )

        globals()[name] = NodeSkillOmninodeDevSetupOrchestrator
        return NodeSkillOmninodeDevSetupOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
