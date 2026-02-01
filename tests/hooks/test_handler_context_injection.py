# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for HandlerContextInjection.

Tests verify the handler:
1. Loads patterns from disk (I/O)
2. Filters by domain when specified
3. Filters by confidence threshold (default 0.7)
4. Sorts by confidence descending
5. Limits to max_patterns (default 5)
6. Handles missing files gracefully
7. Handles malformed JSON gracefully
8. Deduplicates patterns by ID
9. Uses async properly

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelInjectionResult,
    ModelPatternRecord,
    inject_patterns,
    inject_patterns_sync,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test Data - Module-level constants for reference
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
    "confidence": 0.8,
    "usage_count": 5,
    "success_rate": 0.80,
}

SAMPLE_PATTERN_FILE: dict[str, Any] = {
    "version": "1.0.0",
    "last_updated": "2025-01-26T12:00:00Z",
    "patterns": [SAMPLE_PATTERN_1, SAMPLE_PATTERN_2],
}

# Low confidence pattern (below default 0.7 threshold)
SAMPLE_LOW_CONFIDENCE_PATTERN: dict[str, Any] = {
    "pattern_id": "pat-low",
    "domain": "testing",
    "title": "Low Confidence Pattern",
    "description": "Pattern with low confidence",
    "confidence": 0.5,
    "usage_count": 2,
    "success_rate": 0.60,
}

# General domain pattern (included in all domain filters)
SAMPLE_GENERAL_DOMAIN_PATTERN: dict[str, Any] = {
    "pattern_id": "pat-general",
    "domain": "general",
    "title": "General Pattern",
    "description": "Pattern applicable to all domains",
    "confidence": 0.85,
    "usage_count": 20,
    "success_rate": 0.90,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate tests from user's real ~/.claude/ directory.

    This fixture patches Path.home() to return a temporary directory,
    preventing tests from being affected by actual user-level pattern files.
    This ensures test isolation and prevents flaky tests.

    Autouse=True means this applies to ALL tests in this module.
    """
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()

    # Patch Path.home() to return our fake home directory
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    return fake_home


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with .claude folder."""
    # Use a subdirectory of tmp_path distinct from fake_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir()
    return project_dir


@pytest.fixture
def pattern_file(temp_project_dir: Path) -> Path:
    """Create a sample pattern file with SAMPLE_PATTERN_FILE content."""
    pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
    with pattern_path.open("w") as f:
        json.dump(SAMPLE_PATTERN_FILE, f)
    return pattern_path


@pytest.fixture
def sample_patterns() -> dict[str, dict[str, Any]]:
    """Provide access to all sample patterns as a dictionary.

    Useful for tests that need to reference or modify sample patterns.

    Returns:
        Dictionary with keys: 'high_confidence', 'code_review',
        'low_confidence', 'general_domain'
    """
    return {
        "high_confidence": SAMPLE_PATTERN_1,
        "code_review": SAMPLE_PATTERN_2,
        "low_confidence": SAMPLE_LOW_CONFIDENCE_PATTERN,
        "general_domain": SAMPLE_GENERAL_DOMAIN_PATTERN,
    }


@pytest.fixture
def permissive_config() -> ContextInjectionConfig:
    """Config with low threshold to allow all patterns through.

    Note: db_enabled=False ensures file-based tests work without database.
    """
    return ContextInjectionConfig(
        enabled=True,
        min_confidence=0.0,  # Allow all
        max_patterns=20,  # High limit (max allowed is 20)
        db_enabled=False,  # Use file-based loading for tests
    )


@pytest.fixture
def handler(permissive_config: ContextInjectionConfig) -> HandlerContextInjection:
    """Create a fresh handler instance with permissive config."""
    return HandlerContextInjection(config=permissive_config)


@pytest.fixture
def default_handler() -> HandlerContextInjection:
    """Create a handler with default config (min_confidence=0.7).

    Note: db_enabled=False ensures file-based tests work without database.
    """
    return HandlerContextInjection(
        config=ContextInjectionConfig(enabled=True, db_enabled=False)
    )


# =============================================================================
# Handler Properties Tests
# =============================================================================


class TestHandlerProperties:
    """Test handler properties and identity."""

    def test_handler_id(self, handler: HandlerContextInjection) -> None:
        """Test handler ID is set."""
        assert handler.handler_id == "handler-context-injection"

    def test_handler_id_is_string(self, handler: HandlerContextInjection) -> None:
        """Test handler ID returns a string."""
        assert isinstance(handler.handler_id, str)


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
# Result Model Tests
# =============================================================================


class TestInjectionResult:
    """Test ModelInjectionResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating a result."""
        result = ModelInjectionResult(
            success=True,
            context_markdown="## Patterns",
            pattern_count=2,
            context_size_bytes=100,
            source="/path/to/file",
            retrieval_ms=42,
        )
        assert result.success is True
        assert result.context_markdown == "## Patterns"
        assert result.pattern_count == 2
        assert result.context_size_bytes == 100
        assert result.source == "/path/to/file"
        assert result.retrieval_ms == 42

    def test_result_is_frozen(self) -> None:
        """Test result is immutable (frozen dataclass)."""
        result = ModelInjectionResult(
            success=True,
            context_markdown="",
            pattern_count=0,
            context_size_bytes=0,
            source="none",
            retrieval_ms=0,
        )
        with pytest.raises(Exception):  # Frozen dataclass raises FrozenInstanceError
            result.success = False  # type: ignore[misc]


# =============================================================================
# Handler Handle Tests
# =============================================================================


class TestHandlerHandle:
    """Test the main handle method."""

    @pytest.mark.asyncio
    async def test_load_patterns_from_project(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test loading patterns from project directory."""
        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 2
        assert result.retrieval_ms >= 0
        assert str(pattern_file) in result.source

    @pytest.mark.asyncio
    async def test_filters_by_confidence_threshold(
        self,
        default_handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that handler filters patterns by confidence threshold."""
        # Default config has min_confidence=0.7
        # Use the predefined low-confidence pattern (0.5 confidence)
        patterns_data = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [SAMPLE_PATTERN_1, SAMPLE_LOW_CONFIDENCE_PATTERN],
        }
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        result = await default_handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Handler should filter out low confidence pattern (0.5 < 0.7)
        assert result.pattern_count == 1
        # High confidence pattern (0.9) should be included
        assert "Test Pattern 1" in result.context_markdown

    @pytest.mark.asyncio
    async def test_sorts_by_effective_score_descending(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that handler sorts patterns by effective_score descending.

        Note: OMN-1671 changed sorting from pure confidence to effective_score,
        which is: confidence * success_rate * f(usage_count).
        """
        # Create patterns with different effective scores
        # Use different domains to avoid domain cap (max_per_domain=2 default)
        patterns_data = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [
                {
                    **SAMPLE_PATTERN_1,
                    "pattern_id": "low",
                    "domain": "debugging",
                    "title": "Low",
                    "confidence": 0.75,
                    "success_rate": 0.5,
                    "usage_count": 5,  # Low effective score
                },
                {
                    **SAMPLE_PATTERN_1,
                    "pattern_id": "high",
                    "domain": "testing",
                    "title": "High",
                    "confidence": 0.95,
                    "success_rate": 0.9,
                    "usage_count": 20,  # High effective score
                },
                {
                    **SAMPLE_PATTERN_1,
                    "pattern_id": "mid",
                    "domain": "code_review",
                    "title": "Mid",
                    "confidence": 0.85,
                    "success_rate": 0.7,
                    "usage_count": 10,  # Mid effective score
                },
            ],
        }
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        # Use min_confidence=0.0 to include all patterns
        config = ContextInjectionConfig(
            enabled=True,
            min_confidence=0.0,
            db_enabled=False,
        )
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Handler sorts by effective_score descending
        # High should appear before Mid before Low
        high_pos = result.context_markdown.find("High")
        mid_pos = result.context_markdown.find("Mid")
        low_pos = result.context_markdown.find("Low")
        assert high_pos < mid_pos < low_pos, (
            f"Expected High < Mid < Low, got positions: High={high_pos}, Mid={mid_pos}, Low={low_pos}"
        )

    @pytest.mark.asyncio
    async def test_limits_to_max_patterns(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that handler limits to max_patterns from config.

        Note: OMN-1671 added domain caps (max_per_domain). To test
        max_patterns_per_injection, we use different domains.
        """
        # Create many patterns with different domains to avoid domain cap
        domains = ["testing", "code_review", "debugging", "documentation", "security"]
        patterns = [
            {
                **SAMPLE_PATTERN_1,
                "pattern_id": f"pat-{i}",
                "title": f"Pattern {i}",
                "domain": domains[i % len(domains)],  # Rotate through domains
            }
            for i in range(10)
        ]
        patterns_data = {**SAMPLE_PATTERN_FILE, "patterns": patterns}
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        # Config with max_patterns=3 via limits
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        limits = InjectionLimitsConfig(
            max_patterns_per_injection=3,
            max_per_domain=10,  # High enough to not trigger
        )
        config = ContextInjectionConfig(
            enabled=True,
            min_confidence=0.0,
            db_enabled=False,  # Use file-based loading for tests
            limits=limits,
        )
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should only have 3 patterns
        assert result.pattern_count == 3

    @pytest.mark.asyncio
    async def test_filters_by_domain(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that handler filters by domain when specified."""
        # SAMPLE_PATTERN_1 has domain="testing"
        # SAMPLE_PATTERN_2 has domain="code_review"
        result = await handler.handle(
            project_root=str(temp_project_dir),
            agent_domain="testing",
            emit_event=False,
        )

        # Should only include testing domain
        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown
        assert "Test Pattern 2" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_domain_filter_includes_general(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that domain filter includes 'general' domain patterns."""
        # Use predefined general domain pattern constant
        patterns_data = {
            **SAMPLE_PATTERN_FILE,
            "patterns": [SAMPLE_PATTERN_1, SAMPLE_GENERAL_DOMAIN_PATTERN],
        }
        with pattern_file.open("w") as f:
            json.dump(patterns_data, f)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            agent_domain="testing",
            emit_event=False,
        )

        # Should include both testing and general domain
        assert result.pattern_count == 2
        assert "Test Pattern 1" in result.context_markdown
        assert "General Pattern" in result.context_markdown

    @pytest.mark.asyncio
    async def test_no_pattern_file(
        self,
        handler: HandlerContextInjection,
        tmp_path: Path,
    ) -> None:
        """Test handling when no pattern file exists."""
        result = await handler.handle(
            project_root=str(tmp_path),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 0
        assert result.source == "none"

    @pytest.mark.asyncio
    async def test_malformed_json(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
    ) -> None:
        """Test handling malformed JSON file."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            f.write("{ invalid json }")

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_deduplication_by_pattern_id(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should deduplicate - only 1 pattern with pat-001 ID
        assert result.pattern_count == 1
        # Keeps first occurrence, not the duplicate
        assert "Test Pattern 1" in result.context_markdown

    @pytest.mark.asyncio
    async def test_retrieval_ms_is_measured(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that retrieval_ms is populated."""
        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # retrieval_ms should be set (usually 0-5ms for local file)
        assert result.retrieval_ms >= 0

    @pytest.mark.asyncio
    async def test_context_markdown_format(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that context_markdown has expected format."""
        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should have markdown header
        assert "## Learned Patterns (Auto-Injected)" in result.context_markdown
        # Should have pattern title
        assert "### Test Pattern 1" in result.context_markdown
        # Should have domain info
        assert "**Domain**: testing" in result.context_markdown
        # Should have confidence percentage
        assert "**Confidence**: 90%" in result.context_markdown

    @pytest.mark.asyncio
    async def test_disabled_config_returns_empty(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test that disabled config returns empty result."""
        config = ContextInjectionConfig(enabled=False)
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 0
        assert result.context_markdown == ""
        assert result.source == "disabled"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_patterns_array(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
    ) -> None:
        """Test handling empty patterns array."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": []}, f)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_invalid_pattern_skipped(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with only valid pattern
        assert result.success is True
        assert result.pattern_count == 1

    @pytest.mark.asyncio
    async def test_none_project_root(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test with None project root.

        With isolated_home fixture, user-level patterns are isolated,
        so this test reliably returns 0 patterns (no user patterns exist).
        """
        result = await handler.handle(
            project_root=None,
            emit_event=False,
        )

        # With isolated home directory, no patterns should be found
        assert result.success is True
        assert result.pattern_count == 0
        assert result.retrieval_ms >= 0

    @pytest.mark.asyncio
    async def test_nonexistent_project_path(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test with nonexistent project path."""
        result = await handler.handle(
            project_root="/nonexistent/path/that/does/not/exist",
            emit_event=False,
        )

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_patterns_not_a_list(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
    ) -> None:
        """Test handling when patterns is not a list."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump({"version": "1.0.0", "patterns": "not a list"}, f)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_file_not_json_object(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
    ) -> None:
        """Test handling when file is not a JSON object."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with pattern_path.open("w") as f:
            json.dump(["not", "an", "object"], f)

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_empty_file(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
    ) -> None:
        """Test handling empty file."""
        pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        pattern_path.write_text("")

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_pattern_with_missing_optional_field(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 1
        # No example reference means no "Example:" line in markdown
        assert "*Example:" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_pattern_with_wrong_type_confidence(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed with only valid pattern
        assert result.success is True
        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown


# =============================================================================
# Multiple Pattern Files Tests
# =============================================================================


class TestMultiplePatternFiles:
    """Test behavior with multiple pattern files."""

    @pytest.mark.asyncio
    async def test_deduplication_across_files(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        isolated_home: Path,
    ) -> None:
        """Test patterns are deduplicated when same ID appears in multiple files.

        With isolated_home fixture, we can safely test both project-level
        and user-level pattern file deduplication.
        """
        # Create project pattern file
        project_pattern_path = temp_project_dir / ".claude" / "learned_patterns.json"
        with project_pattern_path.open("w") as f:
            json.dump(
                {
                    "version": "1.0.0",
                    "patterns": [
                        {**SAMPLE_PATTERN_1},  # pat-001
                        {**SAMPLE_PATTERN_1, "pattern_id": "unique-project"},
                    ],
                },
                f,
            )

        # Create user-level pattern file with duplicate ID
        user_claude_dir = isolated_home / ".claude"
        user_claude_dir.mkdir()
        user_pattern_path = user_claude_dir / "learned_patterns.json"
        with user_pattern_path.open("w") as f:
            json.dump(
                {
                    "version": "1.0.0",
                    "patterns": [
                        {**SAMPLE_PATTERN_1},  # Same pat-001 (should be deduplicated)
                        {**SAMPLE_PATTERN_2},  # Different ID (pat-002)
                    ],
                },
                f,
            )

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should have 3 unique patterns:
        # - pat-001 (from project, first occurrence)
        # - unique-project (from project)
        # - pat-002 (from user-level)
        # The duplicate pat-001 from user-level should be deduplicated
        assert result.success is True
        assert result.pattern_count == 3


# =============================================================================
# Source Path Tests
# =============================================================================


class TestSourcePath:
    """Test source path reporting."""

    @pytest.mark.asyncio
    async def test_source_contains_pattern_file_path(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test source field contains the pattern file path."""
        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.source == str(pattern_file)

    @pytest.mark.asyncio
    async def test_source_is_none_when_no_files(
        self,
        handler: HandlerContextInjection,
        tmp_path: Path,
    ) -> None:
        """Test source is 'none' when no pattern files exist."""
        result = await handler.handle(
            project_root=str(tmp_path),
            emit_event=False,
        )

        assert result.source == "none"


# =============================================================================
# Async Behavior Tests
# =============================================================================


class TestAsyncBehavior:
    """Test async execution behavior."""

    @pytest.mark.asyncio
    async def test_handle_is_async(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test handle is an async coroutine."""
        import inspect

        assert inspect.iscoroutinefunction(handler.handle)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_calls(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test multiple concurrent handle calls work correctly."""
        import asyncio

        # Execute multiple concurrent calls
        results = await asyncio.gather(
            handler.handle(project_root=str(temp_project_dir), emit_event=False),
            handler.handle(project_root=str(temp_project_dir), emit_event=False),
            handler.handle(project_root=str(temp_project_dir), emit_event=False),
        )

        # All should succeed with same patterns
        for result in results:
            assert result.success is True
            assert result.pattern_count == 2


# =============================================================================
# Pattern File Structure Tests
# =============================================================================


class TestPatternFileStructure:
    """Test handling of various pattern file structures."""

    @pytest.mark.asyncio
    async def test_extra_fields_in_pattern_file_ignored(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 1

    @pytest.mark.asyncio
    async def test_extra_fields_in_pattern_record_preserved(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed - extra fields are simply not included in the record
        assert result.success is True
        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown

    @pytest.mark.asyncio
    async def test_pattern_with_numeric_string_confidence(
        self,
        handler: HandlerContextInjection,
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

        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Should succeed - float() handles string conversion
        assert result.success is True
        assert result.pattern_count == 1
        # 85% confidence
        assert "**Confidence**: 85%" in result.context_markdown


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Test inject_patterns convenience function."""

    @pytest.mark.asyncio
    async def test_inject_patterns_function(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns convenience function."""
        result = await inject_patterns(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_inject_patterns_with_session_start_context(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns accepts session_start injection_context.

        Part of OMN-1675: SessionStart pattern injection.
        """
        from omniclaude.hooks.models_injection_tracking import EnumInjectionContext

        result = await inject_patterns(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
            injection_context=EnumInjectionContext.SESSION_START,
        )

        # Should succeed (patterns loaded from file)
        assert result.success is True
        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_inject_patterns_with_domain(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns with domain filter."""
        result = await inject_patterns(
            project_root=str(temp_project_dir),
            agent_domain="testing",
            config=permissive_config,
            emit_event=False,
        )

        # Should only include testing domain
        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown


# =============================================================================
# Context Size Tests
# =============================================================================


class TestContextSize:
    """Test context size calculation."""

    @pytest.mark.asyncio
    async def test_context_size_bytes_calculated(
        self,
        handler: HandlerContextInjection,
        temp_project_dir: Path,
        pattern_file: Path,
    ) -> None:
        """Test context_size_bytes is calculated correctly."""
        result = await handler.handle(
            project_root=str(temp_project_dir),
            emit_event=False,
        )

        # Size should match the UTF-8 encoded length of the markdown
        expected_size = len(result.context_markdown.encode("utf-8"))
        assert result.context_size_bytes == expected_size

    @pytest.mark.asyncio
    async def test_empty_result_has_zero_size(
        self,
        handler: HandlerContextInjection,
        tmp_path: Path,
    ) -> None:
        """Test empty result has zero context size."""
        result = await handler.handle(
            project_root=str(tmp_path),
            emit_event=False,
        )

        assert result.context_size_bytes == 0
        assert result.context_markdown == ""


# =============================================================================
# Sync Wrapper Tests
# =============================================================================


class TestInjectPatternsSync:
    """Test inject_patterns_sync convenience function.

    This function wraps the async inject_patterns() for use in synchronous
    contexts (e.g., shell scripts). It handles event loop detection:
    - If no loop is running: uses asyncio.run() directly
    - If a loop is running: uses ThreadPoolExecutor to avoid nested loop error
    """

    def test_sync_from_sync_context(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync works from synchronous context.

        When called outside any async context, asyncio.get_running_loop()
        raises RuntimeError, so the function uses asyncio.run() directly.
        """
        result = inject_patterns_sync(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        assert isinstance(result, ModelInjectionResult)
        assert result.success is True
        assert result.pattern_count == 2

    def test_sync_returns_correct_type(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync returns ModelInjectionResult."""
        result = inject_patterns_sync(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        assert isinstance(result, ModelInjectionResult)
        assert hasattr(result, "success")
        assert hasattr(result, "context_markdown")
        assert hasattr(result, "pattern_count")
        assert hasattr(result, "context_size_bytes")
        assert hasattr(result, "source")
        assert hasattr(result, "retrieval_ms")

    def test_sync_no_patterns_graceful(
        self,
        tmp_path: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync handles missing patterns gracefully."""
        result = inject_patterns_sync(
            project_root=str(tmp_path),
            config=permissive_config,
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 0
        assert result.context_markdown == ""

    def test_sync_with_domain_filter(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync applies domain filter correctly."""
        result = inject_patterns_sync(
            project_root=str(temp_project_dir),
            agent_domain="testing",
            config=permissive_config,
            emit_event=False,
        )

        # Should only include testing domain pattern
        assert result.success is True
        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown

    @pytest.mark.asyncio
    async def test_sync_from_async_context(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync works when called from async context.

        When called inside an async context (loop is running),
        asyncio.get_running_loop() succeeds, so the function uses
        ThreadPoolExecutor to run asyncio.run() in a separate thread.
        This avoids the 'This event loop is already running' error.
        """
        import asyncio

        # Verify we're in async context
        loop = asyncio.get_running_loop()
        assert loop is not None

        # Call sync function from async context
        result = inject_patterns_sync(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        assert isinstance(result, ModelInjectionResult)
        assert result.success is True
        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_sync_matches_async_result(
        self,
        temp_project_dir: Path,
        pattern_file: Path,
        permissive_config: ContextInjectionConfig,
    ) -> None:
        """Test inject_patterns_sync returns same result as inject_patterns.

        The sync wrapper should produce identical results to the async
        version (aside from timing which may vary slightly).
        """
        # Get async result
        async_result = await inject_patterns(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        # Get sync result (called from async context uses thread pool)
        sync_result = inject_patterns_sync(
            project_root=str(temp_project_dir),
            config=permissive_config,
            emit_event=False,
        )

        # Compare results (exclude retrieval_ms which may vary)
        assert sync_result.success == async_result.success
        assert sync_result.pattern_count == async_result.pattern_count
        assert sync_result.context_markdown == async_result.context_markdown
        assert sync_result.context_size_bytes == async_result.context_size_bytes
        assert sync_result.source == async_result.source
