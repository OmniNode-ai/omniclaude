# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Canonical JSON Schema models for hook contract definitions.

This module provides the single source of truth for JSON Schema-like models
used in hook contracts. These models represent a "contract-schema dialect" -
a bounded subset of JSON Schema sufficient for describing hook event payloads.

Models are permissive by default (extra="ignore") for forward compatibility.
Use assert_no_extra_fields() for strict enforcement at contract boundaries.

Ticket: OMN-1812 - Consolidate hook contract schema models
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "ModelJsonSchemaProperty",
    "ModelJsonSchemaDefinition",
    "assert_no_extra_fields",
]


class ModelJsonSchemaProperty(BaseModel):
    """JSON Schema property definition for contract documentation.

    Represents a single property in a JSON Schema definition, capturing
    type information, constraints, and documentation for contract models.

    This model supports the JSON Schema keywords commonly used in hook
    contracts. Unknown keywords are ignored for forward compatibility.

    Attributes:
        type: JSON Schema type (string, integer, boolean, object, array).
        description: Human-readable description of the property.
        format: Optional format specifier (uuid, date-time, etc.).
        nullable: Whether the property can be null.
        minLength: Minimum string length constraint.
        maxLength: Maximum string length constraint.
        minimum: Minimum numeric value constraint.
        maximum: Maximum numeric value constraint.
        enum: List of allowed values for the property.
        default: Default value for the property.

    Example:
        >>> prop = ModelJsonSchemaProperty(
        ...     type="string",
        ...     description="User identifier",
        ...     format="uuid",
        ...     minLength=36,
        ...     maxLength=36,
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",  # Forward compatible: ignore unknown JSON Schema keywords
    )

    type: str = Field(
        ...,
        min_length=1,
        description="JSON Schema type (string, integer, boolean, object, array)",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of the property",
    )
    format: str | None = Field(
        default=None,
        min_length=1,
        description="Optional format specifier (uuid, date-time, etc.)",
    )
    nullable: bool | None = Field(
        default=None,
        description="Whether the property can be null",
    )
    minLength: int | None = Field(
        default=None,
        ge=0,
        description="Minimum string length constraint",
    )
    maxLength: int | None = Field(
        default=None,
        ge=0,
        description="Maximum string length constraint",
    )
    minimum: int | float | None = Field(
        default=None,
        description="Minimum numeric value constraint",
    )
    maximum: int | float | None = Field(
        default=None,
        description="Maximum numeric value constraint",
    )
    enum: list[str] | None = Field(
        default=None,
        description="List of allowed values for the property",
    )
    default: bool | int | float | str | None = Field(
        default=None,
        description="Default value for the property",
    )


class ModelJsonSchemaDefinition(BaseModel):
    """JSON Schema object definition for contract documentation.

    Represents a complete JSON Schema object definition, typically describing
    a Pydantic model in the contract. Used for documentation and reference,
    with actual runtime models defined separately.

    This model is permissive by default. For strict validation, use
    assert_no_extra_fields() after parsing.

    Attributes:
        type: Schema type (typically 'object' for model definitions).
        description: Human-readable description of the model.
        properties: Mapping of property names to their schema definitions.
        required: List of required property names.

    Example:
        >>> definition = ModelJsonSchemaDefinition(
        ...     type="object",
        ...     description="User profile model",
        ...     properties={"id": ModelJsonSchemaProperty(type="string", format="uuid")},
        ...     required=["id"],
        ... )
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",  # Forward compatible: ignore unknown JSON Schema keywords
    )

    type: str = Field(
        ...,
        min_length=1,
        description="Schema type (typically 'object' for model definitions)",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the model",
    )
    properties: dict[str, ModelJsonSchemaProperty] = Field(
        default_factory=dict,
        description="Mapping of property names to their schema definitions",
    )
    required: list[str] = Field(
        default_factory=list,
        description="List of required property names",
    )


def _iter_models(model: BaseModel) -> Iterator[BaseModel]:
    """Recursively iterate over all nested BaseModel instances.

    Yields the model itself and all nested BaseModel instances found in
    fields that are dicts or lists containing BaseModels.

    Args:
        model: The root model to iterate from.

    Yields:
        All BaseModel instances in the model tree.
    """
    yield model
    for field_value in model.__dict__.values():
        if isinstance(field_value, BaseModel):
            yield from _iter_models(field_value)
        elif isinstance(field_value, dict):
            for v in field_value.values():
                if isinstance(v, BaseModel):
                    yield from _iter_models(v)
        elif isinstance(field_value, list):
            for item in field_value:
                if isinstance(item, BaseModel):
                    yield from _iter_models(item)


def assert_no_extra_fields(model: BaseModel, *, recursive: bool = True) -> None:
    """Assert that a model and its nested models have no extra fields.

    Use this function at contract boundaries where strict validation is
    required. Models with extra="ignore" silently drop unknown fields;
    this function detects when that happened and raises an error.

    Args:
        model: The model to check for extra fields.
        recursive: If True (default), also check nested BaseModel instances.

    Raises:
        ValueError: If any model has extra fields in model_extra.

    Example:
        >>> definition = ModelJsonSchemaDefinition.model_validate(data)
        >>> assert_no_extra_fields(definition)  # Raises if unknown keys present

    Note:
        This function only checks models that have extra="ignore" configured.
        Models with extra="forbid" will have already raised during parsing.
    """
    models_to_check = _iter_models(model) if recursive else [model]

    for m in models_to_check:
        if m.model_extra:
            extra_keys = list(m.model_extra.keys())
            model_name = type(m).__name__
            raise ValueError(
                f"{model_name} has unknown fields: {extra_keys}. "
                "Contract schema dialect does not allow these keywords."
            )
