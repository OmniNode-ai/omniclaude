# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field

from omniclaude.nodes.node_delegation_orchestrator.enums.enum_cli_recipient import (
    EnumCliRecipient,
)


class ModelCrossCLIInvocationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    correlation_id: str = Field(..., description="Tracing correlation ID")
    recipient: EnumCliRecipient = Field(...)
    stdout: str = Field(default="", description="Captured stdout")
    stderr: str = Field(default="", description="Captured stderr")
    exit_code: int = Field(..., description="Process exit code; 0 = success")
    files_modified: list[str] = Field(default_factory=list)
    runtime_seconds: float = Field(default=0.0, ge=0.0)
    working_directory: str | None = Field(default=None)
    error_detail: str = Field(default="")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success(self) -> bool:
        return self.exit_code == 0 and bool(self.stdout.strip())
