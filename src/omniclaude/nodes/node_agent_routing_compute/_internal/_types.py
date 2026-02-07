# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Shared type definitions for _internal/ routing modules.

TypedDicts that describe the dict-based interfaces between the handler layer
and the pure-Python routing logic.  These replace ``dict[str, Any]`` annotations
with narrow, documented shapes while keeping the modules free of ONEX/Pydantic
imports.

Pure Python - NO ONEX imports.
"""

from __future__ import annotations

from typing import TypedDict

__all__ = [
    "AgentData",
    "AgentRegistry",
    "HistoricalRecord",
    "RoutingContext",
]


class AgentData(TypedDict, total=False):
    """Agent metadata as produced by the handler's ``_build_registry_dict``.

    All keys are optional (``total=False``) because internal callers access
    values via ``.get()`` with safe defaults.

    Keys:
        activation_triggers: Phrases that trigger this agent.
        title: Human-readable agent description.
        capabilities: Capability strings the agent provides.
        domain_context: Domain classification for context scoring.
        definition_path: Filesystem path to the agent YAML file.
    """

    activation_triggers: list[str]
    title: str
    capabilities: list[str]
    domain_context: str
    definition_path: str


class RoutingContext(TypedDict, total=False):
    """Execution context passed to confidence scoring.

    Keys:
        domain: Current domain classification (e.g., 'debugging', 'frontend').
    """

    domain: str


class HistoricalRecord(TypedDict, total=False):
    """Historical success data for a single agent.

    Keys:
        overall: Aggregate success rate (0.0-1.0).
    """

    overall: float


class AgentRegistry(TypedDict):
    """Registry structure expected by ``TriggerMatcher``.

    Keys:
        agents: Mapping of agent name to agent metadata.
    """

    agents: dict[str, AgentData]
