"""ModelGapFinding — a single integration drift finding from gap analysis."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .enum_gap_category import EnumGapCategory


class ModelGapFinding(BaseModel):
    """A single integration gap or drift finding."""

    model_schema_version: str = "1.0"

    # Core identity
    fingerprint: str = Field(
        description=(
            "SHA-256 of: category|boundary_kind|rule_name|sorted(repos)"
            "|seam_id_suffix|mismatch_shape|repo_relative_path"
        )
    )
    category: EnumGapCategory
    boundary_kind: str = Field(
        description=(
            "e.g. kafka_topic, model_field, fk_reference, api_contract, db_boundary"
        )
    )
    rule_name: str = Field(description="e.g. topic_name_mismatch, field_type_drift")
    seam_id: str = Field(description="Full seam identifier (topic/path/endpoint)")
    seam_id_suffix: str = Field(
        description="Suffix-only portion of seam_id (no env/namespace prefix)"
    )
    repos: list[str] = Field(description="Canonical repo names involved")

    # Severity and confidence
    severity: Literal["CRITICAL", "WARNING", "INFO"]
    confidence: Literal["DETERMINISTIC", "BEST_EFFORT", "SKIP"]
    evidence_method: Literal["registry", "ast", "grep", "schema_json", "openapi"]

    # Location
    repo_relative_path: str = Field(
        description="Path relative to repo root (not absolute)"
    )

    # Proof blob
    proof: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Full evidence blob. For Kafka: expected_topic, observed_topic, "
            "source_location. For DB: connection strings, table names."
        ),
    )
    mismatch_shape: str = Field(
        default="",
        description="Compact description of the mismatch (for fingerprint stability)",
    )

    # Ticket linkage (populated after Phase 3)
    ticket_id: str | None = None

    # Marker block fields (populated when writing ticket)
    detected_at: str | None = None

    class Config:
        frozen = True
        extra = "ignore"
        from_attributes = True
