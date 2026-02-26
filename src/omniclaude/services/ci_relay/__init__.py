# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""CI Relay service — receives GitHub Actions workflow completion callbacks.

Accepts POST from GH Actions notify-completion step, validates bearer token,
applies rate limiting and idempotency, then publishes to Kafka topic
``onex.evt.omniclaude.github-pr-status.v1``.

See OMN-2826 Phase 2a for specification.
"""

from omniclaude.services.ci_relay.app import create_app
from omniclaude.services.ci_relay.models import (
    CICallbackPayload,
    PRStatusEvent,
)

__all__ = [
    "CICallbackPayload",
    "PRStatusEvent",
    "create_app",
]
