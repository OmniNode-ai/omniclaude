# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Output consumed by the stock Bash onboarding entrypoint."""

from pydantic import BaseModel, ConfigDict


class ModelOnboardingModelConfigResult(BaseModel):
    """One shell-readable result; placement succeeds with empty output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: str = ""
