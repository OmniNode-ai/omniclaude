# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the quirks rollout orchestrator (OMN-21779)."""

from __future__ import annotations

from collections.abc import Callable

from omniclaude.quirks.controller import NodeValidatorRolloutOrchestratorOrchestrator


def build_rollout_orchestrator(
    *, db_session_factory: Callable[..., object] | None
) -> NodeValidatorRolloutOrchestratorOrchestrator:
    """Build the orchestrator; None keeps the in-memory stage config."""
    return NodeValidatorRolloutOrchestratorOrchestrator(
        db_session_factory=db_session_factory
    )


def build_cli_orchestrator() -> NodeValidatorRolloutOrchestratorOrchestrator:
    """Build the orchestrator for the operator CLI.

    Uses the in-memory store only (no DB session factory) because the CLI is
    intended for development and operator use without a live DB connection.
    For production use, wire up a session factory via the Python API directly.
    """
    return build_rollout_orchestrator(db_session_factory=None)
