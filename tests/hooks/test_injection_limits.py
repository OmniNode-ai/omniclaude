# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for injection limits module (OMN-1671).

Tests verify:
1. Token counting with tiktoken cl100k_base
2. Domain normalization through taxonomy
3. Effective score calculation formula
4. Selection algorithm with all limit types:
   - max_patterns_per_injection
   - max_per_domain
   - max_tokens_injected
5. Deterministic ordering
6. "prefer_fewer_high_confidence" policy
7. Configuration via environment variables

Part of OMN-1671: INJECT-002 - Add injection limits configuration.
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.injection_limits import (
    DOMAIN_ALIASES,
    KNOWN_DOMAINS,
    InjectionLimitsConfig,
    compute_effective_score,
    count_tokens,
    normalize_domain,
    render_single_pattern,
    select_patterns_for_injection,
)
from tests.hooks.conftest import MockPatternRecord, make_pattern

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Token Counting Tests
# =============================================================================


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_empty_string(self) -> None:
        """Empty string has 0 tokens."""
        assert count_tokens("") == 0

    def test_simple_text(self) -> None:
        """Simple text tokenizes correctly."""
        # "Hello world" is typically 2 tokens
        tokens = count_tokens("Hello world")
        assert tokens > 0
        assert tokens < 10  # Sanity check

    def test_markdown_text(self) -> None:
        """Markdown text tokenizes."""
        md = """## Header

Some **bold** text and `code`.
"""
        tokens = count_tokens(md)
        assert tokens > 5  # Has multiple elements

    def test_deterministic(self) -> None:
        """Same input always produces same token count."""
        text = "This is a test string for tokenization."
        count1 = count_tokens(text)
        count2 = count_tokens(text)
        assert count1 == count2

    def test_special_characters(self) -> None:
        """Special characters are handled."""
        text = "Code: `def foo(): pass` and emoji"
        tokens = count_tokens(text)
        assert tokens > 0


# =============================================================================
# Domain Normalization Tests
# =============================================================================


class TestNormalizeDomain:
    """Tests for normalize_domain function."""

    def test_known_alias_lowercase(self) -> None:
        """Known aliases are normalized."""
        assert normalize_domain("py") == "python"
        assert normalize_domain("js") == "javascript"
        assert normalize_domain("ts") == "typescript"

    def test_known_alias_mixed_case(self) -> None:
        """Case-insensitive matching."""
        assert normalize_domain("Py") == "python"
        assert normalize_domain("PY") == "python"
        assert normalize_domain("Python") == "python"
        assert normalize_domain("PYTHON") == "python"

    def test_known_canonical_domain(self) -> None:
        """Canonical domains pass through."""
        assert normalize_domain("python") == "python"
        assert normalize_domain("testing") == "testing"
        assert normalize_domain("code_review") == "code_review"

    def test_unknown_domain(self) -> None:
        """Unknown domains get unknown/ prefix."""
        assert normalize_domain("custom_domain") == "unknown/custom_domain"
        assert normalize_domain("my_special_domain") == "unknown/my_special_domain"

    def test_whitespace_stripped(self) -> None:
        """Whitespace is stripped."""
        assert normalize_domain("  python  ") == "python"
        assert normalize_domain("\tpy\n") == "python"

    def test_domain_aliases_complete(self) -> None:
        """All aliases map to known domains."""
        for alias, canonical in DOMAIN_ALIASES.items():
            assert canonical in KNOWN_DOMAINS, (
                f"Alias {alias} maps to unknown {canonical}"
            )

    def test_general_domain(self) -> None:
        """General domain variants normalize correctly."""
        assert normalize_domain("general") == "general"
        assert normalize_domain("all") == "general"


# =============================================================================
# Effective Score Tests
# =============================================================================


class TestComputeEffectiveScore:
    """Tests for compute_effective_score function."""

    def test_zero_usage_count(self) -> None:
        """Zero usage_count produces zero score (log1p(0) = 0)."""
        score = compute_effective_score(
            confidence=0.9,
            success_rate=0.8,
            usage_count=0,
        )
        assert score == 0.0

    def test_all_ones(self) -> None:
        """Maximum inputs approach 1.0 (but usage factor caps)."""
        score = compute_effective_score(
            confidence=1.0,
            success_rate=1.0,
            usage_count=1000,  # High usage
        )
        # With k=5.0, usage_factor = min(1.0, log1p(1000)/5.0) = min(1.0, 1.38) = 1.0
        assert 0.99 <= score <= 1.0

    def test_moderate_values(self) -> None:
        """Moderate values produce reasonable score."""
        score = compute_effective_score(
            confidence=0.8,
            success_rate=0.7,
            usage_count=10,
        )
        # 0.8 * 0.7 * (log1p(10)/5.0) = 0.56 * 0.48 = ~0.27
        assert 0.2 <= score <= 0.4

    def test_clamping_confidence(self) -> None:
        """Confidence values outside [0,1] are clamped."""
        score_over = compute_effective_score(1.5, 0.5, 10)
        score_normal = compute_effective_score(1.0, 0.5, 10)
        assert score_over == score_normal  # Clamped to 1.0

        score_under = compute_effective_score(-0.5, 0.5, 10)
        assert score_under == 0.0  # Clamped to 0.0

    def test_clamping_success_rate(self) -> None:
        """Success rate values outside [0,1] are clamped."""
        score_over = compute_effective_score(0.8, 1.5, 10)
        score_normal = compute_effective_score(0.8, 1.0, 10)
        assert score_over == score_normal

    def test_clamping_usage_count(self) -> None:
        """Negative usage_count treated as 0."""
        score_neg = compute_effective_score(0.8, 0.8, -5)
        score_zero = compute_effective_score(0.8, 0.8, 0)
        assert score_neg == score_zero == 0.0

    def test_usage_count_scale_effect(self) -> None:
        """Higher scale reduces usage_count impact."""
        score_low_k = compute_effective_score(0.8, 0.8, 10, usage_count_scale=2.0)
        score_high_k = compute_effective_score(0.8, 0.8, 10, usage_count_scale=10.0)
        assert score_low_k > score_high_k  # Lower k = usage counts more

    def test_monotonic_in_usage_count(self) -> None:
        """Score increases monotonically with usage_count."""
        scores = [
            compute_effective_score(0.8, 0.8, count) for count in [1, 5, 10, 50, 100]
        ]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], "Score should increase with usage"


# =============================================================================
# Pattern Rendering Tests
# =============================================================================


class TestRenderSinglePattern:
    """Tests for render_single_pattern function."""

    def test_basic_rendering(self) -> None:
        """Pattern renders to markdown."""
        pattern = make_pattern()
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]

        assert "### Test Pattern" in rendered
        assert "**Domain**: testing" in rendered
        assert "**Confidence**: 90%" in rendered
        assert "**Success Rate**: 80%" in rendered
        assert "(10 uses)" in rendered
        assert "A test pattern description" in rendered

    def test_with_example_reference(self) -> None:
        """Example reference is included."""
        pattern = make_pattern(example_reference="src/file.py:42")
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]

        assert "*Example: `src/file.py:42`*" in rendered

    def test_without_example_reference(self) -> None:
        """No example reference section when None."""
        pattern = make_pattern(example_reference=None)
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]

        assert "Example:" not in rendered

    def test_ends_with_separator(self) -> None:
        """Rendered pattern ends with separator."""
        pattern = make_pattern()
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]

        assert rendered.strip().endswith("---")


# =============================================================================
# Configuration Tests
# =============================================================================


class TestInjectionLimitsConfig:
    """Tests for InjectionLimitsConfig."""

    def test_defaults(self) -> None:
        """Default values are sensible."""
        config = InjectionLimitsConfig()

        assert config.max_patterns_per_injection == 5
        assert config.max_tokens_injected == 2000
        assert config.max_per_domain == 2
        assert config.selection_policy == "prefer_fewer_high_confidence"
        assert config.usage_count_scale == 5.0

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configuration loads from environment."""
        monkeypatch.setenv(
            "OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION", "10"
        )
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_MAX_TOKENS_INJECTED", "3000")
        monkeypatch.setenv("OMNICLAUDE_INJECTION_LIMITS_MAX_PER_DOMAIN", "3")

        config = InjectionLimitsConfig.from_env()

        assert config.max_patterns_per_injection == 10
        assert config.max_tokens_injected == 3000
        assert config.max_per_domain == 3

    def test_validation_bounds(self) -> None:
        """Values must be within bounds."""
        with pytest.raises(ValueError):
            InjectionLimitsConfig(max_patterns_per_injection=0)

        with pytest.raises(ValueError):
            InjectionLimitsConfig(max_patterns_per_injection=100)

        with pytest.raises(ValueError):
            InjectionLimitsConfig(max_tokens_injected=50)

        with pytest.raises(ValueError):
            InjectionLimitsConfig(usage_count_scale=0.5)


# =============================================================================
# Selection Algorithm Tests
# =============================================================================


class TestSelectPatternsForInjection:
    """Tests for select_patterns_for_injection function."""

    @pytest.fixture
    def default_limits(self) -> InjectionLimitsConfig:
        """Default limits config for testing."""
        return InjectionLimitsConfig()

    @pytest.fixture
    def many_patterns(self) -> list[MockPatternRecord]:
        """Create multiple patterns for testing."""
        return [
            make_pattern(
                pattern_id=f"pat-{i:03d}",
                domain=domain,
                confidence=0.9 - (i * 0.05),
                usage_count=20 - i,
                success_rate=0.9 - (i * 0.02),
            )
            for i, domain in enumerate(
                [
                    "testing",
                    "testing",
                    "code_review",
                    "code_review",
                    "debugging",
                    "debugging",
                    "general",
                ]
            )
        ]

    def test_empty_candidates(self, default_limits: InjectionLimitsConfig) -> None:
        """Empty input returns empty output."""
        result = select_patterns_for_injection([], default_limits)
        assert result == []

    def test_max_patterns_limit(self) -> None:
        """Respects max_patterns_per_injection limit."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=2,
            max_per_domain=10,  # High to not trigger
            max_tokens_injected=10000,  # High to not trigger
        )
        patterns = [
            make_pattern(
                pattern_id=f"pat-{i}", confidence=0.9, usage_count=10, success_rate=0.8
            )
            for i in range(5)
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        assert len(result) == 2

    def test_max_per_domain_limit(self) -> None:
        """Respects max_per_domain limit."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=1,
            max_tokens_injected=10000,
        )
        patterns = [
            make_pattern(
                pattern_id="pat-1",
                domain="testing",
                confidence=0.95,
                usage_count=10,
                success_rate=0.9,
            ),
            make_pattern(
                pattern_id="pat-2",
                domain="testing",
                confidence=0.90,
                usage_count=10,
                success_rate=0.9,
            ),
            make_pattern(
                pattern_id="pat-3",
                domain="code_review",
                confidence=0.85,
                usage_count=10,
                success_rate=0.9,
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Should have 1 testing + 1 code_review
        assert len(result) == 2
        domains = [p.domain for p in result]
        assert domains.count("testing") == 1
        assert domains.count("code_review") == 1

    def test_max_tokens_limit(self) -> None:
        """Respects max_tokens_injected limit."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=200,  # Very low - will limit selection
        )
        patterns = [
            make_pattern(
                pattern_id=f"pat-{i}",
                domain=f"domain-{i}",  # Different domains
                description="A" * 500,  # Long description = many tokens
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
            )
            for i in range(5)
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # With 200 token budget and ~50 header tokens, only 1-2 patterns fit
        assert len(result) <= 2

    def test_deterministic_ordering(
        self, default_limits: InjectionLimitsConfig
    ) -> None:
        """Selection is deterministic - same input, same output."""
        patterns = [
            make_pattern(
                pattern_id="pat-b", confidence=0.8, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-a", confidence=0.8, usage_count=10, success_rate=0.8
            ),  # Same score
            make_pattern(
                pattern_id="pat-c", confidence=0.9, usage_count=10, success_rate=0.8
            ),  # Higher
        ]

        result1 = select_patterns_for_injection(patterns, default_limits)  # type: ignore[arg-type]
        result2 = select_patterns_for_injection(patterns, default_limits)  # type: ignore[arg-type]

        assert [p.pattern_id for p in result1] == [p.pattern_id for p in result2]

    def test_sort_order_effective_score(self) -> None:
        """Patterns sorted by effective_score descending."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
        )
        patterns = [
            make_pattern(
                pattern_id="low", confidence=0.5, usage_count=5, success_rate=0.5
            ),
            make_pattern(
                pattern_id="high", confidence=0.95, usage_count=20, success_rate=0.9
            ),
            make_pattern(
                pattern_id="mid", confidence=0.75, usage_count=10, success_rate=0.7
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Higher effective_score first
        assert result[0].pattern_id == "high"
        assert result[1].pattern_id == "mid"
        assert result[2].pattern_id == "low"

    def test_tie_break_by_confidence(self) -> None:
        """Ties in effective_score broken by confidence."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
        )
        # Same effective score (0.9 * 0.8 * usage_factor), different confidence
        patterns = [
            make_pattern(
                pattern_id="a", confidence=0.72, usage_count=10, success_rate=1.0
            ),  # Same effective
            make_pattern(
                pattern_id="b", confidence=0.90, usage_count=10, success_rate=0.8
            ),  # Higher confidence
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Higher confidence wins tie-break
        assert result[0].pattern_id == "b"

    def test_tie_break_by_pattern_id(self) -> None:
        """Final tie-break by pattern_id ascending."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
        )
        # Identical scores
        patterns = [
            make_pattern(
                pattern_id="pat-c", confidence=0.8, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-a", confidence=0.8, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-b", confidence=0.8, usage_count=10, success_rate=0.8
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Alphabetical order for identical scores
        assert [p.pattern_id for p in result] == ["pat-a", "pat-b", "pat-c"]

    def test_prefer_fewer_high_confidence_policy(self) -> None:
        """Never swaps in lower-scoring patterns to fill quota."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=5,
            max_per_domain=1,  # Only 1 per domain
            max_tokens_injected=10000,
        )
        patterns = [
            make_pattern(
                pattern_id="high-testing",
                domain="testing",
                confidence=0.95,
                usage_count=20,
                success_rate=0.9,
            ),
            make_pattern(
                pattern_id="low-testing",
                domain="testing",
                confidence=0.60,
                usage_count=5,
                success_rate=0.5,
            ),
            make_pattern(
                pattern_id="high-review",
                domain="code_review",
                confidence=0.90,
                usage_count=15,
                success_rate=0.85,
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # Should have high-testing and high-review, NOT low-testing
        pattern_ids = [p.pattern_id for p in result]
        assert "high-testing" in pattern_ids
        assert "high-review" in pattern_ids
        assert "low-testing" not in pattern_ids

    def test_domain_normalization_applied(self) -> None:
        """Domain normalization affects caps."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=1,  # Only 1 per normalized domain
            max_tokens_injected=10000,
        )
        patterns = [
            make_pattern(
                pattern_id="py1",
                domain="py",
                confidence=0.9,
                usage_count=10,
                success_rate=0.8,
            ),
            make_pattern(
                pattern_id="py2",
                domain="python",
                confidence=0.85,
                usage_count=10,
                success_rate=0.8,
            ),
            make_pattern(
                pattern_id="py3",
                domain="Python",
                confidence=0.80,
                usage_count=10,
                success_rate=0.8,
            ),
        ]

        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        # All normalize to "python", so only 1 should be selected
        assert len(result) == 1
        assert result[0].pattern_id == "py1"  # Highest score


# =============================================================================
# Integration with ContextInjectionConfig Tests
# =============================================================================


class TestContextInjectionConfigIntegration:
    """Test that InjectionLimitsConfig integrates with ContextInjectionConfig."""

    def test_import_into_context_config(self) -> None:
        """InjectionLimitsConfig can be imported and composed."""
        from omniclaude.hooks.context_config import ContextInjectionConfig

        config = ContextInjectionConfig()

        assert hasattr(config, "limits")
        assert isinstance(config.limits, InjectionLimitsConfig)
        assert config.limits.max_patterns_per_injection == 5

    def test_nested_config_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nested limits config loads from environment."""
        from omniclaude.hooks.context_config import ContextInjectionConfig

        monkeypatch.setenv(
            "OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION", "8"
        )

        config = ContextInjectionConfig.from_env()

        assert config.limits.max_patterns_per_injection == 8


# =============================================================================
# Format Synchronization Tests
# =============================================================================


class TestFormatSynchronization:
    """Tests verifying render_single_pattern() stays in sync with handler format.

    The render_single_pattern() function in injection_limits.py must produce
    identical pattern formatting as _format_patterns_markdown() in
    handler_context_injection.py. This is critical because:

    1. render_single_pattern() is used for token counting during selection
    2. _format_patterns_markdown() is used for actual injection output
    3. If they differ, token budgets won't match actual output sizes

    These tests catch format drift between the two implementations.
    """

    def test_render_single_pattern_matches_handler_format(self) -> None:
        """Verify render_single_pattern() produces same format as handler.

        This test creates a pattern, renders it with both functions, and
        verifies the pattern-specific content is identical. The handler
        adds a header and removes trailing separators, so we extract the
        pattern portion for comparison.
        """
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        # Create a real PatternRecord (not mock) for handler compatibility
        pattern = PatternRecord(
            pattern_id="sync-test-001",
            domain="testing",
            title="Format Synchronization Test",
            description="This pattern tests that render_single_pattern stays in sync.",
            confidence=0.85,
            usage_count=42,
            success_rate=0.92,
            example_reference=None,
        )

        # Render with injection_limits function
        single_render = render_single_pattern(pattern)

        # Render with handler's format function
        handler = HandlerContextInjection()
        # Access private method for testing (patterns already limited)
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Extract pattern content from handler output (skip header)
        # Header is: "## Learned Patterns...\n\nThe following...\n\n"
        # That's 4 lines when split
        header_lines = [
            "## Learned Patterns (Auto-Injected)",
            "",
            "The following patterns have been learned from previous sessions:",
            "",
        ]
        expected_header = "\n".join(header_lines)

        assert handler_render.startswith(expected_header), (
            f"Handler output should start with expected header.\n"
            f"Expected header:\n{expected_header!r}\n"
            f"Got:\n{handler_render[: len(expected_header) + 50]!r}"
        )

        # Extract pattern portion from handler (after header)
        handler_pattern_content = handler_render[len(expected_header) :]

        # Single render includes trailing separator "---\n\n"
        # Handler removes trailing separator for last pattern
        # So we need to strip the trailing separator from single_render
        # Also strip leading/trailing whitespace for clean comparison
        single_render_stripped = single_render.strip()
        if single_render_stripped.endswith("---"):
            single_render_stripped = single_render_stripped[:-3].strip()

        handler_pattern_stripped = handler_pattern_content.strip()

        assert single_render_stripped == handler_pattern_stripped, (
            f"Pattern content mismatch between render_single_pattern() and "
            f"handler._format_patterns_markdown().\n\n"
            f"render_single_pattern() produced:\n{single_render_stripped!r}\n\n"
            f"Handler pattern portion:\n{handler_pattern_stripped!r}\n\n"
            f"These must stay in sync for accurate token counting."
        )

    def test_render_single_pattern_with_example_reference(self) -> None:
        """Verify format sync when pattern has example_reference."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="sync-test-002",
            domain="code_review",
            title="Pattern With Example",
            description="Testing example_reference formatting sync.",
            confidence=0.75,
            usage_count=10,
            success_rate=0.80,
            example_reference="src/module/file.py:123",
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Extract pattern portion (skip 4-line header)
        header_end = handler_render.find("### ")
        handler_pattern = handler_render[header_end:]

        # Strip trailing separators for comparison
        single_stripped = single_render.rstrip()
        if single_stripped.endswith("---"):
            single_stripped = single_stripped[:-3].rstrip()

        handler_stripped = handler_pattern.rstrip()

        assert single_stripped == handler_stripped, (
            f"Pattern with example_reference has format mismatch.\n\n"
            f"render_single_pattern():\n{single_stripped!r}\n\n"
            f"Handler:\n{handler_stripped!r}"
        )

        # Also verify example reference is present in both
        assert "*Example: `src/module/file.py:123`*" in single_render
        assert "*Example: `src/module/file.py:123`*" in handler_render

    def test_render_preserves_exact_formatting(self) -> None:
        """Verify specific formatting elements match exactly."""
        from omniclaude.hooks.handler_context_injection import (
            HandlerContextInjection,
            PatternRecord,
        )

        pattern = PatternRecord(
            pattern_id="format-check",
            domain="python",
            title="Exact Format Check",
            description="Verifying exact formatting elements.",
            confidence=0.90,
            usage_count=100,
            success_rate=0.85,
        )

        single_render = render_single_pattern(pattern)
        handler = HandlerContextInjection()
        handler_render = handler._format_patterns_markdown([pattern], max_patterns=1)

        # Check specific format elements are present in both
        expected_elements = [
            "### Exact Format Check",
            "- **Domain**: python",
            "- **Confidence**: 90%",
            "- **Success Rate**: 85% (100 uses)",
            "Verifying exact formatting elements.",
        ]

        for element in expected_elements:
            assert element in single_render, (
                f"render_single_pattern missing: {element!r}"
            )
            assert element in handler_render, f"handler format missing: {element!r}"


# =============================================================================
# Evidence Tier Tests (OMN-2044)
# =============================================================================


class TestEvidenceTierRendering:
    """Tests for evidence_tier badge rendering in render_single_pattern."""

    def test_measured_badge_in_render(self) -> None:
        """render_single_pattern includes [Measured] badge."""
        pattern = make_pattern(title="My Pattern", evidence_tier="MEASURED")
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern [Measured]" in rendered

    def test_verified_badge_in_render(self) -> None:
        """render_single_pattern includes [Verified] badge."""
        pattern = make_pattern(title="My Pattern", evidence_tier="VERIFIED")
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern [Verified]" in rendered

    def test_unmeasured_no_badge(self) -> None:
        """UNMEASURED patterns do not get a badge."""
        pattern = make_pattern(title="My Pattern", evidence_tier="UNMEASURED")
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern" in rendered
        assert "[Measured]" not in rendered
        assert "[Verified]" not in rendered

    def test_none_evidence_tier_no_badge(self) -> None:
        """Patterns with evidence_tier=None do not get a badge."""
        pattern = make_pattern(title="My Pattern", evidence_tier=None)
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "### My Pattern" in rendered
        assert "[Measured]" not in rendered
        assert "[Verified]" not in rendered

    def test_combined_provisional_and_measured(self) -> None:
        """Provisional + Measured produces both badges."""
        pattern = make_pattern(
            title="My Pattern",
            lifecycle_state="provisional",
            evidence_tier="MEASURED",
        )
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "[Provisional]" in rendered
        assert "[Measured]" in rendered
        assert "### My Pattern [Provisional] [Measured]" in rendered

    def test_combined_provisional_and_verified(self) -> None:
        """Provisional + Verified produces both badges."""
        pattern = make_pattern(
            title="My Pattern",
            lifecycle_state="provisional",
            evidence_tier="VERIFIED",
        )
        rendered = render_single_pattern(pattern)  # type: ignore[arg-type]
        assert "[Provisional]" in rendered
        assert "[Verified]" in rendered
        assert "### My Pattern [Provisional] [Verified]" in rendered


class TestRequireMeasuredFilter:
    """Tests for require_measured filter in select_patterns_for_injection."""

    def test_require_measured_filters_unmeasured(self) -> None:
        """require_measured=True filters out UNMEASURED patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            require_measured=True,
        )
        patterns = [
            make_pattern(
                pattern_id="unmeasured",
                domain="testing",
                evidence_tier="UNMEASURED",
            ),
            make_pattern(
                pattern_id="measured",
                domain="code_review",
                evidence_tier="MEASURED",
            ),
            make_pattern(
                pattern_id="verified",
                domain="debugging",
                evidence_tier="VERIFIED",
            ),
        ]
        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        ids = [p.pattern_id for p in result]
        assert "unmeasured" not in ids
        assert "measured" in ids
        assert "verified" in ids
        assert len(result) == 2

    def test_require_measured_filters_none_tier(self) -> None:
        """require_measured=True filters out None evidence_tier."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            require_measured=True,
        )
        patterns = [
            make_pattern(
                pattern_id="none-tier",
                domain="testing",
                evidence_tier=None,
            ),
            make_pattern(
                pattern_id="verified",
                domain="code_review",
                evidence_tier="VERIFIED",
            ),
        ]
        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        assert len(result) == 1
        assert result[0].pattern_id == "verified"

    def test_require_measured_false_passes_all(self) -> None:
        """require_measured=False (default) passes all patterns."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            require_measured=False,
        )
        patterns = [
            make_pattern(pattern_id="unmeasured", evidence_tier="UNMEASURED"),
            make_pattern(
                pattern_id="measured", domain="code_review", evidence_tier="MEASURED"
            ),
            make_pattern(pattern_id="none", domain="debugging", evidence_tier=None),
        ]
        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        assert len(result) == 3

    def test_require_measured_empty_after_filter(self) -> None:
        """require_measured=True with all unmeasured returns empty."""
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            require_measured=True,
        )
        patterns = [
            make_pattern(pattern_id="u1", evidence_tier="UNMEASURED"),
            make_pattern(pattern_id="u2", domain="code_review", evidence_tier=None),
        ]
        result = select_patterns_for_injection(patterns, limits)  # type: ignore[arg-type]

        assert result == []

    def test_require_measured_default_is_false(self) -> None:
        """Default InjectionLimitsConfig has require_measured=False."""
        config = InjectionLimitsConfig()
        assert config.require_measured is False


# =============================================================================
# Evidence Scoring Tests (OMN-2092)
# =============================================================================


class TestEvidenceScoring:
    """Tests for compute_effective_score() with gate_result evidence boost/penalty."""

    def test_pass_applies_boost(self) -> None:
        """score * 1.3 for gate_result="pass"."""
        base_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
        )
        boosted_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
            gate_result="pass",
        )
        assert boosted_score == pytest.approx(base_score * 1.3)

    def test_fail_applies_penalty(self) -> None:
        """score * 0.6 for gate_result="fail"."""
        base_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
        )
        penalized_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
            gate_result="fail",
        )
        assert penalized_score == pytest.approx(base_score * 0.6)

    def test_insufficient_evidence_neutral(self) -> None:
        """No modifier for gate_result="insufficient_evidence"."""
        base_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
        )
        neutral_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
            gate_result="insufficient_evidence",
        )
        assert neutral_score == pytest.approx(base_score)

    def test_none_gate_result_neutral(self) -> None:
        """No modifier for None."""
        base_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
        )
        neutral_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
            gate_result=None,
        )
        assert neutral_score == pytest.approx(base_score)

    def test_boost_capped_at_3x(self) -> None:
        """evidence_boost=5.0 capped to 3.0."""
        base_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
        )
        # Try to boost with 5.0 (should cap to 3.0)
        capped_score = compute_effective_score(
            confidence=0.8,
            success_rate=0.8,
            usage_count=10,
            gate_result="pass",
            evidence_boost=5.0,
        )
        assert capped_score == pytest.approx(base_score * 3.0)

    def test_config_rejects_evidence_boost_above_3(self) -> None:
        """InjectionLimitsConfig rejects evidence_boost > 3.0 at validation time."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="evidence_boost"):
            InjectionLimitsConfig(evidence_boost=5.0)

    def test_config_rejects_evidence_boost_at_or_below_1(self) -> None:
        """InjectionLimitsConfig rejects evidence_boost <= 1.0 at validation time."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="evidence_boost"):
            InjectionLimitsConfig(evidence_boost=1.0)


# =============================================================================
# Evidence Policy Tests (OMN-2092)
# =============================================================================


class TestEvidencePolicy:
    """Tests for select_patterns_for_injection() with evidence resolver."""

    def test_ignore_policy_does_not_consult_resolver(self) -> None:
        """evidence_policy="ignore" doesn't call resolver."""
        from tests.hooks.dict_evidence_resolver import DictEvidenceResolver

        # Create resolver that would raise if called
        class StrictResolver(DictEvidenceResolver):
            def resolve(self, pattern_id: str) -> str | None:
                raise RuntimeError("Resolver should not be called with ignore policy")

        resolver = StrictResolver({})
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="ignore",
        )
        patterns = [make_pattern(pattern_id="pat-1")]

        # Should not raise
        result = select_patterns_for_injection(
            patterns, limits, evidence_resolver=resolver
        )  # type: ignore[arg-type]
        assert len(result) == 1

    def test_boost_policy_reranks_by_evidence(self) -> None:
        """KEY DEMO: 3 patterns with same base stats, evidence_policy="boost" reranks by gate_result."""
        from tests.hooks.dict_evidence_resolver import DictEvidenceResolver

        resolver = DictEvidenceResolver(
            {
                "pat-a": "pass",
                "pat-b": "fail",
                # pat-c not in dict → None
            }
        )
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="boost",
        )
        patterns = [
            make_pattern(
                pattern_id="pat-a", confidence=0.9, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-b", confidence=0.9, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-c", confidence=0.9, usage_count=10, success_rate=0.8
            ),
        ]

        result = select_patterns_for_injection(
            patterns, limits, evidence_resolver=resolver
        )  # type: ignore[arg-type]
        ids = [p.pattern_id for p in result]

        # pass first, neutral second, fail third
        assert ids == ["pat-a", "pat-c", "pat-b"]

    def test_require_policy_filters_non_pass(self) -> None:
        """evidence_policy="require" only selects pass patterns."""
        from tests.hooks.dict_evidence_resolver import DictEvidenceResolver

        resolver = DictEvidenceResolver(
            {
                "pat-pass": "pass",
                "pat-fail": "fail",
                "pat-insufficient": "insufficient_evidence",
            }
        )
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="require",
        )
        patterns = [
            make_pattern(pattern_id="pat-pass", domain="testing"),
            make_pattern(pattern_id="pat-fail", domain="code_review"),
            make_pattern(pattern_id="pat-insufficient", domain="debugging"),
        ]

        result = select_patterns_for_injection(
            patterns, limits, evidence_resolver=resolver
        )  # type: ignore[arg-type]
        assert len(result) == 1
        assert result[0].pattern_id == "pat-pass"

    def test_require_policy_empty_when_no_pass(self) -> None:
        """All fail/None → empty result."""
        from tests.hooks.dict_evidence_resolver import DictEvidenceResolver

        resolver = DictEvidenceResolver(
            {
                "pat-a": "fail",
                "pat-b": "insufficient_evidence",
            }
        )
        limits = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="require",
        )
        patterns = [
            make_pattern(pattern_id="pat-a"),
            make_pattern(pattern_id="pat-b", domain="code_review"),
            make_pattern(pattern_id="pat-c", domain="debugging"),  # None
        ]

        result = select_patterns_for_injection(
            patterns, limits, evidence_resolver=resolver
        )  # type: ignore[arg-type]
        assert result == []

    def test_resolver_none_treated_as_null(self) -> None:
        """evidence_resolver=None → same as NullEvidenceResolver."""
        limits_with_none = InjectionLimitsConfig(
            max_patterns_per_injection=10,
            max_per_domain=10,
            max_tokens_injected=10000,
            evidence_policy="boost",
        )
        patterns = [
            make_pattern(
                pattern_id="pat-a", confidence=0.9, usage_count=10, success_rate=0.8
            ),
            make_pattern(
                pattern_id="pat-b", confidence=0.8, usage_count=10, success_rate=0.8
            ),
        ]

        result = select_patterns_for_injection(
            patterns, limits_with_none, evidence_resolver=None
        )  # type: ignore[arg-type]

        # Should work without error, ordering by base score only
        assert len(result) == 2
        assert result[0].pattern_id == "pat-a"  # Higher confidence

    def test_evidence_badge_not_in_rendered_output(self) -> None:
        """render_single_pattern does NOT include evidence badges (format sync with handler).

        Evidence badges are intentionally excluded from render_single_pattern()
        because _format_patterns_markdown() in handler_context_injection.py does
        not have access to gate_result. Including them would desynchronize token
        counting from actual output.
        """
        pattern = make_pattern(pattern_id="pat-pass", title="Test Pattern")
        rendered = render_single_pattern(pattern, gate_result="pass")  # type: ignore[arg-type]

        assert "[Evidence: Pass]" not in rendered
        assert "### Test Pattern" in rendered

    def test_default_evidence_policy_is_ignore(self) -> None:
        """InjectionLimitsConfig().evidence_policy == "ignore"."""
        config = InjectionLimitsConfig()
        assert config.evidence_policy == "ignore"
