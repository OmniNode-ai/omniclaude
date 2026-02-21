# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Directed edge in the Plan DAG — represents a dependency between work units."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelDagEdge(BaseModel):
    """A directed dependency edge between two work units in the Plan DAG.

    Semantics: ``from_unit_id`` must be completed before ``to_unit_id``
    can begin.

    Attributes:
        from_unit_id: ID of the prerequisite work unit.
        to_unit_id: ID of the dependent work unit.
        label: Optional human-readable label describing the dependency.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    from_unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the prerequisite work unit",
    )
    to_unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the dependent work unit",
    )
    label: str = Field(
        default="",
        max_length=256,
        description="Optional human-readable label for the dependency",
    )

    @model_validator(mode="after")
    def _no_self_loops(self) -> ModelDagEdge:
        """Self-loops (from == to) are immediately rejected."""
        if self.from_unit_id == self.to_unit_id:
            raise ValueError(
                f"DAG self-loop detected: from_unit_id == to_unit_id == {self.from_unit_id!r}"
            )
        return self


__all__ = ["ModelDagEdge"]
