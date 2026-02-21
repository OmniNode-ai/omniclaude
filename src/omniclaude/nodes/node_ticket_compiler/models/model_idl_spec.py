# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""IDL (Interface Definition Language) specification for a compiled ticket.

Machine-readable description of the inputs, outputs, and declared side effects
of the work unit. Enables automated validation of ticket completeness.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelIdlSpec(BaseModel):
    """Machine-readable IDL specification for a work unit ticket.

    Attributes:
        input_schema: JSON Schema string describing required inputs.
        output_schema: JSON Schema string describing expected outputs.
        side_effects: Declared side effects (e.g. "creates file", "sends email").
        idl_version: Version of the IDL spec format.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    input_schema: str = Field(
        default="{}",
        min_length=2,
        description="JSON Schema string for required inputs (at minimum '{}')",
    )
    output_schema: str = Field(
        default="{}",
        min_length=2,
        description="JSON Schema string for expected outputs (at minimum '{}')",
    )
    side_effects: tuple[str, ...] = Field(
        default=(),
        description="Declared side effects of executing this work unit",
    )
    idl_version: str = Field(
        default="1.0",
        min_length=1,
        max_length=32,
        description="Version of the IDL spec format",
    )

    @model_validator(mode="after")
    def _schemas_are_valid_json(self) -> ModelIdlSpec:
        """Both schema fields must be parseable JSON."""
        import json

        for field_name, value in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
        ):
            try:
                json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field_name} is not valid JSON: {exc}") from exc
        return self


__all__ = ["ModelIdlSpec"]
