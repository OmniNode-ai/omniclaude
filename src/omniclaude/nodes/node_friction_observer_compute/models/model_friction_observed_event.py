# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The friction-observed event the observer publishes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_friction_observer_compute.models.enum_friction_severity import (
    EnumFrictionSeverity,
)


class ModelFrictionObservedEvent(BaseModel):
    """One classified friction signal.

    ``session_id`` is the partition key of the friction-observed topic; a signal
    that carries no session id uses its correlation id there.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    session_id: str
    correlation_id: UUID
    surface: str
    severity: EnumFrictionSeverity
    rule_id: str
    event_pattern: str
    source: str
    description: str
    emitted_at: datetime


__all__ = ["ModelFrictionObservedEvent"]
