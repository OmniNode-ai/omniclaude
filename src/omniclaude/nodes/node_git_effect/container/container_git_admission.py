# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the git admission handler (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
    HandlerGitAdmission,
)

if TYPE_CHECKING:
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission_transport import (
        HandlerGitAdmissionTransport,
    )


def build_git_admission() -> HandlerGitAdmission:
    """Build the admission handler with its constructor defaults."""
    return HandlerGitAdmission()


def build_git_admission_transport() -> HandlerGitAdmissionTransport:
    """Build the contract-bound admission transport at its binding site."""
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission_transport import (
        HandlerGitAdmissionTransport,
    )

    return HandlerGitAdmissionTransport()
