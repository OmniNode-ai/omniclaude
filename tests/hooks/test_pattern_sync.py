# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests to verify CLI and handler PatternRecord definitions stay in sync.

The PatternRecord class is intentionally duplicated in two locations:
1. plugins/onex/hooks/lib/pattern_types.py (CLI - subprocess independence)
2. src/omniclaude/hooks/handler_context_injection.py (Handler - API model)

Both definitions MUST stay in sync to ensure consistent behavior.
This test module provides automated verification of that sync requirement.

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def cli_pattern_types_path() -> Path:
    """Path to CLI pattern_types.py file."""
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / "plugins" / "onex" / "hooks" / "lib" / "pattern_types.py"


@pytest.fixture
def handler_module_path() -> Path:
    """Path to handler_context_injection.py file."""
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / "src" / "omniclaude" / "hooks" / "handler_context_injection.py"


# =============================================================================
# AST-Based Field Extraction (for CLI that can't be imported)
# =============================================================================


def extract_dataclass_fields_from_ast(
    file_path: Path, class_name: str
) -> list[tuple[str, str, str | None]]:
    """Extract field definitions from a dataclass using AST parsing.

    Args:
        file_path: Path to Python file.
        class_name: Name of the dataclass to extract fields from.

    Returns:
        List of (field_name, type_annotation, default_value) tuples.

    Raises:
        ValueError: If class not found or not a dataclass.
    """
    source = file_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # Verify it's a dataclass (check for @dataclass decorator)
            is_dataclass = any(
                (isinstance(d, ast.Name) and d.id == "dataclass")
                or (
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Name)
                    and d.func.id == "dataclass"
                )
                for d in node.decorator_list
            )
            if not is_dataclass:
                raise ValueError(f"{class_name} is not a dataclass")

            fields_list: list[tuple[str, str, str | None]] = []

            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    field_name = item.target.id
                    # Skip private/internal fields like __post_init__
                    if field_name.startswith("_"):
                        continue

                    type_annotation = ast.unparse(item.annotation)
                    default_value = ast.unparse(item.value) if item.value else None

                    fields_list.append((field_name, type_annotation, default_value))

            return fields_list

    raise ValueError(f"Class {class_name} not found in {file_path}")


# =============================================================================
# Sync Verification Tests
# =============================================================================


class TestPatternRecordSync:
    """Verify CLI and handler PatternRecord definitions stay in sync."""

    def test_field_names_match(
        self,
        cli_pattern_types_path: Path,
        handler_module_path: Path,
    ) -> None:
        """Verify both PatternRecord classes have identical field names."""
        cli_fields = extract_dataclass_fields_from_ast(
            cli_pattern_types_path, "PatternRecord"
        )
        handler_fields = extract_dataclass_fields_from_ast(
            handler_module_path, "PatternRecord"
        )

        cli_field_names = [f[0] for f in cli_fields]
        handler_field_names = [f[0] for f in handler_fields]

        assert cli_field_names == handler_field_names, (
            f"Field names mismatch!\n"
            f"CLI fields: {cli_field_names}\n"
            f"Handler fields: {handler_field_names}\n"
            f"These definitions MUST stay in sync. See docstrings for rationale."
        )

    def test_field_types_match(
        self,
        cli_pattern_types_path: Path,
        handler_module_path: Path,
    ) -> None:
        """Verify both PatternRecord classes have identical field types."""
        cli_fields = extract_dataclass_fields_from_ast(
            cli_pattern_types_path, "PatternRecord"
        )
        handler_fields = extract_dataclass_fields_from_ast(
            handler_module_path, "PatternRecord"
        )

        # Compare types (normalize whitespace)
        for cli_field, handler_field in zip(cli_fields, handler_fields):
            cli_name, cli_type, _ = cli_field
            _handler_name, handler_type, _ = handler_field

            # Normalize type strings (remove extra whitespace)
            cli_type_normalized = " ".join(cli_type.split())
            handler_type_normalized = " ".join(handler_type.split())

            assert cli_type_normalized == handler_type_normalized, (
                f"Type mismatch for field '{cli_name}'!\n"
                f"CLI type: {cli_type_normalized}\n"
                f"Handler type: {handler_type_normalized}\n"
                f"These definitions MUST stay in sync."
            )

    def test_field_defaults_match(
        self,
        cli_pattern_types_path: Path,
        handler_module_path: Path,
    ) -> None:
        """Verify both PatternRecord classes have identical field defaults."""
        cli_fields = extract_dataclass_fields_from_ast(
            cli_pattern_types_path, "PatternRecord"
        )
        handler_fields = extract_dataclass_fields_from_ast(
            handler_module_path, "PatternRecord"
        )

        for cli_field, handler_field in zip(cli_fields, handler_fields):
            cli_name, _, cli_default = cli_field
            _handler_name, _, handler_default = handler_field

            assert cli_default == handler_default, (
                f"Default mismatch for field '{cli_name}'!\n"
                f"CLI default: {cli_default}\n"
                f"Handler default: {handler_default}\n"
                f"These definitions MUST stay in sync."
            )

    def test_field_count_is_eight(
        self,
        cli_pattern_types_path: Path,
        handler_module_path: Path,
    ) -> None:
        """Verify both PatternRecord classes have exactly 8 fields.

        The API model should have exactly 8 core fields. If this changes,
        it likely means someone added database-specific fields that should
        be in DbPatternRecord instead.
        """
        cli_fields = extract_dataclass_fields_from_ast(
            cli_pattern_types_path, "PatternRecord"
        )
        handler_fields = extract_dataclass_fields_from_ast(
            handler_module_path, "PatternRecord"
        )

        assert len(cli_fields) == 8, (
            f"CLI PatternRecord has {len(cli_fields)} fields, expected 8.\n"
            f"Fields: {[f[0] for f in cli_fields]}\n"
            f"If adding database fields, use DbPatternRecord instead."
        )

        assert len(handler_fields) == 8, (
            f"Handler PatternRecord has {len(handler_fields)} fields, expected 8.\n"
            f"Fields: {[f[0] for f in handler_fields]}\n"
            f"If adding database fields, use DbPatternRecord instead."
        )

    def test_expected_field_names(
        self,
        cli_pattern_types_path: Path,
    ) -> None:
        """Verify the expected field names are present."""
        expected_fields = [
            "pattern_id",
            "domain",
            "title",
            "description",
            "confidence",
            "usage_count",
            "success_rate",
            "example_reference",
        ]

        cli_fields = extract_dataclass_fields_from_ast(
            cli_pattern_types_path, "PatternRecord"
        )
        cli_field_names = [f[0] for f in cli_fields]

        assert cli_field_names == expected_fields, (
            f"Field names don't match expected API model!\n"
            f"Expected: {expected_fields}\n"
            f"Actual: {cli_field_names}"
        )


class TestPatternRecordValidation:
    """Test that validation logic is consistent between CLI and handler."""

    def test_cli_validation_bounds(self, cli_pattern_types_path: Path) -> None:
        """Verify CLI PatternRecord has __post_init__ with validation."""
        source = cli_pattern_types_path.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PatternRecord":
                # Find __post_init__ method
                post_init_found = False
                for item in node.body:
                    if (
                        isinstance(item, ast.FunctionDef)
                        and item.name == "__post_init__"
                    ):
                        post_init_found = True
                        # Check for validation keywords
                        source_segment = ast.unparse(item)
                        assert "confidence" in source_segment, (
                            "Missing confidence validation"
                        )
                        assert "success_rate" in source_segment, (
                            "Missing success_rate validation"
                        )
                        assert "usage_count" in source_segment, (
                            "Missing usage_count validation"
                        )
                        break

                assert post_init_found, (
                    "CLI PatternRecord missing __post_init__ validation"
                )
                return

        pytest.fail("PatternRecord class not found in CLI module")

    def test_handler_validation_bounds(self, handler_module_path: Path) -> None:
        """Verify handler PatternRecord has __post_init__ with validation."""
        source = handler_module_path.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PatternRecord":
                # Find __post_init__ method
                post_init_found = False
                for item in node.body:
                    if (
                        isinstance(item, ast.FunctionDef)
                        and item.name == "__post_init__"
                    ):
                        post_init_found = True
                        # Check for validation keywords
                        source_segment = ast.unparse(item)
                        assert "confidence" in source_segment, (
                            "Missing confidence validation"
                        )
                        assert "success_rate" in source_segment, (
                            "Missing success_rate validation"
                        )
                        assert "usage_count" in source_segment, (
                            "Missing usage_count validation"
                        )
                        break

                assert post_init_found, (
                    "Handler PatternRecord missing __post_init__ validation"
                )
                return

        pytest.fail("PatternRecord class not found in handler module")
