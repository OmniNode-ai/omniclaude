# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Verifiable acceptance criterion for a compiled ticket's test contract.

Each criterion must specify an assertion type and an expected value or
verification command.  Prose-only criteria are rejected at construction time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_ticket_compiler.enums.enum_assertion_type import (
    EnumAssertionType,
)


class ModelAcceptanceCriterion(BaseModel):
    """A single verifiable acceptance criterion.

    Attributes:
        criterion_id: Stable identifier for this criterion.
        description: Human-readable description of what is being verified.
        assertion_type: The mechanism used to verify this criterion.
        expected_value: Expected value or outcome (required unless
            assertion_type is MANUAL_VERIFICATION).
        verification_command: Shell command or test invocation to verify
            the criterion (required for command-based assertion types).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    criterion_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this criterion",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Human-readable description of what is being verified",
    )
    assertion_type: EnumAssertionType = Field(
        ...,
        description="Verification mechanism for this criterion",
    )
    expected_value: str = Field(
        default="",
        max_length=2000,
        description="Expected value or outcome",
    )
    verification_command: str = Field(
        default="",
        max_length=2000,
        description="Shell command or test invocation to verify the criterion",
    )

    @model_validator(mode="after")
    def _prose_only_rejected(self) -> ModelAcceptanceCriterion:
        """Criteria that have no expected value AND no verification command
        are rejected unless the assertion type is MANUAL_VERIFICATION.

        This enforces the 'no prose-only ACs' rule from OMN-2503 R2.
        """
        if self.assertion_type == EnumAssertionType.MANUAL_VERIFICATION:
            return self
        if not self.expected_value and not self.verification_command:
            raise ValueError(
                f"Acceptance criterion {self.criterion_id!r} (type={self.assertion_type.value}) "
                "must have either expected_value or verification_command — "
                "prose-only acceptance criteria are rejected."
            )
        return self


__all__ = ["ModelAcceptanceCriterion"]
