# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A bounded command outcome that retains the failed target and its remedy."""

from pydantic import BaseModel, ConfigDict


class ModelOnboardingBusIdentityResult(BaseModel):
    """A failed call never reports a minted identity or completes its phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool
    failed_step: str = ""
    returncode: int = 0
    attempts: int = 0
    reason: str = ""
    next_step: str = ""
