# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for NodeContextInjectionEffect.

Tests verify the effect node:
1. Only performs file I/O (no filtering/sorting)
2. Returns raw patterns from disk
3. Handles missing files gracefully
4. Handles malformed JSON gracefully
5. Deduplicates patterns by ID
6. Uses async properly

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omniclaude.hooks.node_context_injection_effect import (
    ModelContextRetrievalContract,
    ModelContextRetrievalResult,
    ModelPatternRecord,
    NodeContextInjectionEffect,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test Data
# =============================================================================

SAMPLE_PATTERN_1: dict[str, Any] = {
    "pattern_id": "pat-001",
    "domain": "testing",
    "title": "Test Pattern 1",
    "description": "Description for pattern 1",
    "confidence": 0.9,
    "usage_count": 10,
    "success_rate": 0.85,
    "example_reference": "src/test.py:42",
}

SAMPLE_PATTERN_2: dict[str, Any] = {
    "pattern_id": "pat-002",
    "domain": "code_review",
    "title": "Test Pattern 2",
    "description": "Description for pattern 2",
    "confidence": 0.7,
    "usage_count": 5,
    "success_rate": 0.80,
}

SAMPLE_PATTERN_FILE: dict[str, Any] = {
    "version": "1.0.0",
    "last_updated": "2025-01-26T12:00:00Z",
    "patterns": [SAMPLE_PATTERN_1, SAMPLE_PATTERN_2],
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with .claude folder."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return tmp_path


@pytest.fixture
def pattern_file(temp_project_dir: Path) -> Path:
    """Create a sample pattern file."""
    pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
    with pattern_path.open("w") as f:
        json.dump(SAMPLE_PATTERN_FILE, f)
    return pattern_path


@pytest.fixture
def node() -> NodeContextInjectionEffect:
    """Create a fresh node instance."""
    return NodeContextInjectionEffect()


# =============================================================================
# Node Properties Tests
# =============================================================================


class TestNodeProperties:
    """Test node properties and identity."""

    def test_default_node_id(self, node: NodeContextInjectionEffect) -> None:
        """Test default node ID is set."""
        assert node.node_id == "context-injection-effect-bootstrap"

    def test_custom_node_id(self) -> None:
        """Test custom node ID can be set."""
        custom_node = NodeContextInjectionEffect(node_id="custom-id")
        assert custom_node.node_id == "custom-id"

    def test_node_type(self, node: NodeContextInjectionEffect) -> None:
        """Test node type is 'effect'."""
        assert node.node_type == "effect"

    def test_node_type_is_string(self, node: NodeContextInjectionEffect) -> None:
        """Test node type returns a string."""
        assert isinstance(node.node_type, str)

    def test_node_id_is_string(self, node: NodeContextInjectionEffect) -> None:
        """Test node id returns a string."""
        assert isinstance(node.node_id, str)


# =============================================================================
# Contract Model Tests
# =============================================================================


class TestContractModels:
    """Test input/output contract models."""

    def test_contract_default_values(self) -> None:
        """Test contract has correct defaults."""
        contract = ModelContextRetrievalContract()
        assert contract.project_root is None
        assert contract.domain == ""

    def test_contract_with_values(self) -> None:
        """Test contract accepts values."""
        contract = ModelContextRetrievalContract(
            project_root="/path/to/project",
            domain="testing",
        )
        assert contract.project_root == "/path/to/project"
        assert contract.domain == "testing"

    def test_contract_is_frozen(self) -> None:
        """Test contract is immutable (frozen)."""
        contract = ModelContextRetrievalContract(project_root="/test")
        with pytest.raises(Exception):  # Pydantic raises ValidationError for frozen
            contract.project_root = "/other"  # type: ignore[misc]

    def test_contract_forbids_extra_fields(self) -> None:
        """Test contract rejects extra fields."""
        with pytest.raises(Exception):  # Pydantic raises ValidationError
            ModelContextRetrievalContract(
                project_root="/test",
                extra_field="not allowed",  # type: ignore[call-arg]
            )

    def test_result_model(self) -> None:
        """Test result model."""
        result = ModelContextRetrievalResult(
            success=True,
            patterns=[],
            source="test",
            retrieval_ms=42,
        )
        assert result.success is True
        assert result.patterns == []
        assert result.source == "test"
        assert result.retrieval_ms == 42

    def test_result_model_default_values(self) -> None:
        """Test result model default values."""
        result = ModelContextRetrievalResult(success=True)
        assert result.patterns == []
        assert result.source == "none"
        assert result.retrieval_ms == 0
        assert result.error_message is None

    def test_result_model_with_error(self) -> None:
        """Test result model with error message."""
        result = ModelContextRetrievalResult(
            success=False,
            source="error",
            error_message="Something went wrong",
        )
        assert result.success is False
        assert result.source == "error"
        assert result.error_message == "Something went wrong"

    def test_result_retrieval_ms_non_negative(self) -> None:
        """Test retrieval_ms must be non-negative."""
        with pytest.raises(Exception):  # Pydantic raises ValidationError
            ModelContextRetrievalResult(
                success=True,
                retrieval_ms=-1,
            )


# =============================================================================
# Pattern Record Tests
# =============================================================================


class TestPatternRecord:
    """Test ModelPatternRecord dataclass."""

    def test_create_pattern_record(self) -> None:
        """Test creating a pattern record."""
        record = ModelPatternRecord(
            pattern_id="test-001",
            domain="testing",
            title="Test Pattern",
            description="A test pattern",
            confidence=0.9,
            usage_count=10,
            success_rate=0.85,
            example_reference="file.py:42",
        )
        assert record.pattern_id == "test-001"
        assert record.domain == "testing"
        assert record.confidence == 0.9
        assert record.usage_count == 10
        assert record.success_rate == 0.85
        assert record.example_reference == "file.py:42"

    def test_pattern_record_optional_reference(self) -> None:
        """Test pattern record with no example reference."""
        record = ModelPatternRecord(
            pattern_id="test-002",
            domain="general",
            title="Test",
            description="Desc",
            confidence=0.5,
            usage_count=0,
            success_rate=0.0,
        )
        assert record.example_reference is None

    def test_pattern_record_is_frozen(self) -> None:
        """Test pattern record is immutable (frozen dataclass)."""
        record = ModelPatternRecord(
            pattern_id="test-003",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.5,
            usage_count=0,
            success_rate=0.0,
        )
        with pytest.raises(Exception):  # Frozen dataclass raises FrozenInstanceError
            record.pattern_id = "modified"  # type: ignore[misc]

    def test_pattern_record_equality(self) -> None:
        """Test pattern record equality (dataclass default)."""
        record1 = ModelPatternRecord(
            pattern_id="test-001",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.5,
            usage_count=0,
            success_rate=0.0,
        )
        record2 = ModelPatternRecord(
            pattern_id="test-001",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.5,
            usage_count=0,
            success_rate=0.0,
        )
        assert record1 == record2


# =============================================================================
# Execute Effect Tests
# =============================================================================


class TestExecuteEffect:
    """Test the main execute_effect method."""

    @pytest.mark.asyncio
    async def test_load_patterns_from_project(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test loading patterns from project directory."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert len(result.patterns) == 2
        assert result.retrieval_ms >= 0
        assert str(pattern_file) in result.source

    @pytest.mark.asyncio
    async def test_returns_raw_patterns_no_filtering(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that node returns raw patterns without filtering."""
        # Add a low-confidence pattern
        low_confidence_pattern = {
            **SAMPLE_PATTERN_1,
            "pattern_id": "pat-low",
            "confidence": 0.1,
        }
        patterns_data = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [SAMPLE_PATTERN_1, low_confidence_pattern],
        }
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Node should return ALL patterns (no filtering)
        assert len(result.patterns) == 2
        # Verify low confidence pattern is included
        confidences = [p.confidence for p in result.patterns]
        assert 0.1 in confidences

    @pytest.mark.asyncio
    async def test_returns_raw_patterns_no_sorting(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that node returns patterns in file order (no sorting)."""
        # Create patterns in reverse confidence order
        patterns_data = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [
                {**SAMPLE_PATTERN_1, "pattern_id": "low", "confidence": 0.3},
                {**SAMPLE_PATTERN_1, "pattern_id": "high", "confidence": 0.9},
            ],
        }
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Node should NOT sort - first pattern should still be low confidence
        assert result.patterns[0].confidence == 0.3
        assert result.patterns[1].confidence == 0.9

    @pytest.mark.asyncio
    async def test_no_pattern_file(
        self,
        node: NodeContextInjectionEffect,
        tmp_path: Path,
    ) -> None:
        """Test handling when no pattern file exists."""
        contract = ModelContextRetrievalContract(
            project_root=str(tmp_path),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert len(result.patterns) == 0
        assert result.source == "none"

    @pytest.mark.asyncio
    async def test_malformed_json(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test handling malformed JSON file."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            f.write("{ invalid json }")

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_deduplication_by_pattern_id(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test that duplicate pattern IDs are deduplicated."""
        duplicate_patterns = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [
                SAMPLE_PATTERN_1,
                {**SAMPLE_PATTERN_1, "title": "Duplicate"},  # Same pattern_id
            ],
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(duplicate_patterns, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should deduplicate - only 1 pattern with pat-001 ID
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "pat-001"
        # Keeps first occurrence, not the duplicate
        assert result.patterns[0].title == "Test Pattern 1"

    @pytest.mark.asyncio
    async def test_domain_hint_not_filtered(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that domain is just a hint, not filtered by node."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
            domain="testing",  # Only one pattern has this domain
        )
        result = await node.execute_effect(contract)

        # Node should NOT filter by domain - return all patterns
        assert len(result.patterns) == 2

    @pytest.mark.asyncio
    async def test_retrieval_ms_is_measured(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that retrieval_ms is populated."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # retrieval_ms should be set (usually 0-5ms for local file)
        assert result.retrieval_ms >= 0

    @pytest.mark.asyncio
    async def test_patterns_have_correct_types(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that returned patterns are ModelPatternRecord instances."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert len(result.patterns) == 2
        for pattern in result.patterns:
            assert isinstance(pattern, ModelPatternRecord)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_patterns_array(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test handling empty patterns array."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": []}, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_invalid_pattern_skipped(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test that invalid patterns are skipped."""
        patterns_data = {
            "version": "1.0.0",
            "patterns": [
                SAMPLE_PATTERN_1,
                {"invalid": "pattern"},  # Missing required fields
            ],
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(patterns_data, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with only valid pattern
        assert result.success is True
        assert len(result.patterns) == 1

    @pytest.mark.asyncio
    async def test_none_project_root(
        self,
        node: NodeContextInjectionEffect,
    ) -> None:
        """Test with None project root."""
        contract = ModelContextRetrievalContract(project_root=None)
        result = await node.execute_effect(contract)

        # Should succeed (may or may not find user-level patterns)
        assert result.success is True
        assert result.retrieval_ms >= 0

    @pytest.mark.asyncio
    async def test_nonexistent_project_path(
        self,
        node: NodeContextInjectionEffect,
    ) -> None:
        """Test with nonexistent project path."""
        contract = ModelContextRetrievalContract(
            project_root="/nonexistent/path/that/does/not/exist"
        )
        result = await node.execute_effect(contract)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_patterns_not_a_list(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test handling when patterns is not a list."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": "not a list"}, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_file_not_json_object(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test handling when file is not a JSON object."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(["not", "an", "object"], f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_empty_file(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test handling empty file."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        pattern_path.write_text("")

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert len(result.patterns) == 0

    @pytest.mark.asyncio
    async def test_pattern_with_missing_optional_field(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test pattern without optional example_reference field."""
        pattern_without_ref = {
            "pattern_id": "no-ref",
            "domain": "testing",
            "title": "No Reference",
            "description": "Pattern without example reference",
            "confidence": 0.8,
            "usage_count": 3,
            "success_rate": 0.75,
            # No example_reference field
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": [pattern_without_ref]}, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert len(result.patterns) == 1
        assert result.patterns[0].example_reference is None

    @pytest.mark.asyncio
    async def test_pattern_with_wrong_type_confidence(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test pattern with invalid confidence type is skipped."""
        patterns_data = {
            "version": "1.0.0",
            "patterns": [
                SAMPLE_PATTERN_1,
                {
                    **SAMPLE_PATTERN_2,
                    "pattern_id": "bad-conf",
                    "confidence": "not a number",
                },
            ],
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(patterns_data, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed with only valid pattern
        assert result.success is True
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "pat-001"


# =============================================================================
# Multiple Pattern Files Tests
# =============================================================================


class TestMultiplePatternFiles:
    """Test behavior with multiple pattern files."""

    @pytest.mark.asyncio
    async def test_deduplication_across_files(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Test patterns are deduplicated when same ID appears in multiple files.

        Note: This test only checks project-level patterns since user-level
        patterns depend on the actual ~/.claude directory which we don't control.
        """
        # Create project pattern file with a pattern
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(
                {
                    "version": "1.0.0",
                    "patterns": [
                        {**SAMPLE_PATTERN_1},
                        {**SAMPLE_PATTERN_1, "pattern_id": "unique-project"},
                    ],
                },
                f,
            )

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should have both patterns (different IDs)
        assert result.success is True
        pattern_ids = {p.pattern_id for p in result.patterns}
        assert "pat-001" in pattern_ids
        assert "unique-project" in pattern_ids


# =============================================================================
# Source Path Tests
# =============================================================================


class TestSourcePath:
    """Test source path reporting."""

    @pytest.mark.asyncio
    async def test_source_contains_pattern_file_path(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test source field contains the pattern file path."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.source == str(pattern_file)

    @pytest.mark.asyncio
    async def test_source_is_none_when_no_files(
        self,
        node: NodeContextInjectionEffect,
        tmp_path: Path,
    ) -> None:
        """Test source is 'none' when no pattern files exist."""
        contract = ModelContextRetrievalContract(
            project_root=str(tmp_path),
        )
        result = await node.execute_effect(contract)

        assert result.source == "none"


# =============================================================================
# Async Behavior Tests
# =============================================================================


class TestAsyncBehavior:
    """Test async execution behavior."""

    @pytest.mark.asyncio
    async def test_execute_effect_is_async(
        self,
        node: NodeContextInjectionEffect,
    ) -> None:
        """Test execute_effect is an async coroutine."""
        import inspect

        assert inspect.iscoroutinefunction(node.execute_effect)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_calls(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test multiple concurrent execute_effect calls work correctly."""
        import asyncio

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )

        # Execute multiple concurrent calls
        results = await asyncio.gather(
            node.execute_effect(contract),
            node.execute_effect(contract),
            node.execute_effect(contract),
        )

        # All should succeed with same patterns
        for result in results:
            assert result.success is True
            assert len(result.patterns) == 2


# =============================================================================
# Pattern File Structure Tests
# =============================================================================


class TestPatternFileStructure:
    """Test handling of various pattern file structures."""

    @pytest.mark.asyncio
    async def test_extra_fields_in_pattern_file_ignored(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test extra fields at top level of pattern file are ignored."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(
                {
                    "version": "1.0.0",
                    "last_updated": "2025-01-26T12:00:00Z",
                    "extra_field": "should be ignored",
                    "patterns": [SAMPLE_PATTERN_1],
                },
                f,
            )

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert len(result.patterns) == 1

    @pytest.mark.asyncio
    async def test_extra_fields_in_pattern_record_preserved(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test extra fields in pattern records don't cause errors."""
        pattern_with_extras = {
            **SAMPLE_PATTERN_1,
            "extra_field": "extra value",
            "another_extra": 123,
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": [pattern_with_extras]}, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed - extra fields are simply not included in the record
        assert result.success is True
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "pat-001"

    @pytest.mark.asyncio
    async def test_pattern_with_numeric_string_confidence(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test pattern with numeric string confidence is converted."""
        pattern_with_string_conf = {
            **SAMPLE_PATTERN_1,
            "pattern_id": "string-conf",
            "confidence": "0.85",  # String instead of float
        }
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": [pattern_with_string_conf]}, f)

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Should succeed - float() handles string conversion
        assert result.success is True
        assert len(result.patterns) == 1
        assert result.patterns[0].confidence == 0.85


# =============================================================================
# Error Message Tests
# =============================================================================


class TestErrorMessages:
    """Test error message handling in results."""

    @pytest.mark.asyncio
    async def test_success_has_no_error_message(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test successful retrieval has no error message."""
        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        assert result.success is True
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_graceful_degradation_still_success(
        self,
        node: NodeContextInjectionEffect,
        temp_project_dir: Path,
    ) -> None:
        """Test graceful degradation (malformed file) still returns success."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            f.write("not valid json")

        contract = ModelContextRetrievalContract(
            project_root=str(temp_project_dir),
        )
        result = await node.execute_effect(contract)

        # Graceful degradation - success with empty patterns
        assert result.success is True
        assert len(result.patterns) == 0
