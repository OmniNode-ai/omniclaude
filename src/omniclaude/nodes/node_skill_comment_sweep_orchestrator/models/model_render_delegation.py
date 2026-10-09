# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Work-side evidence for a comment reply, including attempts with no receipt."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRenderDelegation(BaseModel):
    """Rendering route, recorded independently of whether delegation ran."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    work_unit_id: str = Field(min_length=1)
    outcome: Literal["pending", "delegated", "fallback"]
    onex_binary: str
    searched_venv: str
    reason: str | None = None
    detail: str | None = None
    run_id: UUID | None = None
    delegation_correlation_id: UUID | None = None
    endpoint: str | None = None
    model: str | None = None
    artifact_path: str | None = None

    @model_validator(mode="after")
    def require_evidence(self) -> ModelRenderDelegation:
        if self.outcome == "delegated":
            if not all(
                (self.run_id, self.delegation_correlation_id, self.endpoint, self.model)
            ):
                raise ValueError("delegated rendering requires a receipted route")
            if self.reason is not None:
                raise ValueError("delegated rendering cannot carry a fallback reason")
        elif self.outcome == "fallback" and not self.reason:
            raise ValueError("fallback rendering requires a reason")
        elif self.outcome == "pending" and any(
            (self.run_id, self.endpoint, self.model)
        ):
            raise ValueError("pending rendering cannot claim a delegation receipt")
        return self
