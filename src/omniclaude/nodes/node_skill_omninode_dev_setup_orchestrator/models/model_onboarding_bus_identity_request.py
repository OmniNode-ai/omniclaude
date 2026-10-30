# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One bounded phase of onboarding the developer's local broker identity."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelOnboardingBusIdentityRequest(BaseModel):
    """Use the selected workspace and phase 3's dispatch Python environment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace: str = Field(min_length=1)
    log_path: str = Field(min_length=1)
    mode: Literal["secure", "mint", "resume"]
    retries: int = Field(default=3, ge=1)
    command_timeout_seconds: int = Field(default=1800, ge=1)
    health_timeout_seconds: int = Field(default=900, ge=1)
