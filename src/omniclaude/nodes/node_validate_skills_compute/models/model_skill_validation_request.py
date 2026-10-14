# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Inputs shared by the skill validation handlers."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ModelSkillValidationRequest(BaseModel):
    """A skill tree and its validation mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skills_root: Path
    strict: bool = False
