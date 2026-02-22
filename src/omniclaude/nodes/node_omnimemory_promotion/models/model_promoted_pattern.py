# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Promoted ticket generation pattern stored in OmniMemory.

A promoted pattern represents a stable, evidence-backed template for
generating Plan DAG work units for a specific intent type.  It is
reused by the Plan DAG Generator (OMN-2502) to short-circuit full
template generation when a matching pattern is found.

Implements the PromotedPatternProtocol interface used by the Plan DAG
Generator's PatternCacheProtocol.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Type aliases matching PromotedPatternProtocol from OMN-2502
_WorkUnitSpec = tuple[str, str, str, str]  # (local_id, title, unit_type, scope)
_DepSpec = tuple[str, str]  # (from_local_id, to_local_id)


class ModelPromotedPattern(BaseModel):
    """A stable, evidence-backed ticket generation pattern.

    Attributes:
        pattern_id: Stable unique ID for this promoted pattern.
        pattern_key: Normalized key for pattern lookup (intent_type + shape hash).
        intent_type: The intent type this pattern applies to.
        unit_specs: Work unit specs as (local_id, title, unit_type, scope) tuples.
        dep_specs: Dependency specs as (from_local_id, to_local_id) tuples.
        evidence_bundle_ids: IDs of evidence bundles backing this pattern.
        evidence_count: Number of successful evidence bundles backing this pattern.
        version: Monotonically increasing version (starts at 1, increments on bump).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    pattern_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable unique ID for this promoted pattern",
    )
    pattern_key: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Normalized key for pattern lookup (intent_type + shape hash)",
    )
    intent_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="The intent type this pattern applies to",
    )
    unit_specs: tuple[_WorkUnitSpec, ...] = Field(
        ...,
        description="Work unit specs as (local_id, title, unit_type, scope)",
    )
    dep_specs: tuple[_DepSpec, ...] = Field(
        default=(),
        description="Dependency specs as (from_local_id, to_local_id)",
    )
    evidence_bundle_ids: tuple[str, ...] = Field(
        ...,
        description="IDs of evidence bundles backing this pattern",
    )
    evidence_count: int = Field(
        ...,
        ge=1,
        description="Number of successful evidence bundles backing this pattern",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Monotonically increasing version",
    )

    @model_validator(mode="after")
    def _validate_evidence_bundle_count(self) -> ModelPromotedPattern:
        """evidence_count must equal the number of evidence_bundle_ids."""
        if len(self.evidence_bundle_ids) != self.evidence_count:
            raise ValueError(
                f"evidence_count ({self.evidence_count}) must match "
                f"len(evidence_bundle_ids) ({len(self.evidence_bundle_ids)})"
            )
        return self


__all__ = ["ModelPromotedPattern"]
