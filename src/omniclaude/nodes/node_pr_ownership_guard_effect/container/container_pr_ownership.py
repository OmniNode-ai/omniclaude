# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the PR ownership handler (OMN-21779)."""

from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership import (
    HandlerPrOwnership,
)


def build_pr_ownership(*, defer_claims: bool) -> HandlerPrOwnership:
    """Build the ownership handler; the caller says whether claims are deferred."""
    return HandlerPrOwnership(defer_claims=defer_claims)
