# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeGithubPrWatcherEffect -- subscribes to PR status events and routes
to per-agent inboxes via Valkey watch registry.

See OMN-2826 Phase 2b.
"""

from omniclaude.nodes.node_github_pr_watcher_effect.node import (
    NodeGithubPrWatcherEffect,
)

__all__ = ["NodeGithubPrWatcherEffect"]
