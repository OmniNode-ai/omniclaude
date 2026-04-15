# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pydantic model for agent YAML contract validation (OMN-8914).

Extends OMN-8842's disallowedTools schema to enforce all required fields.
Instantiating this model from a raw agent YAML dict auto-validates on load.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Pattern: agent-[a-z][a-z0-9-]+
_NAME_RE = re.compile(r"^agent-[a-z][a-z0-9-]+$")

EnumModel = Literal["opus", "sonnet", "haiku"]


class ModelAgentContract(BaseModel):
    """Required-field contract for agent YAML definitions.

    All fields are required unless explicitly noted optional.
    Extra fields are forbidden to surface typos and schema drift.
    Frozen to prevent mutation after load.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[
        str, Field(description="Agent identifier, must match agent-[a-z][a-z0-9-]+")
    ]
    description: Annotated[
        str, Field(min_length=20, description="Human-readable description")
    ]
    model: EnumModel
    triggers: list[str]
    disallowedTools: list[str]
    domain: str
    purpose: Annotated[str, Field(min_length=20, description="Why this agent exists")]
    is_orchestrator: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                f"name must match pattern agent-[a-z][a-z0-9-]+, got: {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _validate_triggers_non_empty_for_workers(self) -> ModelAgentContract:
        if not self.is_orchestrator and len(self.triggers) == 0:
            raise ValueError(
                "triggers must be non-empty for non-orchestrator agents "
                "(set is_orchestrator=True to exempt)"
            )
        return self
