# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for OMN-2042: Graduated Injection Policy.

Tests verify:
1. PatternRecord with lifecycle_state constructs correctly
2. Effective score is dampened for provisional patterns
3. Markdown output includes [Provisional] annotation
4. Mixed validated/provisional - validated always preferred in selection
5. max_provisional cap is enforced when set
6. include_provisional=False (default) backward compatibility
7. Sync test: PatternRecord matches in both locations

Part of OMN-2042: Graduated Injection Policy - lifecycle-state-aware pattern selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelLoadPatternsResult,
    ModelPatternRecord,
)
from omniclaude.hooks.injection_limits import (
    InjectionLimitsConfig,
    compute_effective_score,
    render_single_pattern,
    select_patterns_for_injection,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test Data
# =============================================================================


@dataclass(frozen=True)
class MockPatternRecord:
    """Mock PatternRecord with lifecycle_state and evidence_tier for testing."""

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None
    lifecycle_state: str | None = None
    evidence_tier: str | None = None


def make_pattern(
    pattern_id: str = "pat-001",
    domain: str = "testing",
    title: str = "Test Pattern",
    description: str = "A test pattern description",
    confidence: float = 0.9,
    usage_count: int = 10,
    success_rate: float = 0.8,
    example_reference: str | None = None,
    lifecycle_state: str | None = None,
) -> MockPatternRecord:
    """Create a mock pattern with defaults."""
    return MockPatternRecord(
        pattern_id=pattern_id,
        domain=domain,
        title=title,
        description=description,
        confidence=confidence,
        usage_count=usage_count,
        success_rate=success_rate,
        example_reference=example_reference,
        lifecycle_state=lifecycle_state,
    )


# =============================================================================
# PatternRecord lifecycle_state Tests
# =============================================================================


class TestPatternRecordLifecycleState:
    """Test PatternRecord with lifecycle_state field."""

    def test_construct_with_lifecycle_state_validated(self) -> None:
        """PatternRecord constructs with lifecycle_state='validated'."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        record = PatternRecord(
            pattern_id="test-001",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
            lifecycle_state="validated",
        )
        assert record.lifecycle_state == "validated"

    def test_construct_with_lifecycle_state_provisional(self) -> None:
        """PatternRecord constructs with lifecycle_state='provisional'."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        record = PatternRecord(
            pattern_id="test-002",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.7,
            usage_count=5,
            success_rate=0.6,
            lifecycle_state="provisional",
        )
        assert record.lifecycle_state == "provisional"

    def test_construct_without_lifecycle_state_defaults_none(self) -> None:
        """PatternRecord defaults lifecycle_state to None (backward compat)."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        record = PatternRecord(
            pattern_id="test-003",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
        )
        assert record.lifecycle_state is None

    def test_lifecycle_state_is_frozen(self) -> None:
        """lifecycle_state cannot be modified after creation (frozen dataclass)."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        record = PatternRecord(
            pattern_id="test-004",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
            lifecycle_state="validated",
        )
        with pytest.raises(Exception):
            record.lifecycle_state = "provisional"  # type: ignore[misc]

    def test_invalid_lifecycle_state_raises_value_error(self) -> None:
        """PatternRecord rejects invalid lifecycle_state values."""
        from omniclaude.hooks.handler_context_injection import PatternRecord

        with pytest.raises(ValueError, match="lifecycle_state must be one of"):
            PatternRecord(
                pattern_id="test-bad",
                domain="testing",
                title="Test",
                description="Desc",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="unknown",
            )

    def test_cli_pattern_record_has_lifecycle_state(self) -> None:
        """CLI PatternRecord also has lifecycle_state field."""
        from plugins.onex.hooks.lib.pattern_types import PatternRecord as CLIRecord

        record = CLIRecord(
            pattern_id="test-005",
            domain="testing",
            title="Test",
            description="Desc",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
            lifecycle_state="provisional",
        )
        assert record.lifecycle_state == "provisional"


# =============================================================================
# Effective Score Dampening Tests
# =============================================================================


class TestProvisionalDampening:
    """Test that provisional patterns get dampened scores."""

    def test_validated_no_dampening(self) -> None:
        """Validated patterns are not dampened."""
        score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state="validated",
            provisional_dampening=0.5,
        )
        # Same as without lifecycle_state
        score_none = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state=None,
            provisional_dampening=0.5,
        )
        assert score == score_none

    def test_provisional_dampened_by_factor(self) -> None:
        """Provisional patterns are dampened by the provisional_dampening factor."""
        base_score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
        )
        dampened_score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state="provisional",
            provisional_dampening=0.5,
        )
        assert dampened_score == pytest.approx(base_score * 0.5, abs=1e-10)

    def test_provisional_dampening_zero_raises(self) -> None:
        """Provisional dampening of 0.0 raises ValueError (use include_provisional=False)."""
        with pytest.raises(ValueError, match=r"provisional_dampening must be > 0\.0"):
            compute_effective_score(
                confidence=0.9,
                success_rate=0.8,
                usage_count=10,
                lifecycle_state="provisional",
                provisional_dampening=0.0,
            )

    def test_provisional_dampening_one(self) -> None:
        """Provisional dampening of 1.0 produces no dampening."""
        base_score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
        )
        score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state="provisional",
            provisional_dampening=1.0,
        )
        assert score == base_score

    def test_default_dampening_halves_provisional_score(self) -> None:
        """Default provisional_dampening=0.5 halves score for provisional patterns."""
        score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state="provisional",
        )
        base_score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
        )
        # Default dampening is 0.5 (matches InjectionLimitsConfig default)
        assert score == pytest.approx(base_score * 0.5)

    def test_dampening_clamped_above_one(self) -> None:
        """Dampening > 1.0 is clamped to 1.0."""
        base_score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
        )
        score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=10,
            lifecycle_state="provisional",
            provisional_dampening=1.5,  # Should be clamped to 1.0
        )
        assert score == base_score


# =============================================================================
# Markdown [Provisional] Badge Tests
# =============================================================================


class TestProvisionalBadge:
    """Test [Provisional] badge in markdown output."""

    def test_provisional_badge_in_render(self) -> None:
        """render_single_pattern includes [Provisional] badge."""
        pattern = make_pattern(
            title="My Pattern",
            lifecycle_state="provisional",
        )
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern [Provisional]" in rendered

    def test_validated_no_badge(self) -> None:
        """Validated patterns do not get [Provisional] badge."""
        pattern = make_pattern(
            title="My Pattern",
            lifecycle_state="validated",
        )
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern" in rendered
        assert "[Provisional]" not in rendered

    def test_none_lifecycle_no_badge(self) -> None:
        """Patterns with lifecycle_state=None do not get badge."""
        pattern = make_pattern(
            title="My Pattern",
            lifecycle_state=None,
        )
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern" in rendered
        assert "[Provisional]" not in rendered

    def test_handler_format_provisional_badge(self) -> None:
        """Handler _format_patterns_markdown includes [Provisional] badge."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="prov-001",
            domain="testing",
            title="Provisional Pattern",
            description="A provisional pattern.",
            confidence=0.7,
            usage_count=5,
            success_rate=0.6,
            lifecycle_state="provisional",
        )

        handler = HandlerContextInjection()
        rendered = handler._format_patterns_markdown([pattern], max_patterns=5)
        assert "### Provisional Pattern [Provisional]" in rendered

    def test_handler_format_validated_no_badge(self) -> None:
        """Handler _format_patterns_markdown: validated patterns have no badge."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="val-001",
            domain="testing",
            title="Validated Pattern",
            description="A validated pattern.",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
            lifecycle_state="validated",
        )

        handler = HandlerContextInjection()
        rendered = handler._format_patterns_markdown([pattern], max_patterns=5)
        assert "### Validated Pattern" in rendered
        assert "[Provisional]" not in rendered

    def test_format_sync_provisional(self) -> None:
        """render_single_pattern and handler format match for provisional patterns."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="sync-prov-001",
            domain="testing",
            title="Sync Test Provisional",
            description="Verifying sync for provisional patterns.",
            confidence=0.75,
            usage_count=8,
            success_rate=0.7,
            lifecycle_state="provisional",
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Both should contain the [Provisional] badge
        assert "[Provisional]" in single_render
        assert "[Provisional]" in handler_render

        # Extract pattern portion from handler (skip header, strip separator)
        header_end = handler_render.find("### ")
        handler_pattern = handler_render[header_end:]

        single_stripped = single_render.rstrip()
        if single_stripped.endswith("---"):
            single_stripped = single_stripped[:-3].rstrip()

        handler_stripped = handler_pattern.rstrip()

        assert single_stripped == handler_stripped

    def test_format_sync_measured_badge(self) -> None:
        """render_single_pattern and handler format match for MEASURED patterns."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="sync-meas-001",
            domain="testing",
            title="Sync Test Measured",
            description="Verifying sync for measured patterns.",
            confidence=0.85,
            usage_count=12,
            success_rate=0.8,
            evidence_tier="MEASURED",
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Both should contain the [Measured] badge
        assert "[Measured]" in single_render
        assert "[Measured]" in handler_render

        # Extract pattern portion from handler (skip header, strip separator)
        header_end = handler_render.find("### ")
        handler_pattern_text = handler_render[header_end:]

        single_stripped = single_render.rstrip()
        if single_stripped.endswith("---"):
            single_stripped = single_stripped[:-3].rstrip()

        handler_stripped = handler_pattern_text.rstrip()

        assert single_stripped == handler_stripped

    def test_format_sync_verified_badge(self) -> None:
        """render_single_pattern and handler format match for VERIFIED patterns."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="sync-ver-001",
            domain="code_review",
            title="Sync Test Verified",
            description="Verifying sync for verified patterns.",
            confidence=0.95,
            usage_count=25,
            success_rate=0.92,
            evidence_tier="VERIFIED",
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Both should contain the [Verified] badge
        assert "[Verified]" in single_render
        assert "[Verified]" in handler_render

        # Extract pattern portion from handler (skip header, strip separator)
        header_end = handler_render.find("### ")
        handler_pattern_text = handler_render[header_end:]

        single_stripped = single_render.rstrip()
        if single_stripped.endswith("---"):
            single_stripped = single_stripped[:-3].rstrip()

        handler_stripped = handler_pattern_text.rstrip()

        assert single_stripped == handler_stripped

    def test_format_sync_combined_provisional_measured(self) -> None:
        """render_single_pattern and handler format match for provisional + measured."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="sync-combo-001",
            domain="testing",
            title="Sync Test Combined",
            description="Verifying sync for combined badges.",
            confidence=0.75,
            usage_count=8,
            success_rate=0.7,
            lifecycle_state="provisional",
            evidence_tier="MEASURED",
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Both should contain both badges
        assert "[Provisional]" in single_render
        assert "[Measured]" in single_render
        assert "[Provisional]" in handler_render
        assert "[Measured]" in handler_render

        # Extract pattern portion from handler (skip header, strip separator)
        header_end = handler_render.find("### ")
        handler_pattern_text = handler_render[header_end:]

        single_stripped = single_render.rstrip()
        if single_stripped.endswith("---"):
            single_stripped = single_stripped[:-3].rstrip()

        handler_stripped = handler_pattern_text.rstrip()

        assert single_stripped == handler_stripped


# =============================================================================
# Mixed Validated/Provisional Selection Tests
# =============================================================================


class TestMixedSelection:
    """Test that validated patterns are always preferred over provisional."""

    def test_validated_preferred_over_provisional(self) -> None:
        """Validated patterns rank higher than equivalent provisional patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=2,
            max_per_domain=10,
            max_tokens_injected=10000,
            include_provisional=True,
            provisional_dampening=0.5,
        )
        patterns = [
            make_pattern(
                pattern_id="prov-1",
                domain="testing",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="provisional",
            ),
            make_pattern(
                pattern_id="val-1",
                domain="code_review",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="validated",
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Validated should be first (undampened score > dampened score)
        assert result[0].pattern_id == "val-1"
        assert result[1].pattern_id == "prov-1"

    def test_mixed_selection_respects_all_limits(self) -> None:
        """Mixed selection still respects domain caps and token limits."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=5,
            max_per_domain=1,
            max_tokens_injected=10000,
            include_provisional=True,
            provisional_dampening=0.5,
        )
        patterns = [
            make_pattern(
                pattern_id="val-test-1",
                domain="testing",
                confidence=0.95,
                usage_count=20,
                success_rate=0.9,
                lifecycle_state="validated",
            ),
            make_pattern(
                pattern_id="prov-test-1",
                domain="testing",
                confidence=0.85,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="provisional",
            ),
            make_pattern(
                pattern_id="val-review-1",
                domain="code_review",
                confidence=0.90,
                usage_count=15,
                success_rate=0.85,
                lifecycle_state="validated",
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # max_per_domain=1: only 1 testing + 1 code_review
        assert len(result) == 2
        pattern_ids = [p.pattern_id for p in result]
        assert "val-test-1" in pattern_ids  # Highest testing score
        assert "val-review-1" in pattern_ids  # Only code_review
        assert "prov-test-1" not in pattern_ids  # Blocked by domain cap


# =============================================================================
# max_provisional Cap Tests
# =============================================================================


class TestMaxProvisionalCap:
    """Test max_provisional cap enforcement."""

    def test_max_provisional_caps_selection(self) -> None:
        """max_provisional limits the number of provisional patterns selected."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            include_provisional=True,
            provisional_dampening=0.8,  # Mild dampening
            max_provisional=1,
        )
        patterns = [
            make_pattern(
                pattern_id="val-1",
                domain="testing",
                confidence=0.95,
                usage_count=20,
                success_rate=0.9,
                lifecycle_state="validated",
            ),
            make_pattern(
                pattern_id="prov-1",
                domain="code_review",
                confidence=0.85,
                usage_count=15,
                success_rate=0.8,
                lifecycle_state="provisional",
            ),
            make_pattern(
                pattern_id="prov-2",
                domain="debugging",
                confidence=0.80,
                usage_count=12,
                success_rate=0.75,
                lifecycle_state="provisional",
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Should include val-1 + 1 provisional (max_provisional=1)
        provisional_selected = [
            p for p in result if getattr(p, "lifecycle_state", None) == "provisional"
        ]
        assert len(provisional_selected) == 1
        # Total should be 2 (1 validated + 1 provisional)
        assert len(result) == 2

    def test_max_provisional_none_means_no_cap(self) -> None:
        """max_provisional=None allows unlimited provisional patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            include_provisional=True,
            provisional_dampening=0.8,
            max_provisional=None,
        )
        patterns = [
            make_pattern(
                pattern_id=f"prov-{i}",
                domain=f"domain-{i}",
                confidence=0.85,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="provisional",
            )
            for i in range(5)
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # All 5 should be selected (no provisional cap)
        assert len(result) == 5

    def test_validated_ranked_above_zero_score_provisional(self) -> None:
        """Validated patterns appear before zero-score provisional patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            include_provisional=True,
            provisional_dampening=0.5,
            max_provisional=None,
        )
        patterns = [
            make_pattern(
                pattern_id="prov-zero",
                domain="testing",
                confidence=0.9,
                usage_count=0,  # Score will be 0 (log1p(0) = 0)
                success_rate=0.8,
                lifecycle_state="provisional",
            ),
            make_pattern(
                pattern_id="val-active",
                domain="testing",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state="validated",
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Both selected (no filter on score=0), but validated first
        assert result[0].pattern_id == "val-active"
        # prov-zero has score 0 but is still technically valid for selection
        assert len(result) == 2


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Test include_provisional=False (default) maintains backward compat."""

    def test_default_config_no_provisional(self) -> None:
        """Default InjectionLimitsConfig has include_provisional=False."""
        config = InjectionLimitsConfig()
        assert config.include_provisional is False
        assert config.provisional_dampening == 0.5
        assert config.max_provisional is None

    def test_patterns_without_lifecycle_state_work(self) -> None:
        """Patterns without lifecycle_state field still work in selection."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=5,
            max_per_domain=10,
            max_tokens_injected=10000,
        )
        # Old-style patterns without lifecycle_state
        patterns = [
            make_pattern(
                pattern_id="old-1",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
                lifecycle_state=None,
            ),
            make_pattern(
                pattern_id="old-2",
                confidence=0.85,
                usage_count=8,
                success_rate=0.75,
                lifecycle_state=None,
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Both should be selected (no dampening for None lifecycle_state)
        assert len(result) == 2

    def test_provisional_dampening_only_affects_provisional(self) -> None:
        """Setting provisional_dampening does not affect validated patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=5,
            max_per_domain=10,
            max_tokens_injected=10000,
            provisional_dampening=0.1,  # Very aggressive dampening
        )
        pattern = make_pattern(
            pattern_id="val-1",
            confidence=0.9,
            usage_count=10,
            success_rate=0.8,
            lifecycle_state="validated",
        )

        result = select_patterns_for_injection([pattern], limits)  # type: ignore[arg-type]

        # Validated pattern should still be selected
        assert len(result) == 1
        assert result[0].pattern_id == "val-1"


# =============================================================================
# Configuration Tests
# =============================================================================


class TestProvisionalConfig:
    """Test provisional configuration knobs."""

    def test_include_provisional_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """include_provisional loads from environment."""
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_INCLUDE_PROVISIONAL", "true")
        config = InjectionLimitsConfig.from_env()
        assert config.include_provisional is True

    def test_provisional_dampening_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provisional_dampening loads from environment."""
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_PROVISIONAL_DAMPENING", "0.3")
        config = InjectionLimitsConfig.from_env()
        assert config.provisional_dampening == 0.3

    def test_max_provisional_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_provisional loads from environment."""
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_MAX_PROVISIONAL", "3")
        config = InjectionLimitsConfig.from_env()
        assert config.max_provisional == 3

    def test_provisional_dampening_validation(self) -> None:
        """provisional_dampening must be between 0.0 and 1.0."""
        with pytest.raises(ValueError):
            InjectionLimitsConfig(provisional_dampening=-0.1)

        with pytest.raises(ValueError):
            InjectionLimitsConfig(provisional_dampening=1.5)

    def test_max_provisional_validation(self) -> None:
        """max_provisional must be >= 1 if set."""
        with pytest.raises(ValueError):
            InjectionLimitsConfig(max_provisional=0)


# =============================================================================
# Handler Integration Tests
# =============================================================================


class TestHandlerIntegration:
    """Test handler integration with provisional patterns (mock-DB)."""

    @pytest.mark.asyncio
    async def test_handler_with_provisional_pattern(self) -> None:
        """Handler formats provisional patterns from DB with badge."""
        patterns = [
            ModelPatternRecord(
                pattern_id="val-1",
                domain="testing",
                title="Validated Pattern",
                description="A validated pattern.",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
            ),
            ModelPatternRecord(
                pattern_id="prov-1",
                domain="code_review",
                title="Provisional Pattern",
                description="A provisional pattern.",
                confidence=0.7,
                usage_count=5,
                success_rate=0.6,
                lifecycle_state="provisional",
            ),
        ]

        config = ContextInjectionConfig(
            enabled=True,
            db_enabled=True,
            min_confidence=0.0,
            limits=InjectionLimitsConfig(include_provisional=True),
        )
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
        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 2
        assert "Validated Pattern" in result.context_markdown
        assert "[Provisional]" in result.context_markdown

    @pytest.mark.asyncio
    async def test_handler_excludes_provisional_when_disabled(self) -> None:
        """Handler excludes provisional patterns when include_provisional=False."""
        patterns = [
            ModelPatternRecord(
                pattern_id="val-1",
                domain="testing",
                title="Validated Pattern",
                description="A validated pattern.",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
            ),
            ModelPatternRecord(
                pattern_id="prov-1",
                domain="code_review",
                title="Provisional Pattern",
                description="A provisional pattern.",
                confidence=0.7,
                usage_count=5,
                success_rate=0.6,
                lifecycle_state="provisional",
            ),
        ]

        # Default config has include_provisional=False
        config = ContextInjectionConfig(
            enabled=True,
            min_confidence=0.0,
            db_enabled=True,
        )
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
        result = await handler.handle(emit_event=False)

        assert result.success is True
        assert result.pattern_count == 1  # Only validated pattern selected
        assert "Validated Pattern" in result.context_markdown
        assert "[Provisional]" not in result.context_markdown

    @pytest.mark.asyncio
    async def test_load_patterns_disabled_returns_empty_with_warning(self) -> None:
        """Pattern loading returns empty with warning when api_enabled=False (OMN-2355).

        OMN-2058 disabled direct DB access. OMN-2355 restored loading via HTTP API.
        When api_enabled=False (explicit opt-out), the method returns empty patterns
        with a structured warning. The old "pending_api" stub is replaced by the real
        API path; this test verifies the explicit-disabled fallback.
        """
        config = ContextInjectionConfig(
            enabled=True,
            db_enabled=True,
            api_enabled=False,  # Explicit opt-out → disabled path
            min_confidence=0.0,
            limits=InjectionLimitsConfig(include_provisional=True),
        )
        handler = HandlerContextInjection(config=config)

        result = await handler._load_patterns_from_database(domain="testing")

        # Should return empty patterns (API explicitly disabled)
        assert len(result.patterns) == 0
        assert len(result.warnings) == 1
        assert "OMN-2059" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_load_patterns_disabled_without_domain(self) -> None:
        """Pattern loading disabled even without domain filter when api_enabled=False."""
        config = ContextInjectionConfig(
            enabled=True,
            db_enabled=True,
            api_enabled=False,  # Explicit opt-out → disabled path
            min_confidence=0.0,
            limits=InjectionLimitsConfig(include_provisional=True),
        )
        handler = HandlerContextInjection(config=config)

        result = await handler._load_patterns_from_database(domain=None)

        # Should return empty patterns (API explicitly disabled)
        assert len(result.patterns) == 0
        assert len(result.warnings) == 1
        assert "api_enabled=False" in result.warnings[0]
