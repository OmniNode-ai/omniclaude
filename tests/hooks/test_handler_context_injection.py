# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for HandlerContextInjection.

Tests verify the handler:
1. Loads patterns from database (mocked)
2. Filters by domain when specified
3. Filters by confidence threshold (default 0.7)
4. Sorts by effective score descending
5. Limits to max_patterns (default 5)
6. Handles DB failures gracefully
7. Uses async properly

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelInjectionResult,
    ModelLoadPatternsResult,
    ModelPatternRecord,
    PatternPersistenceError,
    inject_patterns_sync,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test Data - Module-level constants for reference
# =============================================================================

SAMPLE_PATTERN_1 = ModelPatternRecord(
    pattern_id="pat-001",
    domain="testing",
    title="Test Pattern 1",
    description="Description for pattern 1",
    confidence=0.9,
    usage_count=10,
    success_rate=0.85,
    example_reference="src/test.py:42",
)

SAMPLE_PATTERN_2 = ModelPatternRecord(
    pattern_id="pat-002",
    domain="code_review",
    title="Test Pattern 2",
    description="Description for pattern 2",
    confidence=0.8,
    usage_count=5,
    success_rate=0.80,
)

# Low confidence pattern (below default 0.7 threshold)
SAMPLE_LOW_CONFIDENCE_PATTERN = ModelPatternRecord(
    pattern_id="pat-low",
    domain="testing",
    title="Low Confidence Pattern",
    description="Pattern with low confidence",
    confidence=0.5,
    usage_count=2,
    success_rate=0.60,
)

# General domain pattern (included in all domain filters)
SAMPLE_GENERAL_DOMAIN_PATTERN = ModelPatternRecord(
    pattern_id="pat-general",
    domain="general",
    title="General Pattern",
    description="Pattern applicable to all domains",
    confidence=0.85,
    usage_count=20,
    success_rate=0.90,
)

TWO_STANDARD_PATTERNS = [SAMPLE_PATTERN_1, SAMPLE_PATTERN_2]


# =============================================================================
# Fixtures
# =============================================================================


# Type alias for the handler factory
HandlerFactory = Callable[..., HandlerContextInjection]


@pytest.fixture
def handler_with_patterns() -> HandlerFactory:
    """Create handler that returns patterns from mock DB.

    Returns a factory function that creates a handler with mocked
    _load_patterns_from_database. Patterns are passed directly,
    avoiding the need for actual DB or file fixtures.
    """

    def _factory(
        patterns: list[ModelPatternRecord],
        **config_kwargs: Any,
    ) -> HandlerContextInjection:
        config_kwargs.setdefault("enabled", True)
        config_kwargs.setdefault("db_enabled", True)
        config = ContextInjectionConfig(**config_kwargs)
        handler = HandlerContextInjection(config=config)

        async def mock_load(
            domain: str | None = None,
            project_scope: str | None = None,
        ) -> ModelLoadPatternsResult:
            return ModelLoadPatternsResult(
                patterns=list(patterns),
                source_files=[Path("mock:test")],
            )

        handler._load_patterns_from_database = mock_load  # type: ignore[assignment]
        return handler

    return _factory


@pytest.fixture
def handler(handler_with_patterns: HandlerFactory) -> HandlerContextInjection:
    """Create a fresh handler with both standard patterns loaded."""
    return handler_with_patterns(TWO_STANDARD_PATTERNS, min_confidence=0.0)


@pytest.fixture
def default_handler(handler_with_patterns: HandlerFactory) -> HandlerContextInjection:
    """Create a handler with default config (min_confidence=0.7)."""
    return handler_with_patterns(TWO_STANDARD_PATTERNS)


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
    async def test_load_patterns_from_db(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test loading patterns via mocked database."""
        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 2
        assert result.retrieval_ms >= 0
        assert "mock:test" in result.source

    @pytest.mark.asyncio
    async def test_filters_by_confidence_threshold(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test that handler filters patterns by confidence threshold."""
        # Default config has min_confidence=0.7
        handler = handler_with_patterns(
            [SAMPLE_PATTERN_1, SAMPLE_LOW_CONFIDENCE_PATTERN],
        )

        result = await handler.handle(emit_event=False)

        # Handler should filter out low confidence pattern (0.5 < 0.7)
        assert result.pattern_count == 1
        # High confidence pattern (0.9) should be included
        assert "Test Pattern 1" in result.context_markdown

    @pytest.mark.asyncio
    async def test_sorts_by_effective_score_descending(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test that handler sorts patterns by effective_score descending.

        Note: OMN-1671 changed sorting from pure confidence to effective_score,
        which is: confidence * success_rate * f(usage_count).
        """
        patterns = [
            ModelPatternRecord(
                pattern_id="low",
                domain="debugging",
                title="Low",
                description="Low score",
                confidence=0.75,
                success_rate=0.5,
                usage_count=5,
            ),
            ModelPatternRecord(
                pattern_id="high",
                domain="testing",
                title="High",
                description="High score",
                confidence=0.95,
                success_rate=0.9,
                usage_count=20,
            ),
            ModelPatternRecord(
                pattern_id="mid",
                domain="code_review",
                title="Mid",
                description="Mid score",
                confidence=0.85,
                success_rate=0.7,
                usage_count=10,
            ),
        ]
        handler = handler_with_patterns(patterns, min_confidence=0.0)

        result = await handler.handle(emit_event=False)

        # Handler sorts by effective_score descending
        high_pos = result.context_markdown.find("High")
        mid_pos = result.context_markdown.find("Mid")
        low_pos = result.context_markdown.find("Low")
        assert high_pos < mid_pos < low_pos, (
            f"Expected High < Mid < Low, got positions: High={high_pos}, Mid={mid_pos}, Low={low_pos}"
        )

    @pytest.mark.asyncio
    async def test_limits_to_max_patterns(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test that handler limits to max_patterns from config.

        Note: OMN-1671 added domain caps (max_per_domain). To test
        max_patterns_per_injection, we use different domains.
        """
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        domains = ["testing", "code_review", "debugging", "documentation", "security"]
        patterns = [
            ModelPatternRecord(
                pattern_id=f"pat-{i}",
                domain=domains[i % len(domains)],
                title=f"Pattern {i}",
                description=f"Description {i}",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
            )
            for i in range(10)
        ]

        limits = InjectionLimitsConfig(
            max_patterns_per_injection=3,
            max_per_domain=10,
        )
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)

        result = await handler.handle(emit_event=False)

        assert result.pattern_count == 3

    @pytest.mark.asyncio
    async def test_filters_by_domain(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test that handler filters by domain when specified."""
        result = await handler.handle(
            agent_domain="testing",
            emit_event=False,
        )

        assert result.pattern_count == 1
        assert "Test Pattern 1" in result.context_markdown
        assert "Test Pattern 2" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_domain_filter_includes_general(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test that domain filter includes 'general' domain patterns."""
        handler = handler_with_patterns(
            [SAMPLE_PATTERN_1, SAMPLE_GENERAL_DOMAIN_PATTERN],
            min_confidence=0.0,
        )

        result = await handler.handle(
            agent_domain="testing",
            emit_event=False,
        )

        assert result.pattern_count == 2
        assert "Test Pattern 1" in result.context_markdown
        assert "General Pattern" in result.context_markdown

    @pytest.mark.asyncio
    async def test_db_returns_empty(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test handling when database returns no patterns."""
        handler = handler_with_patterns([])

        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_db_failure_graceful(self) -> None:
        """Test handling when database query fails."""
        config = ContextInjectionConfig(enabled=True, db_enabled=True)
        handler = HandlerContextInjection(config=config)

        async def mock_load_raises(**kwargs: Any) -> ModelLoadPatternsResult:
            raise PatternPersistenceError("Connection failed")

        handler._load_patterns_from_database = mock_load_raises  # type: ignore[assignment]

        result = await handler.handle(emit_event=False)

        # Should succeed with empty patterns (graceful degradation)
        assert result.success is True
        assert result.pattern_count == 0

    @pytest.mark.asyncio
    async def test_retrieval_ms_is_measured(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test that retrieval_ms is populated."""
        result = await handler.handle(emit_event=False)

        assert result.retrieval_ms >= 0

    @pytest.mark.asyncio
    async def test_context_markdown_format(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test that context_markdown has expected format."""
        result = await handler.handle(emit_event=False)

        # Should have markdown header
        assert "## Learned Patterns (Auto-Injected)" in result.context_markdown
        # Should have pattern title
        assert "### Test Pattern 1" in result.context_markdown
        # Should have domain info
        assert "**Domain**: testing" in result.context_markdown
        # Should have confidence percentage
        assert "**Confidence**: 90%" in result.context_markdown

    @pytest.mark.asyncio
    async def test_disabled_config_returns_empty(self) -> None:
        """Test that disabled config returns empty result."""
        config = ContextInjectionConfig(enabled=False)
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 0
        assert result.context_markdown == ""
        assert result.source == "disabled"

    @pytest.mark.asyncio
    async def test_pattern_without_example_reference(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test pattern without optional example_reference field."""
        pattern = ModelPatternRecord(
            pattern_id="no-ref",
            domain="testing",
            title="No Reference",
            description="Pattern without example reference",
            confidence=0.8,
            usage_count=3,
            success_rate=0.75,
        )
        handler = handler_with_patterns([pattern], min_confidence=0.0)

        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 1
        assert "*Example:" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_db_disabled_returns_empty(self) -> None:
        """Test that db_enabled=False returns empty (no file fallback)."""
        config = ContextInjectionConfig(enabled=True, db_enabled=False)
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 0
        assert result.source == "none"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_none_project_root(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test with None project root (mock DB still works)."""
        result = await handler.handle(
            project_root=None,
            emit_event=False,
        )

        assert result.success is True
        assert result.pattern_count == 2
        assert result.retrieval_ms >= 0


# =============================================================================
# Source Path Tests
# =============================================================================


class TestSourcePath:
    """Test source path reporting."""

    @pytest.mark.asyncio
    async def test_source_contains_db_attribution(
        self,
        handler: HandlerContextInjection,
    ) -> None:
        """Test source field contains the mock source path."""
        result = await handler.handle(emit_event=False)

        assert result.source == "mock:test"

    @pytest.mark.asyncio
    async def test_source_is_none_when_db_disabled(self) -> None:
        """Test source is 'none' when db_enabled=False."""
        config = ContextInjectionConfig(enabled=True, db_enabled=False)
        handler = HandlerContextInjection(config=config)

        result = await handler.handle(emit_event=False)

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
    ) -> None:
        """Test multiple concurrent handle calls work correctly."""
        import asyncio

        results = await asyncio.gather(
            handler.handle(emit_event=False),
            handler.handle(emit_event=False),
            handler.handle(emit_event=False),
        )

        for result in results:
            assert result.success is True
            assert result.pattern_count == 2


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Test inject_patterns convenience function."""

    @pytest.mark.asyncio
    async def test_inject_patterns_function(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test inject_patterns convenience function with mocked handler."""
        # inject_patterns creates its own handler, so we test via the handler directly
        handler = handler_with_patterns(TWO_STANDARD_PATTERNS, min_confidence=0.0)
        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_inject_patterns_with_session_start_context(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test inject_patterns accepts session_start injection_context.

        Part of OMN-1675: SessionStart pattern injection.
        """
        from omniclaude.hooks.models_injection_tracking import EnumInjectionContext

        handler = handler_with_patterns(TWO_STANDARD_PATTERNS, min_confidence=0.0)
        result = await handler.handle(
            emit_event=False,
            injection_context=EnumInjectionContext.SESSION_START,
        )

        assert result.success is True
        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_inject_patterns_with_domain(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test inject_patterns with domain filter."""
        handler = handler_with_patterns(TWO_STANDARD_PATTERNS, min_confidence=0.0)
        result = await handler.handle(
            agent_domain="testing",
            emit_event=False,
        )

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
    ) -> None:
        """Test context_size_bytes is calculated correctly."""
        result = await handler.handle(emit_event=False)

        expected_size = len(result.context_markdown.encode("utf-8"))
        assert result.context_size_bytes == expected_size

    @pytest.mark.asyncio
    async def test_empty_result_has_zero_size(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test empty result has zero context size."""
        handler = handler_with_patterns([])

        result = await handler.handle(emit_event=False)

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

    Note: inject_patterns_sync creates its own handler internally,
    so we test with db_enabled=False (no patterns, graceful empty result).
    """

    def test_sync_from_sync_context(self) -> None:
        """Test inject_patterns_sync works from synchronous context."""
        config = ContextInjectionConfig(
            enabled=True, db_enabled=False, min_confidence=0.0
        )
        result = inject_patterns_sync(config=config, emit_event=False)

        assert isinstance(result, ModelInjectionResult)
        assert result.success is True

    def test_sync_returns_correct_type(self) -> None:
        """Test inject_patterns_sync returns ModelInjectionResult."""
        config = ContextInjectionConfig(
            enabled=True, db_enabled=False, min_confidence=0.0
        )
        result = inject_patterns_sync(config=config, emit_event=False)

        assert isinstance(result, ModelInjectionResult)
        assert hasattr(result, "success")
        assert hasattr(result, "context_markdown")
        assert hasattr(result, "pattern_count")
        assert hasattr(result, "context_size_bytes")
        assert hasattr(result, "source")
        assert hasattr(result, "retrieval_ms")

    def test_sync_no_patterns_graceful(self) -> None:
        """Test inject_patterns_sync handles missing patterns gracefully."""
        config = ContextInjectionConfig(
            enabled=True, db_enabled=False, min_confidence=0.0
        )
        result = inject_patterns_sync(config=config, emit_event=False)

        assert result.success is True
        assert result.pattern_count == 0
        assert result.context_markdown == ""

    @pytest.mark.asyncio
    async def test_sync_from_async_context(self) -> None:
        """Test inject_patterns_sync works when called from async context."""
        import asyncio

        loop = asyncio.get_running_loop()
        assert loop is not None

        config = ContextInjectionConfig(
            enabled=True, db_enabled=False, min_confidence=0.0
        )
        result = inject_patterns_sync(config=config, emit_event=False)

        assert isinstance(result, ModelInjectionResult)
        assert result.success is True


# =============================================================================
# Evidence Tier Tests (OMN-2044)
# =============================================================================


class TestEvidenceTier:
    """Test evidence_tier field on PatternRecord and related behavior."""

    def test_pattern_record_with_evidence_tier(self) -> None:
        """Test PatternRecord with evidence_tier constructs correctly."""
        record = ModelPatternRecord(
            pattern_id="et-001",
            domain="testing",
            title="Measured Pattern",
            description="A pattern with measurement data",
            confidence=0.9,
            usage_count=10,
            success_rate=0.85,
            evidence_tier="MEASURED",
        )
        assert record.evidence_tier == "MEASURED"

    def test_pattern_record_evidence_tier_default_none(self) -> None:
        """Test PatternRecord defaults evidence_tier to None."""
        record = ModelPatternRecord(
            pattern_id="et-002",
            domain="testing",
            title="Default Tier Pattern",
            description="No tier specified",
            confidence=0.9,
            usage_count=10,
            success_rate=0.85,
        )
        assert record.evidence_tier is None

    def test_pattern_record_all_valid_evidence_tiers(self) -> None:
        """Test all valid evidence_tier values are accepted."""
        for tier in ("UNMEASURED", "MEASURED", "VERIFIED", None):
            record = ModelPatternRecord(
                pattern_id=f"et-{tier}",
                domain="testing",
                title="Test",
                description="Desc",
                confidence=0.5,
                usage_count=1,
                success_rate=0.5,
                evidence_tier=tier,
            )
            assert record.evidence_tier == tier

    def test_pattern_record_invalid_evidence_tier(self) -> None:
        """Test PatternRecord rejects invalid evidence_tier values."""
        with pytest.raises(ValueError, match="evidence_tier must be one of"):
            ModelPatternRecord(
                pattern_id="et-bad",
                domain="testing",
                title="Test",
                description="Desc",
                confidence=0.5,
                usage_count=1,
                success_rate=0.5,
                evidence_tier="INVALID",
            )

    @pytest.mark.asyncio
    async def test_markdown_badge_measured(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test markdown output includes [Measured] badge for MEASURED patterns."""
        patterns = [
            ModelPatternRecord(
                pattern_id="badge-measured",
                domain="testing",
                title="Measured Test Pattern",
                description="Has measurement data",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="MEASURED",
            ),
        ]
        handler = handler_with_patterns(patterns, min_confidence=0.0)
        result = await handler.handle(emit_event=False)

        assert "[Measured]" in result.context_markdown
        assert "Measured Test Pattern" in result.context_markdown

    @pytest.mark.asyncio
    async def test_markdown_badge_verified(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test markdown output includes [Verified] badge for VERIFIED patterns."""
        patterns = [
            ModelPatternRecord(
                pattern_id="badge-verified",
                domain="testing",
                title="Verified Test Pattern",
                description="Has been verified",
                confidence=0.95,
                usage_count=20,
                success_rate=0.95,
                evidence_tier="VERIFIED",
            ),
        ]
        handler = handler_with_patterns(patterns, min_confidence=0.0)
        result = await handler.handle(emit_event=False)

        assert "[Verified]" in result.context_markdown
        assert "Verified Test Pattern" in result.context_markdown

    @pytest.mark.asyncio
    async def test_markdown_no_badge_unmeasured(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test markdown output shows no badge for UNMEASURED patterns."""
        patterns = [
            ModelPatternRecord(
                pattern_id="badge-unmeasured",
                domain="testing",
                title="Unmeasured Test Pattern",
                description="No measurement data",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="UNMEASURED",
            ),
        ]
        handler = handler_with_patterns(patterns, min_confidence=0.0)
        result = await handler.handle(emit_event=False)

        assert "[Measured]" not in result.context_markdown
        assert "[Verified]" not in result.context_markdown
        assert "Unmeasured Test Pattern" in result.context_markdown

    @pytest.mark.asyncio
    async def test_markdown_no_badge_none_tier(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test markdown output shows no badge when evidence_tier is None."""
        patterns = [
            ModelPatternRecord(
                pattern_id="badge-none",
                domain="testing",
                title="None Tier Pattern",
                description="No tier specified",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier=None,
            ),
        ]
        handler = handler_with_patterns(patterns, min_confidence=0.0)
        result = await handler.handle(emit_event=False)

        assert "[Measured]" not in result.context_markdown
        assert "[Verified]" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_require_measured_filters_unmeasured(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test require_measured=True filters out UNMEASURED patterns."""
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        patterns = [
            ModelPatternRecord(
                pattern_id="rm-unmeasured",
                domain="testing",
                title="Unmeasured",
                description="Should be filtered",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="UNMEASURED",
            ),
            ModelPatternRecord(
                pattern_id="rm-measured",
                domain="code_review",
                title="Measured",
                description="Should pass filter",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="MEASURED",
            ),
            ModelPatternRecord(
                pattern_id="rm-verified",
                domain="debugging",
                title="Verified",
                description="Should pass filter",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="VERIFIED",
            ),
        ]
        limits = InjectionLimitsConfig(require_measured=True)
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)
        result = await handler.handle(emit_event=False)

        assert result.pattern_count == 2
        assert "Unmeasured" not in result.context_markdown
        assert "Measured" in result.context_markdown
        assert "Verified" in result.context_markdown

    @pytest.mark.asyncio
    async def test_require_measured_false_passes_all(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test require_measured=False (default) passes all patterns."""
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        patterns = [
            ModelPatternRecord(
                pattern_id="rf-unmeasured",
                domain="testing",
                title="Unmeasured",
                description="Should pass",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="UNMEASURED",
            ),
            ModelPatternRecord(
                pattern_id="rf-measured",
                domain="code_review",
                title="Measured",
                description="Should pass",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="MEASURED",
            ),
        ]
        limits = InjectionLimitsConfig(require_measured=False)
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)
        result = await handler.handle(emit_event=False)

        assert result.pattern_count == 2

    @pytest.mark.asyncio
    async def test_require_measured_filters_none_tier(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test require_measured=True also filters out None evidence_tier."""
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        patterns = [
            ModelPatternRecord(
                pattern_id="rf-none",
                domain="testing",
                title="None Tier",
                description="Should be filtered",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier=None,
            ),
            ModelPatternRecord(
                pattern_id="rf-verified",
                domain="code_review",
                title="Verified",
                description="Should pass",
                confidence=0.9,
                usage_count=10,
                success_rate=0.85,
                evidence_tier="VERIFIED",
            ),
        ]
        limits = InjectionLimitsConfig(require_measured=True)
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)
        result = await handler.handle(emit_event=False)

        assert result.pattern_count == 1
        assert "None Tier" not in result.context_markdown
        assert "Verified" in result.context_markdown

    @pytest.mark.asyncio
    async def test_markdown_combined_provisional_and_measured(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test combined [Provisional] [Measured] badges on a single pattern."""
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        patterns = [
            ModelPatternRecord(
                pattern_id="combo-prov-meas",
                domain="testing",
                title="Combined Badge Pattern",
                description="Provisional pattern with measurement data",
                confidence=0.8,
                usage_count=10,
                success_rate=0.75,
                lifecycle_state="provisional",
                evidence_tier="MEASURED",
            ),
        ]
        limits = InjectionLimitsConfig(include_provisional=True)
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)
        result = await handler.handle(emit_event=False)

        assert "[Provisional]" in result.context_markdown
        assert "[Measured]" in result.context_markdown
        assert (
            "Combined Badge Pattern [Provisional] [Measured]" in result.context_markdown
        )

    @pytest.mark.asyncio
    async def test_markdown_combined_provisional_and_verified(
        self,
        handler_with_patterns: HandlerFactory,
    ) -> None:
        """Test combined [Provisional] [Verified] badges on a single pattern."""
        from omniclaude.hooks.injection_limits import InjectionLimitsConfig

        patterns = [
            ModelPatternRecord(
                pattern_id="combo-prov-ver",
                domain="testing",
                title="Provisional Verified Pattern",
                description="Provisional pattern that has been verified",
                confidence=0.85,
                usage_count=15,
                success_rate=0.8,
                lifecycle_state="provisional",
                evidence_tier="VERIFIED",
            ),
        ]
        limits = InjectionLimitsConfig(include_provisional=True)
        handler = handler_with_patterns(patterns, min_confidence=0.0, limits=limits)
        result = await handler.handle(emit_event=False)

        assert "[Provisional]" in result.context_markdown
        assert "[Verified]" in result.context_markdown
        assert (
            "Provisional Verified Pattern [Provisional] [Verified]"
            in result.context_markdown
        )
