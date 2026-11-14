# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The installed customer asset bundle returned to the ONEX setup owner."""

from pydantic import BaseModel, ConfigDict


class ModelOnboardingAssetsRequest(BaseModel):
    """Resolve the installed bundle without acquiring packages or cloning."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelOnboardingAssetsResult(BaseModel):
    """Paths refer to durable files in the installed distribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    marketplace: str
    installer: str
    package_version: str
