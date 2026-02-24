# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for assert_no_extra_fields function.

Validates that extra fields are detected correctly even with extra="ignore"
models, which was a bug fixed in OMN-1812.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from omniclaude.hooks.contracts.schema import (
    ModelJsonSchemaDefinition,
    ModelJsonSchemaProperty,
    assert_no_extra_fields,
)

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


class TestAssertNoExtraFieldsWithRawData:
    """Tests for assert_no_extra_fields when raw_data is provided."""

    def test_detects_extra_fields_with_extra_ignore(self) -> None:
        """Extra fields are detected when raw_data is provided."""
        data = {
            "type": "string",
            "description": "A string property",
            "unknown_key": "should be detected",
        }
        prop = ModelJsonSchemaProperty.model_validate(data)

        # Without raw_data, this would pass (bug before the fix)
        # With raw_data, it correctly detects the extra field
        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(prop, raw_data=data)

        assert "unknown_key" in str(exc_info.value)
        assert "ModelJsonSchemaProperty" in str(exc_info.value)

    def test_passes_when_no_extra_fields(self) -> None:
        """No error when all fields are valid."""
        data = {
            "type": "string",
            "description": "A string property",
            "format": "uuid",
        }
        prop = ModelJsonSchemaProperty.model_validate(data)

        # Should not raise
        assert_no_extra_fields(prop, raw_data=data)

    def test_detects_multiple_extra_fields(self) -> None:
        """All extra fields are reported."""
        data = {
            "type": "string",
            "extra1": "value1",
            "extra2": "value2",
        }
        prop = ModelJsonSchemaProperty.model_validate(data)

        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(prop, raw_data=data)

        error_msg = str(exc_info.value)
        assert "extra1" in error_msg
        assert "extra2" in error_msg

    def test_recursive_detection_in_nested_models(self) -> None:
        """Extra fields in nested models are detected recursively."""
        data = {
            "type": "object",
            "description": "A definition with nested property",
            "properties": {
                "name": {
                    "type": "string",
                    "nested_extra": "should be detected",
                }
            },
        }
        definition = ModelJsonSchemaDefinition.model_validate(data)

        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(definition, raw_data=data, recursive=True)

        assert "nested_extra" in str(exc_info.value)
        assert "ModelJsonSchemaProperty" in str(exc_info.value)

    def test_non_recursive_only_checks_root(self) -> None:
        """With recursive=False, only root model is checked."""
        data = {
            "type": "object",
            "description": "A definition",
            "properties": {
                "name": {
                    "type": "string",
                    "nested_extra": "ignored when non-recursive",
                }
            },
        }
        definition = ModelJsonSchemaDefinition.model_validate(data)

        # Should not raise because nested extra is not checked
        assert_no_extra_fields(definition, raw_data=data, recursive=False)

    def test_detects_root_extra_even_when_nested_valid(self) -> None:
        """Root level extra fields are detected even with valid nested models."""
        data = {
            "type": "object",
            "description": "A definition",
            "root_extra": "should be detected",
            "properties": {"name": {"type": "string"}},
        }
        definition = ModelJsonSchemaDefinition.model_validate(data)

        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(definition, raw_data=data)

        assert "root_extra" in str(exc_info.value)
        assert "ModelJsonSchemaDefinition" in str(exc_info.value)


class TestAssertNoExtraFieldsFallback:
    """Tests for fallback behavior when raw_data is not provided."""

    def test_fallback_checks_model_extra(self) -> None:
        """Without raw_data, checks model_extra (only works with extra='allow')."""

        class AllowExtraModel(BaseModel):
            model_config = ConfigDict(extra="allow")
            name: str

        data = {"name": "test", "extra_field": "value"}
        model = AllowExtraModel.model_validate(data)

        # model_extra should contain the extra field
        assert model.model_extra == {"extra_field": "value"}

        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(model)

        assert "extra_field" in str(exc_info.value)

    def test_fallback_misses_extras_with_ignore(self) -> None:
        """Demonstrates the limitation: without raw_data, extra='ignore' extras are missed."""

        class IgnoreExtraModel(BaseModel):
            model_config = ConfigDict(extra="ignore")
            name: str

        data = {"name": "test", "extra_field": "value"}
        model = IgnoreExtraModel.model_validate(data)

        # model_extra is empty because extras were silently dropped
        assert not model.model_extra

        # Without raw_data, we cannot detect the dropped field
        # This is the documented limitation - raw_data is required for extra="ignore"
        assert_no_extra_fields(model)  # Does not raise!


class TestAssertNoExtraFieldsEdgeCases:
    """Edge case tests for assert_no_extra_fields."""

    def test_empty_data(self) -> None:
        """Empty optional data with required defaults works."""
        data = {"type": "object", "description": "minimal"}
        definition = ModelJsonSchemaDefinition.model_validate(data)

        assert_no_extra_fields(definition, raw_data=data)

    def test_nested_list_of_models(self) -> None:
        """Extra fields in list items are detected."""
        # While ModelJsonSchemaDefinition doesn't have list fields of models,
        # the implementation should handle them
        data = {
            "type": "object",
            "description": "A definition",
            "properties": {
                "item1": {"type": "string"},
                "item2": {"type": "integer", "extra_in_item": "detected"},
            },
        }
        definition = ModelJsonSchemaDefinition.model_validate(data)

        with pytest.raises(ValueError) as exc_info:
            assert_no_extra_fields(definition, raw_data=data)

        assert "extra_in_item" in str(exc_info.value)

    def test_mismatched_data_types_handled_gracefully(self) -> None:
        """Mismatched data types don't cause crashes."""
        data = {
            "type": "object",
            "description": "A definition",
            "properties": "not_a_dict",  # Wrong type - will fail validation
        }

        # This should fail validation, not our check
        with pytest.raises(Exception):
            ModelJsonSchemaDefinition.model_validate(data)
