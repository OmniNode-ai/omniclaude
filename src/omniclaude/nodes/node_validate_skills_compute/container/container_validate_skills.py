# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds this node's handlers (OMN-21779)."""

from omniclaude.nodes.node_validate_skills_compute.handlers import (
    HandlerSkillContracts,
    HandlerSkillHygiene,
)


def build_skill_hygiene() -> HandlerSkillHygiene:
    """Build the hygiene handler with its constructor defaults."""
    return HandlerSkillHygiene()


def build_skill_contracts() -> HandlerSkillContracts:
    """Build the contracts handler with its constructor defaults."""
    return HandlerSkillContracts()
