# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Aggregated skill validation results."""

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_validate_skills_compute.enums import (
    EnumSkillViolationSeverity,
)
from omniclaude.nodes.node_validate_skills_compute.models.model_skill_violation import (
    ModelSkillViolation,
)


class ModelSkillValidationReport(BaseModel):
    """Ordered violations and severity summaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    violations: tuple[ModelSkillViolation, ...]

    @property
    def errors(self) -> tuple[ModelSkillViolation, ...]:
        return tuple(
            v for v in self.violations if v.severity == EnumSkillViolationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[ModelSkillViolation, ...]:
        return tuple(
            v
            for v in self.violations
            if v.severity == EnumSkillViolationSeverity.WARNING
        )

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
