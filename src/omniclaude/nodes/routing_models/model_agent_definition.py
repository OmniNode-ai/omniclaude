# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Agent definition model for routing.

Captures the subset of agent YAML configuration relevant to routing
decisions: identity, activation patterns, and capabilities. This is
a read-only snapshot, not the full agent YAML schema.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentDefinition(BaseModel):
    """Agent identity and activation patterns for routing.

    Represents the routing-relevant fields from an agent YAML definition.
    Used as input to the routing compute node via ``ModelRoutingRequest``.

    Attributes:
        name: Internal agent identifier (e.g., ``agent-api-architect``).
        agent_type: Snake_case agent type (e.g., ``api_architect``).
        description: Human-readable description of agent purpose.
        explicit_triggers: Exact trigger phrases for direct matching.
        context_triggers: Contextual phrases for fuzzy matching.
        domain: Agent's primary domain (e.g., ``debugging``, ``testing``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Internal agent identifier (e.g., 'agent-api-architect')",
    )
    agent_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Snake_case agent type (e.g., 'api_architect')",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable description of agent purpose",
    )
    explicit_triggers: tuple[str, ...] = Field(
        default=(),
        description="Exact trigger phrases for direct matching",
    )
    context_triggers: tuple[str, ...] = Field(
        default=(),
        description="Contextual phrases for fuzzy matching",
    )
    domain: str = Field(
        default="general",
        min_length=1,
        max_length=50,
        description="Agent's primary domain (e.g., 'debugging', 'testing')",
    )


__all__ = ["ModelAgentDefinition"]
