# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One classification rule from the friction observer contract."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

from omniclaude.nodes.node_friction_observer_compute.models.enum_friction_severity import (
    EnumFrictionSeverity,
)

# "*", "event.type", or "event.type:field=value" (one qualifier, no regex).
_VALID_PATTERN = re.compile(r"^(\*|[a-z][a-z0-9_.]*(?::[a-z_]+=\S+)?)$")


class ModelFrictionClassificationRule(BaseModel):
    """A classification rule; rules are evaluated first-match-wins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    event_pattern: str
    surface: str
    severity: EnumFrictionSeverity
    description_template: str
    enabled: bool = True
    note: str = ""

    @field_validator("event_pattern")
    @classmethod
    def _check_pattern(cls, value: str) -> str:
        if not _VALID_PATTERN.match(value):
            raise ValueError(
                f"invalid event_pattern {value!r}: expected an exact event type, "
                "one field=value qualifier, or '*'"
            )
        return value

    @field_validator("surface")
    @classmethod
    def _check_surface(cls, value: str) -> str:
        if "/" not in value:
            raise ValueError(f"invalid surface {value!r}: expected 'category/detail'")
        return value


__all__ = ["ModelFrictionClassificationRule"]
