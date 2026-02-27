# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""STANDALONE fallback inbox for push-based PR notifications.

When the event bus is not available (STANDALONE mode), this module provides
a file-based inbox using ``gh run watch`` background processes.

See OMN-2826 Phase 2d for specification.
"""

from omniclaude.services.standalone_inbox.background_watcher import (
    BackgroundWatcher,
)
from omniclaude.services.standalone_inbox.inbox import (
    StandaloneInbox,
)

__all__ = [
    "BackgroundWatcher",
    "StandaloneInbox",
]
