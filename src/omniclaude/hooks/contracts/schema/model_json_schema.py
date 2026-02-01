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
    from collections.abc import Iterator, Mapping

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


def _iter_models_with_data(
    model: BaseModel,
    data: Mapping[str, object],
) -> Iterator[tuple[BaseModel, Mapping[str, object]]]:
    """Recursively iterate over models paired with their corresponding raw data.

    Yields (model, data) tuples for the model and all nested BaseModel instances,
    matched with their corresponding input data dictionaries.

    Args:
        model: The root model to iterate from.
        data: The raw input data that was used to create the model.

    Yields:
        Tuples of (model_instance, corresponding_raw_data).
    """
    yield (model, data)

    for field_name, field_value in model.__dict__.items():
        field_data = data.get(field_name)

        if isinstance(field_value, BaseModel) and isinstance(field_data, dict):
            yield from _iter_models_with_data(field_value, field_data)

        elif isinstance(field_value, dict) and isinstance(field_data, dict):
            for key, v in field_value.items():
                if isinstance(v, BaseModel):
                    nested_data = field_data.get(key)
                    if isinstance(nested_data, dict):
                        yield from _iter_models_with_data(v, nested_data)

        elif isinstance(field_value, list) and isinstance(field_data, list):
            for i, item in enumerate(field_value):
                if isinstance(item, BaseModel) and i < len(field_data):
                    nested_data = field_data[i]
                    if isinstance(nested_data, dict):
                        yield from _iter_models_with_data(item, nested_data)


def _get_extra_keys(model: BaseModel, data: Mapping[str, object]) -> list[str]:
    """Get keys in data that are not defined fields in the model.

    Args:
        model: The model to check against.
        data: The raw input data.

    Returns:
        List of extra keys not in model fields.
    """
    # Access model_fields from the class to avoid deprecation warning
    expected_fields = set(type(model).model_fields.keys())
    actual_keys = set(data.keys())
    return sorted(actual_keys - expected_fields)


def assert_no_extra_fields(
    model: BaseModel,
    *,
    raw_data: Mapping[str, object] | None = None,
    recursive: bool = True,
) -> None:
    """Assert that a model and its nested models have no extra fields.

    Use this function at contract boundaries where strict validation is
    required. Models with extra="ignore" silently drop unknown fields;
    this function detects when that happened and raises an error.

    IMPORTANT: For models with extra="ignore", you MUST provide raw_data
    to detect extra fields. Without raw_data, only models with extra="allow"
    (which populate model_extra) can be checked.

    Args:
        model: The model to check for extra fields.
        raw_data: The original input data used to create the model.
            Required to detect extra fields when model has extra="ignore".
            If not provided, falls back to checking model_extra (only works
            for models with extra="allow").
        recursive: If True (default), also check nested BaseModel instances.

    Raises:
        ValueError: If any model has extra fields.

    Example:
        >>> data = {"type": "string", "unknown_key": "value"}
        >>> definition = ModelJsonSchemaDefinition.model_validate(data)
        >>> # This detects "unknown_key" even with extra="ignore"
        >>> assert_no_extra_fields(definition, raw_data=data)

    Note:
        Models with extra="forbid" will have already raised during parsing.
    """
    if raw_data is not None:
        # Use raw_data to detect extra fields - works with extra="ignore"
        pairs: list[tuple[BaseModel, Mapping[str, object]]]
        if recursive:
            pairs = list(_iter_models_with_data(model, raw_data))
        else:
            pairs = [(model, raw_data)]

        for m, d in pairs:
            extra_keys = _get_extra_keys(m, d)
            if extra_keys:
                model_name = type(m).__name__
                raise ValueError(
                    f"{model_name} has unknown fields: {extra_keys}. "
                    "Contract schema dialect does not allow these keywords."
                )
    else:
        # Fallback: check model_extra (only works with extra="allow")
        models_to_check = _iter_models(model) if recursive else [model]

        for m in models_to_check:
            if m.model_extra:
                extra_keys = list(m.model_extra.keys())
                model_name = type(m).__name__
                raise ValueError(
                    f"{model_name} has unknown fields: {extra_keys}. "
                    "Contract schema dialect does not allow these keywords."
                )
