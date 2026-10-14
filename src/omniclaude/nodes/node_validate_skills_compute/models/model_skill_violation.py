# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A single skill validation violation."""

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_validate_skills_compute.enums import (
    EnumSkillViolationSeverity,
)


class ModelSkillViolation(BaseModel):
    """An immutable violation with source-compatible formatting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    check: str
    severity: EnumSkillViolationSeverity
    message: str

    def format_line(self) -> str:
        return f"  {self.severity}: [{self.check}] {self.path}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
        }
