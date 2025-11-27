#!/usr/bin/env python3
"""
Pydantic models for prompt parsing results.

This module defines the data structures used to represent parsed prompt metadata
for autonomous node generation.
"""

from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class PromptParseResult(BaseModel):
    """
    Result of parsing a natural language prompt for node generation.

    This model contains all extracted metadata required for generating
    ONEX-compliant nodes, including node type, domain, and requirements.
    """

    node_name: str = Field(
        ...,
        description="Extracted node name in PascalCase (e.g., 'DatabaseWriter')",
        min_length=1,
    )

    node_type: str = Field(
        ...,
        description="Node type: EFFECT, COMPUTE, REDUCER, or ORCHESTRATOR",
        pattern="^(EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)$",
    )

    domain: str = Field(
        ...,
        description="Domain identifier in snake_case (e.g., 'data_services')",
        min_length=1,
    )

    description: str = Field(
        ..., description="Business description of what the node does", min_length=1
    )

    functional_requirements: list[str] = Field(
        default_factory=list, description="Extracted functional requirements"
    )

    external_systems: list[str] = Field(
        default_factory=list,
        description="Detected external system dependencies (e.g., 'PostgreSQL', 'Redis')",
    )

    confidence: float = Field(
        ...,
        description="Parsing confidence score (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    correlation_id: UUID = Field(
        default_factory=uuid4, description="Request correlation ID"
    )

    session_id: UUID = Field(default_factory=uuid4, description="Session ID")

    @field_validator("node_name")
    @classmethod
    def validate_node_name(cls, v):
        """Validate node name is a valid Python identifier in PascalCase."""
        if not v:
            raise ValueError("Node name cannot be empty")

        # Check if valid Python identifier
        if not v.replace("_", "").isalnum():
            raise ValueError(
                f"Node name '{v}' must be alphanumeric (underscores allowed)"
            )

        if not v[0].isupper():
            raise ValueError(
                f"Node name '{v}' must start with uppercase letter (PascalCase)"
            )

        return v

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v):
        """Validate domain follows snake_case convention."""
        if not v:
            raise ValueError("Domain cannot be empty")

        # Check if valid snake_case
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Domain '{v}' must be alphanumeric with underscores")

        if v[0].isupper():
            raise ValueError(
                f"Domain '{v}' should be lowercase (snake_case convention)"
            )

        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v):
        """Validate description has minimum length."""
        if len(v.strip()) < 10:
            raise ValueError(
                "Description must be at least 10 characters for meaningful context"
            )
        return v.strip()

    model_config = {
        "validate_assignment": True,
        "extra": "forbid",  # Reject unknown fields
    }


__all__ = ["PromptParseResult"]
