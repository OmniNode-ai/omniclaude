# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Pydantic models for the Linear relay service.

LinearWebhookPayload: inbound from Linear webhook POST.
LinearEpicClosedCommand: outbound to Kafka topic
    ``onex.cmd.omniclaude.feature-dashboard.v1``.

See OMN-3502 for specification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class LinearWebhookPayload(BaseModel):
    """Payload sent by Linear to the webhook endpoint.

    Linear includes additional fields; we capture only what the relay
    needs. Extra fields are allowed but not validated.
    """

    action: str = Field(..., description="Webhook action, e.g. 'create', 'update'")
    type: str = Field(..., description="Entity type, e.g. 'Project', 'Initiative'")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Entity data. Contains 'state' for project/initiative payloads.",
    )
    organizationId: str = Field(  # noqa: N815 — matches Linear field name
        ...,
        description="Linear organization ID",
    )
    webhookId: str = Field(  # noqa: N815 — matches Linear field name
        ...,
        description="Unique webhook delivery ID (used for deduplication)",
    )
    webhookTimestamp: int = Field(  # noqa: N815 — matches Linear field name
        ...,
        description="Unix timestamp (ms) of the webhook delivery",
    )

    model_config = {"extra": "allow"}


class LinearEpicClosedCommand(BaseModel):
    """Command published to Kafka when a Linear epic is closed.

    Published to ``onex.cmd.omniclaude.feature-dashboard.v1``.
    Triggers the feature-dashboard skill in ``--mode=ticketize``.
    """

    # Envelope fields
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for this command type",
    )
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique message identifier",
    )
    emitted_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of emission",
    )

    # Command identity
    command_id: str = Field(
        ...,
        description=(
            "Idempotency key: sha256('{org_id}:{epic_id}:closed').hexdigest()[:16]"
        ),
    )

    # Source context
    org_id: str = Field(..., description="Linear organization ID")
    epic_id: str = Field(..., description="Linear epic (project/initiative) ID")

    # Feature-dashboard skill arguments
    args: dict[str, str] = Field(
        default_factory=lambda: {
            "mode": "ticketize",
            "output_dir": "docs/feature-dashboard",
            "team": "OmniNode",
        },
        description="Arguments forwarded to the feature-dashboard skill",
    )
