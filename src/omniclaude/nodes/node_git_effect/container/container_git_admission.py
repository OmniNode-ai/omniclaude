# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the git admission handler (OMN-21779)."""

from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
    HandlerGitAdmission,
)


def build_git_admission() -> HandlerGitAdmission:
    """Build the admission handler with its constructor defaults."""
    return HandlerGitAdmission()
