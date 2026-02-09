# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Injection limits configuration and pattern selection algorithm.

This module implements OMN-1671 (INJECT-002): configurable injection limits
to prevent context explosion from over-injection.

The selection algorithm is deterministic and constraint-first:
1. Normalize candidates (domain normalization, effective score computation)
2. Apply hard caps in order: max_per_domain → max_patterns → max_tokens
3. Policy: "prefer_fewer_high_confidence" (early exit, no swap-in)
4. Deterministic tie-breaking: effective_score DESC → confidence DESC → pattern_id ASC

Bootstrapping Consideration:
    Patterns with usage_count=0 receive an effective score of 0, meaning they
    will never be selected through normal ranking. This is intentional - patterns
    must demonstrate value through usage before competing with established ones.
    New patterns should be bootstrapped via: (1) manual injection during testing,
    (2) initial seeding with usage_count=1, or (3) a separate "exploration" quota.

Part of the Manifest Injection Enhancement Plan.
"""

from __future__ import annotations

import functools
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import tiktoken
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from omniclaude.hooks.handler_context_injection import PatternRecord

logger = logging.getLogger(__name__)

# =============================================================================
# Evidence Resolver Protocol (OMN-2092)
# =============================================================================


@runtime_checkable
class EvidenceResolver(Protocol):
    """Protocol for resolving gate results per pattern.

    Implementations provide the bridge between promotion gate storage
    and the injection pipeline. The sync path is kept testable by
    defaulting to NullEvidenceResolver (no file I/O).
    """

    def resolve(self, pattern_id: str) -> str | None:
        """Look up the gate_result for a pattern.

        Returns:
            "pass", "fail", "insufficient_evidence", or None if unknown.
        """
        ...


class NullEvidenceResolver:
    """Always returns None — default, preserves current behavior."""

    def resolve(self, pattern_id: str) -> str | None:
        return None


class DictEvidenceResolver:
    """Test helper — resolves from an in-memory dict."""

    def __init__(self, gates: dict[str, str]) -> None:
        self._gates = gates

    def resolve(self, pattern_id: str) -> str | None:
        return self._gates.get(pattern_id)


class FileEvidenceResolver:
    """Reads gate results from ~/.claude/baselines/ via load_latest_gate_result()."""

    def __init__(self, baselines_root: Path | None = None) -> None:
        self._baselines_root = baselines_root

    def resolve(self, pattern_id: str) -> str | None:
        from plugins.onex.hooks.lib.metrics_aggregator import load_latest_gate_result

        return load_latest_gate_result(pattern_id, baselines_root=self._baselines_root)


# =============================================================================
# Header Constant (Single Source of Truth)
# =============================================================================

# Header format for injection block - SINGLE SOURCE OF TRUTH.
# This constant is imported by handler_context_injection.py's _format_patterns_markdown()
# to ensure the header format used for token counting matches the actual output.
#
# Used for:
# 1. Token counting during pattern selection (INJECTION_HEADER_TOKENS)
# 2. Actual markdown output formatting (via import in handler_context_injection.py)
INJECTION_HEADER: str = (
    "## Learned Patterns (Auto-Injected)\n"
    "\n"
    "The following patterns have been learned from previous sessions:\n"
    "\n"
)


# =============================================================================
# Token Counting
# =============================================================================

# Use cl100k_base for deterministic token counting across models
# This is close enough to Claude's tokenization for budget enforcement

# Safety margin to account for tokenizer differences between tiktoken (cl100k_base)
# and Claude's actual tokenizer. The two tokenizers can differ by ~10-15%, so we
# apply a 90% safety margin to the configured token budget to avoid over-injection.
TOKEN_SAFETY_MARGIN: float = 0.9


@functools.lru_cache(maxsize=1)
def _get_tokenizer() -> tiktoken.Encoding:
    """Get the tokenizer (cached singleton)."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens in text using cl100k_base encoding.

    Args:
        text: The text to tokenize.

    Returns:
        Number of tokens in the text.
    """
    tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text, disallowed_special=()))


# Computed header token count - keeps header_tokens default in sync with actual header.
# This is computed once at module load time for efficiency.
INJECTION_HEADER_TOKENS: int = count_tokens(INJECTION_HEADER)


# =============================================================================
# Domain Normalization
# =============================================================================

# Known domain taxonomy for normalization
# Maps common aliases to canonical domain names
DOMAIN_ALIASES: dict[str, str] = {
    # Programming languages
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "rs": "rust",
    "go": "golang",
    "golang": "golang",
    "rb": "ruby",
    "java": "java",
    "kotlin": "kotlin",
    "kt": "kotlin",
    "swift": "swift",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "c": "c",
    # Domains
    "testing": "testing",
    "test": "testing",
    "tests": "testing",
    "review": "code_review",
    "code_review": "code_review",
    "codereview": "code_review",
    "debug": "debugging",
    "debugging": "debugging",
    "docs": "documentation",
    "documentation": "documentation",
    "infra": "infrastructure",
    "infrastructure": "infrastructure",
    "devops": "infrastructure",
    "security": "security",
    "sec": "security",
    "perf": "performance",
    "performance": "performance",
    "optimization": "performance",
    # General catch-all
    "general": "general",
    "all": "general",
}

# Set of known canonical domains for validation
KNOWN_DOMAINS: set[str] = set(DOMAIN_ALIASES.values())

# Prefix for unknown domains to group them separately
UNKNOWN_DOMAIN_PREFIX: str = "unknown/"


def normalize_domain(raw: str) -> str:
    """Normalize domain string through known taxonomy.

    Applies case-insensitive matching and alias resolution.
    Unknown domains are prefixed with "unknown/" to group them.

    Args:
        raw: Raw domain string from pattern.

    Returns:
        Normalized domain string.

    Examples:
        >>> normalize_domain("py")
        'python'
        >>> normalize_domain("Python")
        'python'
        >>> normalize_domain("custom_domain")
        'unknown/custom_domain'
    """
    lower = raw.lower().strip()

    # Check direct alias mapping
    if lower in DOMAIN_ALIASES:
        return DOMAIN_ALIASES[lower]

    # Check if already a known canonical domain
    if lower in KNOWN_DOMAINS:
        return lower

    # Unknown domain - prefix for grouping
    return f"{UNKNOWN_DOMAIN_PREFIX}{raw}"


# =============================================================================
# Effective Score Calculation
# =============================================================================


def compute_effective_score(
    confidence: float,
    success_rate: float,
    usage_count: int,
    usage_count_scale: float = 5.0,
    lifecycle_state: str | None = None,
    provisional_dampening: float = 0.5,
    gate_result: str | None = None,
    evidence_boost: float = 1.3,
    evidence_penalty: float = 0.6,
) -> float:
    """Compute effective score for pattern ranking.

    Formula: confidence * clamp(success_rate, 0..1) * f(usage_count) [* dampening] [* evidence_modifier]
    where f(usage_count) = min(1.0, log1p(usage_count) / k)

    For provisional patterns (lifecycle_state == "provisional"), the score is
    multiplied by provisional_dampening to reduce their ranking priority relative
    to validated patterns. This is part of OMN-2042: Graduated Injection Policy.

    For evidence-driven injection (OMN-2092), the score is further modified by
    gate_result: patterns with gate_result="pass" are boosted by evidence_boost
    (default 1.3x, capped at 3.0x), and patterns with gate_result="fail" are
    penalized by evidence_penalty (default 0.6x). Patterns with
    gate_result="insufficient_evidence" or None are not modified.

    This provides a composite score that considers:
    - confidence: How certain we are about the pattern
    - success_rate: Historical success when applied
    - usage_count: Experience/maturity (bounded to prevent runaway)
    - lifecycle_state: Pattern maturity (provisional patterns are dampened)
    - gate_result: Promotion gate outcome (passed patterns are boosted)

    Args:
        confidence: Pattern confidence (0.0 to 1.0).
        success_rate: Historical success rate (0.0 to 1.0).
        usage_count: Number of times pattern was used.
        usage_count_scale: Scale factor k for usage_count normalization.
            Higher values = usage_count matters less. Default 5.0.
        lifecycle_state: Pattern lifecycle state. If "provisional", the
            provisional_dampening factor is applied. Default None (treated
            as "validated", no dampening).
        provisional_dampening: Dampening factor for provisional patterns.
            Default 0.5 (matches InjectionLimitsConfig default).
            Must be >0.0 (raises ValueError otherwise);
            use include_provisional=False to disable entirely.
        gate_result: Promotion gate outcome. "pass" applies evidence_boost,
            "fail" applies evidence_penalty, "insufficient_evidence" or None
            applies no modifier. Default None.
        evidence_boost: Score multiplier for gate_result="pass". Default 1.3,
            capped at 3.0 during application.
        evidence_penalty: Score multiplier for gate_result="fail". Default 0.6,
            clamped to [0.0, 1.0] during application.

    Returns:
        Effective score (0.0 to 1.0+, can exceed 1.0 when evidence_boost > 1.0).

    Examples:
        >>> compute_effective_score(0.9, 0.8, 10)  # High confidence, good success
        0.648  # approximately
        >>> compute_effective_score(0.5, 0.5, 0)  # Low everything
        0.0  # log1p(0) = 0
        >>> compute_effective_score(0.9, 0.8, 10, lifecycle_state="provisional",
        ...     provisional_dampening=0.5)  # Provisional at half score
        0.324  # approximately
        >>> compute_effective_score(0.9, 0.8, 10, gate_result="pass",
        ...     evidence_boost=1.3)  # Evidence boost
        0.842  # approximately (0.648 * 1.3)

    Bootstrapping Note:
        Patterns with usage_count=0 will always receive a score of 0 because
        log1p(0) = 0, making the usage_factor zero and thus the entire score zero.
        This is intentional behavior - patterns must prove their value through
        actual usage before they can compete with established patterns.

        To bootstrap new patterns into the selection pool, use one of:
        1. Manual injection during initial testing/validation
        2. Seed new patterns with usage_count=1 (minimal but non-zero)
        3. Implement a separate "exploration" quota that bypasses scoring
    """
    # Clamp inputs to valid ranges
    conf = max(0.0, min(1.0, confidence))
    succ = max(0.0, min(1.0, success_rate))
    count = max(0, usage_count)

    # Usage factor: bounded monotonic function of usage_count
    # log1p(0) = 0, log1p(e^k - 1) = k, so this ranges from 0 to ~1
    # For k=5: usage_count needs to be ~147 to reach factor of 1.0
    usage_factor = min(1.0, math.log1p(count) / usage_count_scale)

    score = conf * succ * usage_factor

    # Apply provisional dampening (OMN-2042)
    if lifecycle_state == "provisional":
        if provisional_dampening <= 0.0:
            raise ValueError(
                "provisional_dampening must be > 0.0; "
                "use include_provisional=False to disable provisional patterns"
            )
        dampening = min(1.0, provisional_dampening)
        score *= dampening

    # Apply evidence modifier (OMN-2092)
    if gate_result == "pass":
        score *= min(evidence_boost, 3.0)  # cap at 3x
    elif gate_result == "fail":
        score *= max(0.0, min(1.0, evidence_penalty))
    # "insufficient_evidence" or None → no modification (1.0)

    return score


# =============================================================================
# Configuration
# =============================================================================


class InjectionLimitsConfig(BaseSettings):
    """Configuration for injection limits.

    Controls hard caps on pattern injection to prevent context explosion.
    All limits are applied in order: domain caps → count caps → token caps.

    Token Budget Safety Margin:
        The actual token budget used during selection is reduced by
        TOKEN_SAFETY_MARGIN (90%) to account for differences between tiktoken's
        cl100k_base encoding and Claude's actual tokenizer, which can differ
        by ~10-15%. For example, if max_tokens_injected=2000, the effective
        budget used is 1800 tokens.

    Environment variables use the OMNICLAUDE_INJECTION_LIMITS_ prefix:
        OMNICLAUDE_INJECTION_LIMITS_MAX_PATTERNS_PER_INJECTION
        OMNICLAUDE_INJECTION_LIMITS_MAX_TOKENS_INJECTED
        OMNICLAUDE_INJECTION_LIMITS_MAX_PER_DOMAIN
        OMNICLAUDE_INJECTION_LIMITS_SELECTION_POLICY
        OMNICLAUDE_INJECTION_LIMITS_USAGE_COUNT_SCALE

    Attributes:
        max_patterns_per_injection: Maximum number of patterns to inject.
        max_tokens_injected: Maximum tokens in rendered injection block
            (note: effective budget is reduced by TOKEN_SAFETY_MARGIN).
        max_per_domain: Maximum patterns from any single domain.
        selection_policy: Selection policy (currently only "prefer_fewer_high_confidence").
        usage_count_scale: Scale factor k for usage_count in effective score.
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_INJECTION_LIMITS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    max_patterns_per_injection: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of patterns to inject per session",
    )

    max_tokens_injected: int = Field(
        default=2000,
        ge=100,
        le=10000,
        description="Maximum tokens in rendered injection block (content + wrapper)",
    )

    max_per_domain: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum patterns from any single domain",
    )

    selection_policy: str = Field(
        default="prefer_fewer_high_confidence",
        description="Selection policy: prefer_fewer_high_confidence",
    )

    usage_count_scale: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Scale factor k for usage_count in effective score formula",
    )

    # Provisional pattern configuration (OMN-2042: Graduated Injection Policy)
    include_provisional: bool = Field(
        default=False,
        description=(
            "Include provisional (not yet fully validated) patterns in injection. "
            "When False (default), only validated patterns are injected. "
            "When True, provisional patterns are included with dampened scores "
            "and annotated with [Provisional] badge in output. "
            "NOTE: When a domain filter is active, this setting falls back to "
            "validated-only patterns with a logged warning, because domain-filtered "
            "graduated injection is not yet implemented (see OMN-2042 follow-up)."
        ),
    )

    provisional_dampening: float = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description=(
            "Dampening factor applied to provisional pattern scores. "
            "A value of 0.5 means provisional patterns compete at half "
            "their computed effective score. Range: (0.0, 1.0]. "
            "To disable provisional patterns entirely, set include_provisional=False."
        ),
    )

    max_provisional: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description=(
            "Optional hard cap on the number of provisional patterns injected. "
            "None means no cap beyond the overall max_patterns_per_injection limit."
        ),
    )

    # Evidence tier filtering (OMN-2044: Evidence Tier in Retrieval Path)
    require_measured: bool = Field(
        default=False,
        description=(
            "When True, only patterns with evidence_tier MEASURED or VERIFIED "
            "are included in injection. Patterns with UNMEASURED or None "
            "evidence_tier are filtered out. Default False (all patterns pass)."
        ),
    )

    evidence_policy: str = Field(
        default="ignore",
        description=(
            "Evidence-driven injection policy. "
            "'ignore' (default): gates not consulted, current behavior preserved. "
            "'boost': gate results modify effective scores (pass=boost, fail=penalize). "
            "'require': only patterns with gate_result='pass' are included."
        ),
    )

    evidence_boost: float = Field(
        default=1.3,
        gt=1.0,
        le=3.0,
        description=(
            "Score multiplier for patterns with gate_result='pass'. "
            "Applied when evidence_policy='boost'. Default 1.3."
        ),
    )

    evidence_penalty: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Score multiplier for patterns with gate_result='fail'. "
            "Applied when evidence_policy='boost'. Default 0.6."
        ),
    )

    @field_validator("selection_policy")
    @classmethod
    def validate_selection_policy(cls, v: str) -> str:
        """Validate that selection_policy is a known policy.

        Currently only "prefer_fewer_high_confidence" is supported.

        Args:
            v: The selection policy value to validate.

        Returns:
            The validated selection policy.

        Raises:
            ValueError: If the policy is not recognized.
        """
        allowed = {"prefer_fewer_high_confidence"}
        if v not in allowed:
            raise ValueError(
                f"Unknown selection_policy: {v!r}. Allowed: {sorted(allowed)}"
            )
        return v

    @field_validator("evidence_policy")
    @classmethod
    def validate_evidence_policy(cls, v: str) -> str:
        allowed = {"ignore", "boost", "require"}
        if v not in allowed:
            raise ValueError(
                f"Unknown evidence_policy: {v!r}. Allowed: {sorted(allowed)}"
            )
        return v

    @classmethod
    def from_env(cls) -> InjectionLimitsConfig:
        """Load configuration from environment variables."""
        return cls()


# =============================================================================
# Pattern Selection
# =============================================================================


@dataclass(frozen=True)
class ScoredPattern:
    """Pattern with computed scores for selection.

    Internal data structure used during selection. Immutable.

    Attributes:
        pattern: Original pattern record.
        effective_score: Computed composite score.
        normalized_domain: Domain after normalization.
        rendered_tokens: Token count of rendered pattern block.
        gate_result: Promotion gate outcome for evidence-driven injection (OMN-2092).
    """

    pattern: PatternRecord
    effective_score: float
    normalized_domain: str
    rendered_tokens: int
    gate_result: str | None


def render_single_pattern(
    pattern: PatternRecord, gate_result: str | None = None
) -> str:
    """Render a single pattern as markdown block.

    This is used for token counting during selection.

    IMPORTANT - Format Synchronization Required:
        The markdown format here MUST stay in sync with `_format_patterns_markdown()`
        in `handler_context_injection.py`. Both functions render patterns identically
        so that token counting during selection matches actual injection output.

        If you modify the format here, update the handler's format function too.
        If you modify the handler's format, update this function too.

    Args:
        pattern: Pattern to render.
        gate_result: Optional promotion gate outcome for evidence badge (OMN-2092).

    Returns:
        Markdown string for the pattern.
    """
    confidence_pct = f"{pattern.confidence * 100:.0f}%"
    success_pct = f"{pattern.success_rate * 100:.0f}%"

    # Annotate provisional patterns with badge (OMN-2042)
    # Annotate evidence tier with quality badge (OMN-2044)
    lifecycle = getattr(pattern, "lifecycle_state", None)
    evidence_tier = getattr(pattern, "evidence_tier", None)
    badges: list[str] = []
    if lifecycle == "provisional":
        badges.append("[Provisional]")
    if evidence_tier == "MEASURED":
        badges.append("[Measured]")
    elif evidence_tier == "VERIFIED":
        badges.append("[Verified]")
    if gate_result == "pass":
        badges.append("[Evidence: Pass]")
    elif gate_result == "fail":
        badges.append("[Evidence: Fail]")
    title_suffix = (" " + " ".join(badges)) if badges else ""

    lines = [
        f"### {pattern.title}{title_suffix}",
        "",
        f"- **Domain**: {pattern.domain}",
        f"- **Confidence**: {confidence_pct}",
        f"- **Success Rate**: {success_pct} ({pattern.usage_count} uses)",
        "",
        pattern.description,
        "",
    ]

    if pattern.example_reference:
        lines.append(f"*Example: `{pattern.example_reference}`*")
        lines.append("")

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def select_patterns_for_injection(
    candidates: list[PatternRecord],
    limits: InjectionLimitsConfig,
    *,
    header_tokens: int | None = None,
    evidence_resolver: EvidenceResolver | None = None,
) -> list[PatternRecord]:
    """Select patterns for injection applying all limits.

    Algorithm (deterministic, constraint-first):
    1. Compute effective_score and normalized_domain for each candidate
    2. Sort by: effective_score DESC, confidence DESC, pattern_id ASC
    3. Apply limits in order:
       a) max_per_domain - skip if domain quota exhausted
       b) max_patterns_per_injection - stop if count reached
       c) max_tokens_injected - skip if would exceed budget (with safety margin)

    Token Budget Safety Margin:
        The token budget check applies TOKEN_SAFETY_MARGIN (90%) to account for
        differences between tiktoken's cl100k_base encoding and Claude's actual
        tokenizer. This prevents over-injection when Claude counts more tokens
        than tiktoken for the same content.

    Policy "prefer_fewer_high_confidence":
    - Early exit once limits approached
    - Never swap in lower-scoring patterns to fill quota
    - Prefer leaving budget unused vs injecting low-signal patterns

    Evidence-Driven Injection (OMN-2092):
        When evidence_resolver is provided and limits.evidence_policy != "ignore":
        - "boost": Gate results modify effective scores (pass=boost, fail=penalize)
        - "require": Only patterns with gate_result="pass" are included (hard filter)

    Args:
        candidates: List of candidate patterns to select from.
        limits: Injection limits configuration.
        header_tokens: Token count for header/wrapper. Defaults to INJECTION_HEADER_TOKENS
            which is computed from INJECTION_HEADER to stay in sync with the actual
            header format used in handler_context_injection.py.
        evidence_resolver: Optional resolver for promotion gate results. Defaults to None
            (no evidence-driven injection).

    Returns:
        Selected patterns in injection order (highest score first).

    Examples:
        >>> limits = InjectionLimitsConfig(max_patterns_per_injection=3)
        >>> selected = select_patterns_for_injection(patterns, limits)
        >>> len(selected) <= 3
        True
    """
    # TODO(OMN-1671): Policy dispatch not yet implemented.
    #
    # Currently only "prefer_fewer_high_confidence" is implemented, and the behavior
    # is hardcoded below. The limits.selection_policy field is validated on config
    # construction (see InjectionLimitsConfig.validate_selection_policy) but not
    # actually checked here.
    #
    # When adding new policies (e.g., "maximize_diversity", "fill_token_budget"):
    # 1. Add the policy name to the allowed set in validate_selection_policy()
    # 2. Add a policy dispatch here, e.g.:
    #        if limits.selection_policy == "maximize_diversity":
    #            return _select_maximize_diversity(candidates, limits, ...)
    # 3. Extract current logic to _select_prefer_fewer_high_confidence()

    if not candidates:
        return []

    # Pre-filter: exclude unmeasured patterns when require_measured=True (OMN-2044)
    if limits.require_measured:
        before_count = len(candidates)
        measured_tiers = {"MEASURED", "VERIFIED"}
        candidates = [
            p for p in candidates if getattr(p, "evidence_tier", None) in measured_tiers
        ]
        filtered_count = before_count - len(candidates)
        if filtered_count > 0:
            logger.debug(
                "Filtered out %d unmeasured patterns (require_measured=True)",
                filtered_count,
            )
        if not candidates:
            return []

    # Pre-filter: exclude provisional patterns when include_provisional=False (OMN-2042)
    # This is the single enforcement point for both DB and file sources.
    if not limits.include_provisional:
        before_count = len(candidates)
        candidates = [
            p
            for p in candidates
            if getattr(p, "lifecycle_state", None) != "provisional"
        ]
        filtered_count = before_count - len(candidates)
        if filtered_count > 0:
            logger.debug(
                "Filtered out %d provisional patterns (include_provisional=False)",
                filtered_count,
            )
        if not candidates:
            return []

    # Use computed header tokens if not explicitly provided
    # This keeps the default in sync with INJECTION_HEADER constant
    effective_header_tokens = (
        header_tokens if header_tokens is not None else INJECTION_HEADER_TOKENS
    )

    # Step 1: Score and normalize all candidates
    scored: list[ScoredPattern] = []
    for pattern in candidates:
        # Pass lifecycle_state and provisional_dampening for graduated injection (OMN-2042)
        pattern_lifecycle = getattr(pattern, "lifecycle_state", None)

        # Evidence resolution (OMN-2092)
        gate_result: str | None = None
        if evidence_resolver is not None and limits.evidence_policy != "ignore":
            gate_result = evidence_resolver.resolve(pattern.pattern_id)

        effective_score = compute_effective_score(
            confidence=pattern.confidence,
            success_rate=pattern.success_rate,
            usage_count=pattern.usage_count,
            usage_count_scale=limits.usage_count_scale,
            lifecycle_state=pattern_lifecycle,
            provisional_dampening=limits.provisional_dampening,
            gate_result=gate_result,
            evidence_boost=limits.evidence_boost,
            evidence_penalty=limits.evidence_penalty,
        )
        normalized_domain = normalize_domain(pattern.domain)
        rendered = render_single_pattern(pattern, gate_result=gate_result)
        rendered_tokens = count_tokens(rendered)

        scored.append(
            ScoredPattern(
                pattern=pattern,
                effective_score=effective_score,
                normalized_domain=normalized_domain,
                rendered_tokens=rendered_tokens,
                gate_result=gate_result,
            )
        )

    # Evidence policy: require (OMN-2092) — filter AFTER scoring, BEFORE sorting
    if limits.evidence_policy == "require" and evidence_resolver is not None:
        before_count = len(scored)
        scored = [s for s in scored if s.gate_result == "pass"]
        filtered_count = before_count - len(scored)
        if filtered_count > 0:
            logger.debug(
                "Filtered out %d patterns without gate_result='pass' (evidence_policy='require')",
                filtered_count,
            )
        if not scored:
            return []

    # Step 2: Deterministic sort
    # Primary: effective_score DESC
    # Secondary: confidence DESC
    # Tertiary: pattern_id ASC (stable tie-breaker)
    scored.sort(
        key=lambda s: (-s.effective_score, -s.pattern.confidence, s.pattern.pattern_id)
    )

    # Step 3: Apply limits with greedy selection
    selected: list[PatternRecord] = []
    domain_counts: dict[str, int] = {}
    provisional_count = (
        0  # Track provisional patterns for max_provisional cap (OMN-2042)
    )
    total_tokens = effective_header_tokens  # Start with header overhead

    # Apply safety margin to token budget to account for tokenizer differences
    budget = limits.max_tokens_injected * TOKEN_SAFETY_MARGIN
    effective_token_budget = int(budget)

    for scored_pattern in scored:
        # Check max_patterns_per_injection (hard stop)
        if len(selected) >= limits.max_patterns_per_injection:
            logger.debug(
                f"Selection stopped: max_patterns ({limits.max_patterns_per_injection}) reached"
            )
            break

        # Check max_per_domain (skip this pattern)
        domain = scored_pattern.normalized_domain
        current_domain_count = domain_counts.get(domain, 0)
        if current_domain_count >= limits.max_per_domain:
            logger.debug(
                f"Skipping pattern {scored_pattern.pattern.pattern_id}: "
                f"domain '{domain}' at cap ({limits.max_per_domain})"
            )
            continue

        # Check max_provisional cap (OMN-2042: skip provisional if cap reached)
        pattern_lifecycle = getattr(scored_pattern.pattern, "lifecycle_state", None)
        if pattern_lifecycle == "provisional" and limits.max_provisional is not None:
            if provisional_count >= limits.max_provisional:
                logger.debug(
                    f"Skipping pattern {scored_pattern.pattern.pattern_id}: "
                    f"provisional cap ({limits.max_provisional}) reached"
                )
                continue

        # Check max_tokens_injected (skip this pattern, try next)
        # Patterns are sorted by descending effective_score. If a high-token pattern
        # exceeds budget, we skip it and try subsequent (lower-scored but possibly
        # smaller) patterns that may still fit within the remaining budget.
        # NOTE: Uses effective_token_budget (with safety margin) to account for
        # tokenizer differences between tiktoken and Claude's actual tokenizer.
        new_total = total_tokens + scored_pattern.rendered_tokens
        if new_total > effective_token_budget:
            logger.debug(
                f"Skipping pattern {scored_pattern.pattern.pattern_id}: "
                f"would exceed token budget ({new_total} > {effective_token_budget})"
            )
            continue

        # Pattern passes all checks - select it
        selected.append(scored_pattern.pattern)
        domain_counts[domain] = current_domain_count + 1
        total_tokens = new_total
        if pattern_lifecycle == "provisional":
            provisional_count += 1

        logger.debug(
            f"Selected pattern {scored_pattern.pattern.pattern_id}: "
            f"score={scored_pattern.effective_score:.3f}, "
            f"domain={domain}, tokens={scored_pattern.rendered_tokens}"
        )

    logger.info(
        f"Pattern selection complete: {len(selected)}/{len(candidates)} patterns, "
        f"{total_tokens} tokens"
    )

    return selected


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Configuration
    "InjectionLimitsConfig",
    # Functions
    "select_patterns_for_injection",
    "compute_effective_score",
    "normalize_domain",
    "count_tokens",
    "render_single_pattern",
    # Evidence Resolution (OMN-2092)
    "EvidenceResolver",
    "NullEvidenceResolver",
    "FileEvidenceResolver",
    "DictEvidenceResolver",
    # Constants
    "DOMAIN_ALIASES",
    "KNOWN_DOMAINS",
    "UNKNOWN_DOMAIN_PREFIX",
    "TOKEN_SAFETY_MARGIN",
    "INJECTION_HEADER",
    "INJECTION_HEADER_TOKENS",
    # Internal (for testing)
    "ScoredPattern",
]
