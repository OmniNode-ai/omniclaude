# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the git admission handler (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
        HandlerGitAdmission,
    )
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission_transport import (
        HandlerGitAdmissionTransport,
    )
    from omniclaude.nodes.node_git_effect.protocols.protocol_git_refusal_advice import (
        ProtocolGitRefusalAdvice,
    )


def build_git_admission() -> HandlerGitAdmission:
    """Build the admission handler with its constructor defaults."""
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
        HandlerGitAdmission,
    )

    return HandlerGitAdmission()


def build_git_admission_transport() -> HandlerGitAdmissionTransport:
    """Build the contract-bound admission transport at its binding site."""
    from omniclaude.nodes.node_git_effect.handlers.handler_git_admission_transport import (
        HandlerGitAdmissionTransport,
    )

    return HandlerGitAdmissionTransport()


def build_git_refusal_advice() -> ProtocolGitRefusalAdvice:
    """Resolve the Git node's refusal renderer through its protocol."""
    from omniclaude.nodes.node_git_effect.handlers.handler_git_refusal_advice import (
        HandlerGitRefusalAdvice,
    )

    return HandlerGitRefusalAdvice()
