# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A skill-completed event as the friction observer reads it."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ModelFrictionSkillCompletedSignal(BaseModel):
    """The fields of a skill-completed event the observer classifies on.

    Other fields of the published event are ignored, so the producer's schema
    can grow without breaking the observer.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    skill_name: str
    status: str
    correlation_id: UUID
    emitted_at: datetime
    session_id: str | None = None
    error: str | None = None
    error_type: str | None = None
    blocked_reason: str | None = None


__all__ = ["ModelFrictionSkillCompletedSignal"]
