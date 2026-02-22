# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Policy envelope for a compiled ticket.

Declares the permission scope and sandbox constraints that apply when
executing the ticket's work.  Enforced at ticket creation time (not deferred).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_ticket_compiler.enums.enum_sandbox_level import (
    EnumSandboxLevel,
)


class ModelPolicyEnvelope(BaseModel):
    """Policy constraints for a compiled ticket.

    Attributes:
        required_validators: Names of validators that must run before the
            ticket can be marked done.
        permission_scope: Set of permissions required to execute this ticket.
        sandbox_level: Degree of sandbox isolation for ticket execution.
        max_execution_minutes: Hard timeout in minutes. 0 = no limit.
        allows_network_access: Whether the ticket may make outbound network calls.
        allows_filesystem_write: Whether the ticket may write to the filesystem.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    required_validators: tuple[str, ...] = Field(
        default=(),
        description="Names of validators that must pass before ticket is done",
    )
    permission_scope: tuple[str, ...] = Field(
        default=(),
        description="Permissions required to execute this ticket",
    )
    sandbox_level: EnumSandboxLevel = Field(
        default=EnumSandboxLevel.STANDARD,
        description="Sandbox isolation level for ticket execution",
    )
    max_execution_minutes: int = Field(
        default=0,
        ge=0,
        description="Hard timeout in minutes (0 = no limit)",
    )
    allows_network_access: bool = Field(
        default=False,
        description="Whether this ticket may make outbound network calls",
    )
    allows_filesystem_write: bool = Field(
        default=True,
        description="Whether this ticket may write to the filesystem",
    )

    @model_validator(mode="after")
    def _enforced_sandbox_restricts_network(self) -> ModelPolicyEnvelope:
        """ENFORCED/ISOLATED sandboxes may not allow network access."""
        if (
            self.sandbox_level
            in (
                EnumSandboxLevel.ENFORCED,
                EnumSandboxLevel.ISOLATED,
            )
            and self.allows_network_access
        ):
            raise ValueError(
                f"Sandbox level {self.sandbox_level.value} does not allow "
                "network access (allows_network_access must be False)"
            )
        return self


__all__ = ["ModelPolicyEnvelope"]
