# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Agent definition model for routing input.

Represents the structured data from agent YAML configurations
used as input to the routing compute node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentDefinition(BaseModel):
    """Typed representation of an agent YAML definition for routing.

    Captures the subset of agent YAML fields relevant to routing decisions:
    trigger matching, confidence scoring, and capability alignment.

    Attributes:
        name: Agent name (e.g., 'agent-api-architect').
        agent_type: Agent type in snake_case (e.g., 'api_architect').
        description: Human-readable description of the agent's purpose.
        domain_context: Domain classification for context scoring (e.g., 'debugging').
        explicit_triggers: Phrases that trigger this agent directly.
        context_triggers: Context phrases that increase match confidence.
        capabilities: List of capability strings this agent provides.
        definition_path: Filesystem path to the agent's YAML file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Agent name (e.g., 'agent-api-architect')",
    )
    agent_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Agent type in snake_case",
    )
    description: str = Field(
        default="",
        max_length=2000,
        description="Human-readable description of agent purpose",
    )
    domain_context: str = Field(
        default="general",
        max_length=100,
        description="Domain classification for context scoring",
    )
    explicit_triggers: tuple[str, ...] = Field(
        default=(),
        description="Phrases that trigger this agent directly",
    )
    context_triggers: tuple[str, ...] = Field(
        default=(),
        description="Context phrases that increase match confidence",
    )
    capabilities: tuple[str, ...] = Field(
        default=(),
        description="Capability strings this agent provides",
    )
    definition_path: str | None = Field(
        default=None,
        max_length=500,
        description="Filesystem path to agent YAML file",
    )


__all__ = ["ModelAgentDefinition"]
