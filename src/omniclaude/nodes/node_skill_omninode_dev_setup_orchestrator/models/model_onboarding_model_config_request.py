# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Operands for one onboarding model configuration operation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelOnboardingModelConfigRequest(BaseModel):
    """Paths belong to the developer's selected workspace and routes file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: Literal["ollama_config", "local_url_endpoint", "place_local_url"]
    path: str
    ram_gb: int = 0
    model: str = ""
    catalogue_path: str = ""
