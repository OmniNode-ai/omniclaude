#!/usr/bin/env python3
"""
Agent Router - Standalone Routing Module
========================================

Local agent routing with trigger matching and confidence scoring.
Works standalone without external service dependencies.

Flow:
1. Check for explicit agent request (@agent-name or "use agent-X")
2. Check cache for previous results
3. Fuzzy trigger matching with scoring
4. Comprehensive confidence scoring
5. Sort and rank recommendations
6. Cache results
7. Return top N recommendations

Performance Targets:
- Total routing time: <100ms
- Cache hit: <5ms
- Cache miss: <100ms
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# Path Resolution
# =============================================================================


# Sensitive system directories that must never be used as agent config paths.
# Safety invariant — changes require code review.
_SENSITIVE_PREFIXES = frozenset(
    {
        "/etc",
        "/var/log",
        "/var/run",
        "/var/lib",
        "/var/cache",
        "/var/spool",
        "/usr/bin",
        "/usr/sbin",
        "/usr/lib",
        "/usr/local/bin",
        "/usr/local/sbin",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/root",
        "/proc",
        "/sys",
        "/dev",
        "/boot",
        "/private/etc",
        "/private/var/log",
        "/private/var/run",
        "/System",
        "/Library/LaunchDaemons",
        "/Library/LaunchAgents",
    }
)


# Safety invariant for candidate filtering. Not agent- or registry-configurable.
# Changes require code review. See docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md.
HARD_FLOOR = 0.55


def _resolve_agent_configs_dir() -> Path:
    """
    Resolve the agent configs directory for routing.

    Resolution order:
    1. CLAUDE_PLUGIN_ROOT/agents/configs (if set and valid)
    2. Script-relative path detection
    3. Legacy fallback (~/.claude/agents/omniclaude)

    Returns:
        Path to the agent configs directory
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()

    if plugin_root:
        plugin_path = Path(plugin_root)
        # Security: reject sensitive system directories
        try:
            resolved = str(plugin_path.resolve())
            if any(
                resolved == s or resolved.startswith(s + "/")
                for s in _SENSITIVE_PREFIXES
            ):
                logger.warning(
                    f"CLAUDE_PLUGIN_ROOT points to sensitive directory: {plugin_root}"
                )
                plugin_root = ""  # Fall through to script-relative detection
        except (OSError, ValueError):
            plugin_root = ""

    if plugin_root:
        plugin_path = Path(plugin_root)
        agents_dir = plugin_path / "agents" / "configs"
        if agents_dir.exists() and agents_dir.is_dir():
            return agents_dir

    # Fallback: try to detect from script location
    script_dir = Path(__file__).parent
    possible_plugin_root = script_dir.parent.parent  # hooks/lib -> hooks -> plugin_root
    possible_agents_dir = possible_plugin_root / "agents" / "configs"

    if possible_agents_dir.exists() and possible_agents_dir.is_dir():
        return possible_agents_dir

    # Legacy fallback
    legacy_dir = Path.home() / ".claude" / "agents" / "omniclaude"
    return legacy_dir


AGENT_CONFIGS_DIR = _resolve_agent_configs_dir()


# =============================================================================
# Confidence Scoring
# =============================================================================


@dataclass
class ConfidenceScore:
    """
    Confidence score with detailed breakdown.

    Attributes:
        total: Overall confidence (0.0-1.0)
        trigger_score: Trigger matching score (0.0-1.0)
        context_score: Context alignment score (0.0-1.0)
        capability_score: Capability match score (0.0-1.0)
        historical_score: Historical success score (0.0-1.0)
        explanation: Human-readable explanation
    """

    total: float
    trigger_score: float
    context_score: float
    capability_score: float
    historical_score: float
    explanation: str


class ConfidenceScorer:
    """
    Calculate confidence scores for agent matches.

    Uses weighted scoring across multiple dimensions:
    - Trigger match quality (40%)
    - Context alignment (30%)
    - Capability relevance (20%)
    - Historical performance (10%)
    """

    WEIGHT_TRIGGER = 0.4
    WEIGHT_CONTEXT = 0.3
    WEIGHT_CAPABILITY = 0.2
    WEIGHT_HISTORICAL = 0.1

    def __init__(self) -> None:
        """Initialize confidence scorer."""
        self.historical_success: dict[str, dict[str, float]] = {}

    def score(
        self,
        agent_name: str,
        agent_data: dict[str, Any],
        user_request: str,
        context: dict[str, Any],
        trigger_score: float,
    ) -> ConfidenceScore:
        """
        Calculate comprehensive confidence score.

        Args:
            agent_name: Name of the agent being scored
            agent_data: Agent metadata from registry
            user_request: User's input text
            context: Current execution context
            trigger_score: Pre-calculated trigger match score

        Returns:
            ConfidenceScore object with breakdown and explanation
        """
        weighted_trigger = trigger_score * self.WEIGHT_TRIGGER

        context_score = self._calculate_context_score(agent_data, context)
        weighted_context = context_score * self.WEIGHT_CONTEXT

        capability_score = self._calculate_capability_score(agent_data, user_request)
        weighted_capability = capability_score * self.WEIGHT_CAPABILITY

        historical_score = self._calculate_historical_score(agent_name)
        weighted_historical = historical_score * self.WEIGHT_HISTORICAL

        total = (
            weighted_trigger
            + weighted_context
            + weighted_capability
            + weighted_historical
        )

        explanation = self._generate_explanation(
            agent_name, trigger_score, context_score, capability_score, historical_score
        )

        return ConfidenceScore(
            total=total,
            trigger_score=trigger_score,
            context_score=context_score,
            capability_score=capability_score,
            historical_score=historical_score,
            explanation=explanation,
        )

    def _calculate_context_score(
        self, agent_data: dict[str, Any], context: dict[str, Any]
    ) -> float:
        """Score based on context alignment."""
        agent_context = agent_data.get("domain_context", "general")
        current_context = context.get("domain", "general")

        if agent_context == current_context:
            return 1.0
        elif agent_context == "general" or current_context == "general":
            return 0.7
        else:
            return 0.4

    def _calculate_capability_score(
        self, agent_data: dict[str, Any], request: str
    ) -> float:
        """Score based on capability match."""
        capabilities = agent_data.get("capabilities", [])

        if not capabilities:
            return 0.5

        request_lower = request.lower()
        matches = sum(1 for cap in capabilities if cap.lower() in request_lower)

        return min(matches / len(capabilities), 1.0)

    def _calculate_historical_score(self, agent_name: str) -> float:
        """Score based on historical success (default 0.5 if no data)."""
        if agent_name not in self.historical_success:
            return 0.5
        result = self.historical_success[agent_name].get("overall", 0.5)
        return float(result) if result is not None else 0.5

    def _generate_explanation(
        self,
        agent_name: str,
        trigger_score: float,
        context_score: float,
        capability_score: float,
        historical_score: float,
    ) -> str:
        """Generate human-readable explanation."""
        parts = []

        if trigger_score > 0.8:
            parts.append("Strong trigger match")
        elif trigger_score > 0.6:
            parts.append("Good trigger match")
        else:
            parts.append("Moderate trigger match")

        if context_score > 0.8:
            parts.append("perfect context alignment")
        elif context_score > 0.6:
            parts.append("good context fit")

        if capability_score > 0.6:
            parts.append("relevant capabilities")

        if historical_score > 0.7:
            parts.append("proven track record")

        return f"{agent_name}: {', '.join(parts)}"


# =============================================================================
# Trigger Matching
# =============================================================================


class TriggerMatcher:
    """
    Advanced trigger matching with fuzzy logic and scoring.

    Uses multiple matching strategies:
    - Exact substring matching
    - Fuzzy string similarity (SequenceMatcher)
    - Keyword overlap scoring
    - Capability matching
    """

    # Common stopwords to filter from keywords
    STOPWORDS = frozenset(
        {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "should",
            "could",
            "may",
            "might",
            "must",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "its",
            "our",
            "their",
        }
    )

    # Pre-compiled technical patterns that indicate discussion ABOUT agents
    # rather than an agent invocation request (avoids recompilation per call)
    _TECHNICAL_PATTERNS = [
        re.compile(
            r"\bpolymorphic\s+(architecture|design|pattern|approach|system|code|style)\b"
        ),
        re.compile(r"\bpolymorphism\b"),
        re.compile(r"\bpollyanna\b"),
        re.compile(
            r"\b(the|a|an)\s+polymorphic\s+(design|pattern|architecture|approach)\b"
        ),
        re.compile(r"\busing\s+polymorphi"),
        re.compile(r"\b(poly|polly)\s+(suggested|mentioned|said|thinks|believes)\b"),
    ]

    # High-confidence technical triggers that don't need action context.
    # NOTE: Some terms overlap with TransformationValidator.SPECIALIZED_KEYWORDS
    # and TaskClassifier.INTENT_KEYWORDS by design -- each collection serves a
    # different purpose (context gating vs. validation vs. intent classification).
    HIGH_CONFIDENCE_TRIGGERS = frozenset(
        {
            "debug",
            "error",
            "bug",
            "troubleshoot",
            "investigate",
            "diagnose",
            "fix",
            "resolve",
            "issue",
            "problem",
            "failure",
            "crash",
            "test",
            "testing",
            "quality",
            "coverage",
            "validate",
            "verify",
            "optimize",
            "performance",
            "benchmark",
            "bottleneck",
            "profile",
            "efficiency",
            "speed",
            "slow",
            "latency",
            "security",
            "audit",
            "vulnerability",
            "penetration",
            "compliance",
            "threat",
            "risk",
            "secure",
            "deploy",
            "deployment",
            "infrastructure",
            "devops",
            "pipeline",
            "container",
            "kubernetes",
            "docker",
            "monitor",
            "observability",
            "document",
            "docs",
            "research",
            "analyze",
            "analysis",
            "api",
            "endpoint",
            "microservice",
            "architecture",
            "design",
            "frontend",
            "backend",
            "react",
            "typescript",
            "python",
            "fastapi",
        }
    )

    # Short alphanumeric technical tokens that should be preserved during
    # keyword extraction even when below the default length threshold.
    # These tokens are domain-significant (e.g., cloud services, protocols).
    _TECHNICAL_TOKENS = frozenset(  # secret-ok: domain keyword tokens
        {"s3", "k8", "ec2", "ml", "ai", "ci", "cd", "db"}
    )

    def __init__(self, agent_registry: dict[str, Any]) -> None:
        """
        Initialize matcher with agent registry.

        Args:
            agent_registry: Registry dict with 'agents' key containing agent definitions
        """
        self.registry = agent_registry
        self.trigger_index = self._build_trigger_index()

    def _build_trigger_index(self) -> dict[str, list[str]]:
        """Build inverted index of triggers -> agent names."""
        index: dict[str, list[str]] = {}
        for agent_name, agent_data in self.registry.get("agents", {}).items():
            triggers = agent_data.get("activation_triggers", [])
            for trigger in triggers:
                trigger_lower = trigger.lower()
                if trigger_lower not in index:
                    index[trigger_lower] = []
                index[trigger_lower].append(agent_name)
        return index

    def match(self, user_request: str) -> list[tuple[str, float, str]]:
        """
        Match user request against agent triggers.

        Args:
            user_request: User's input text

        Returns:
            List of (agent_name, confidence_score, match_reason)
            Sorted by confidence (highest first)
        """
        user_lower = user_request.lower()
        matches: list[tuple[str, float, str]] = []

        keywords = self._extract_keywords(user_request)

        # Sort agents by name for deterministic iteration order.
        # See docs/proposals/FUZZY_MATCHER_IMPROVEMENTS.md (Determinism Guarantees).
        for agent_name, agent_data in sorted(self.registry.get("agents", {}).items()):
            triggers = agent_data.get("activation_triggers", [])
            scores: list[tuple[float, str]] = []

            # 1. Exact trigger match with word boundary checks
            for trigger in triggers:
                if self._exact_match_with_word_boundaries(trigger, user_lower):
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        scores.append((1.0, f"Exact match: '{trigger}'"))

            # 2. Fuzzy trigger match (tiered thresholds, multi-word bonus)
            for trigger in triggers:
                similarity = self._fuzzy_match(trigger.lower(), user_lower)
                if similarity > 0.7:
                    if self._is_context_appropriate(trigger, user_request, agent_name):
                        # Multi-word triggers are more specific -> monotonic bonus
                        word_count = len(trigger.split())
                        specificity_bonus = (
                            min(math.log(word_count) * 0.05, 0.08)
                            if word_count > 1
                            else 0.0
                        )
                        rank_score = similarity * 0.9 + specificity_bonus
                        scores.append(
                            (
                                rank_score,
                                f"Fuzzy match: '{trigger}' ({similarity:.0%})",
                            )
                        )

            # 3. Keyword overlap
            keyword_score = self._keyword_overlap_score(keywords, triggers)
            if keyword_score > 0.5:
                scores.append(
                    (keyword_score * 0.8, f"Keyword overlap ({keyword_score:.0%})")
                )

            # 4. Capability match
            capabilities = agent_data.get("capabilities", [])
            cap_score = self._capability_match_score(keywords, capabilities)
            if cap_score > 0.5:
                scores.append((cap_score * 0.7, f"Capability match ({cap_score:.0%})"))

            if scores:
                best_score, reason = max(scores, key=lambda x: x[0])
                matches.append((agent_name, best_score, reason))

        # Hard floor: remove matches below noise threshold.
        # HARD_FLOOR is a safety invariant, not a tuning knob.
        matches = [
            (name, score, reason)
            for name, score, reason in matches
            if score >= HARD_FLOOR
        ]

        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract meaningful keywords from text.

        Preserves short alphanumeric technical tokens (e.g., "s3", "k8", "ec2")
        that would otherwise be dropped by the length filter.
        """
        words = re.findall(r"\b\w+\b", text.lower())
        return [
            w
            for w in words
            if w not in self.STOPWORDS and (len(w) > 2 or w in self._TECHNICAL_TOKENS)
        ]

    @staticmethod
    def _fuzzy_threshold(trigger: str) -> float:
        """Dynamic threshold: shorter triggers need higher similarity.

        Short words (<=6 chars) like "react", "debug" have high character
        overlap with unrelated words. Longer triggers are more specific.
        """
        n = len(trigger)
        if n <= 6:
            return 0.85
        elif n <= 10:
            return 0.78
        else:
            return 0.72

    def _fuzzy_match(self, trigger: str, text: str) -> float:
        """Calculate fuzzy match score using SequenceMatcher.

        Uses tiered thresholds based on trigger length to prevent
        false positives from short-word character overlap.
        Full-text comparison is intentionally omitted (pure noise).
        Terminates early on perfect word match to avoid unnecessary iteration.
        """
        if self._exact_match_with_word_boundaries(trigger, text):
            return 1.0

        min_threshold = self._fuzzy_threshold(trigger)

        words = re.findall(r"\b\w+\b", text.lower())
        best_word_score = 0.0
        for word in words:
            word_score = SequenceMatcher(None, trigger, word).ratio()
            if word_score >= min_threshold:
                best_word_score = max(best_word_score, word_score)
                if best_word_score >= 1.0:
                    break  # Perfect match; no further iteration needed

        return best_word_score

    def _keyword_overlap_score(self, keywords: list[str], triggers: list[str]) -> float:
        """Calculate keyword overlap score."""
        if not keywords or not triggers:
            return 0.0

        trigger_words = set()
        for trigger in triggers:
            trigger_words.update(re.findall(r"\b\w+\b", trigger.lower()))

        keyword_set = set(keywords)
        overlap = len(keyword_set & trigger_words)
        return overlap / len(keyword_set) if keyword_set else 0.0

    def _capability_match_score(
        self, keywords: list[str], capabilities: list[str]
    ) -> float:
        """Calculate capability match score."""
        if not keywords or not capabilities:
            return 0.0

        capability_words = set()
        for cap in capabilities:
            capability_words.update(re.findall(r"\b\w+\b", cap.lower()))

        keyword_set = set(keywords)
        overlap = len(keyword_set & capability_words)
        return overlap / len(keyword_set) if keyword_set else 0.0

    def _exact_match_with_word_boundaries(self, trigger: str, text: str) -> bool:
        """Check if trigger matches with word boundaries."""
        trigger_lower = trigger.lower()
        pattern = r"\b" + re.escape(trigger_lower) + r"\b"
        return bool(re.search(pattern, text))

    def _is_context_appropriate(
        self, trigger: str, user_request: str, agent_name: str
    ) -> bool:
        """Check if trigger match is contextually appropriate."""
        trigger_lower = trigger.lower()
        request_lower = user_request.lower()

        # High-confidence triggers always match
        if trigger_lower in self.HIGH_CONFIDENCE_TRIGGERS:
            return True

        # Technical/architectural patterns indicate NOT an agent invocation
        for pattern in self._TECHNICAL_PATTERNS:
            if pattern.search(request_lower):
                return False

        # Multi-word triggers are high confidence
        if len(trigger_lower.split()) > 1:
            return True

        # Longer single-word triggers need action context
        if len(trigger_lower) > 6:
            action_patterns = [
                r"\b(use|spawn|dispatch|coordinate|invoke|call|run|execute|trigger)\b.*\b"
                + re.escape(trigger_lower)
                + r"\b",
                r"\b"
                + re.escape(trigger_lower)
                + r"\b.*(agent|coordinator|for workflow)",
            ]
            for pattern in action_patterns:
                if re.search(pattern, request_lower):
                    return True
            return False

        # Short triggers require action context
        action_patterns = [
            r"\b(use|spawn|dispatch|coordinate|invoke|call|run|execute|trigger)\b.*\b"
            + re.escape(trigger_lower)
            + r"\b",
            r"\b"
            + re.escape(trigger_lower)
            + r"\b.*(coordinate|manage|handle|execute|for workflow)",
        ]

        for pattern in action_patterns:
            if re.search(pattern, request_lower):
                return True

        return False


# =============================================================================
# Result Cache
# =============================================================================


class ResultCache:
    """
    Simple in-memory cache with TTL for routing results.

    Features:
    - Hash-based key generation
    - Time-to-live (TTL) expiration
    - Hit/miss tracking
    """

    def __init__(
        self, default_ttl_seconds: int = 3600, max_entries: int = 1000
    ) -> None:
        """
        Initialize cache.

        Args:
            default_ttl_seconds: Default time-to-live in seconds (default: 1 hour)
            max_entries: Maximum number of cache entries before LRU eviction (default: 1000)
        """
        self._lock = threading.Lock()
        self.cache: dict[str, dict[str, Any]] = {}
        self.default_ttl = default_ttl_seconds
        self.max_entries = max_entries

    def _generate_key(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Generate cache key from query and context."""
        key_data = query
        if context:
            try:
                key_data += str(sorted(context.items()))
            except TypeError:
                # Unhashable or uncomparable context values; fall back to repr
                key_data += repr(context)
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, query: str, context: dict[str, Any] | None = None) -> Any | None:
        """Get cached result if valid."""
        key = self._generate_key(query, context)

        with self._lock:
            if key not in self.cache:
                return None

            entry = self.cache[key]

            if time.time() > entry["expires_at"]:
                del self.cache[key]
                return None

            entry["hits"] += 1
            entry["last_accessed"] = time.time()

            return entry["value"]

    def _evict_lru(self) -> None:
        """Evict least-recently-accessed entries when cache exceeds max_entries."""
        while len(self.cache) >= self.max_entries:
            oldest_key = min(self.cache, key=lambda k: self.cache[k]["last_accessed"])
            del self.cache[oldest_key]

    def set(
        self,
        query: str,
        value: Any,
        context: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache result with TTL."""
        key = self._generate_key(query, context)
        ttl = ttl_seconds or self.default_ttl

        with self._lock:
            # Evict LRU entries if at capacity (skip if updating existing key)
            if key not in self.cache:
                self._evict_lru()

            current_time = time.time()
            self.cache[key] = {
                "value": value,
                "created_at": current_time,
                "expires_at": current_time + ttl,
                "last_accessed": current_time,
                "hits": 0,
            }

    def clear(self) -> None:
        """Clear entire cache."""
        with self._lock:
            self.cache.clear()

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            if not self.cache:
                return {
                    "entries": 0,
                    "total_hits": 0,
                    "avg_hits_per_entry": 0.0,
                }

            total_hits = sum(entry["hits"] for entry in self.cache.values())
            total_entries = len(self.cache)

            return {
                "entries": total_entries,
                "total_hits": total_hits,
                "avg_hits_per_entry": total_hits / total_entries
                if total_entries
                else 0,
            }


# =============================================================================
# Agent Recommendation
# =============================================================================


@dataclass
class AgentRecommendation:
    """
    Agent recommendation with confidence.

    Attributes:
        agent_name: Internal agent identifier
        agent_title: Human-readable agent title
        confidence: Detailed confidence breakdown
        reason: Primary match reason
        definition_path: Path to agent definition file
    """

    agent_name: str
    agent_title: str
    confidence: ConfidenceScore
    reason: str
    definition_path: str
    is_explicit: bool = False


@dataclass
class RoutingTiming:
    """
    Performance timing data for routing operations.

    All timings in microseconds for high precision.
    """

    total_routing_time_us: int
    cache_lookup_us: int
    trigger_matching_us: int
    confidence_scoring_us: int
    cache_hit: bool


# =============================================================================
# Agent Router
# =============================================================================


def _build_registry_from_configs(configs_dir: Path) -> dict[str, Any]:
    """
    Build a registry dict from individual agent YAML files.

    Args:
        configs_dir: Path to directory containing agent YAML files

    Returns:
        Registry dict with 'agents' key
    """
    registry: dict[str, Any] = {"agents": {}}

    if not configs_dir.exists():
        logger.warning(f"Agent configs directory not found: {configs_dir}")
        return registry

    for yaml_file in sorted(configs_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                agent_data = yaml.safe_load(f)

            if not agent_data:
                continue

            # Extract agent name from file or from YAML content
            agent_name = yaml_file.stem
            if not agent_name.startswith("agent-"):
                agent_name = f"agent-{agent_name}"

            # Validate agent name (alphanumeric, hyphens, underscores only)
            if not re.match(r"^[a-zA-Z0-9_-]+$", agent_name):
                logger.warning(
                    f"Skipping agent with invalid name '{agent_name}' from {yaml_file}"
                )
                continue

            # Build registry entry
            registry["agents"][agent_name] = {
                "title": agent_data.get("agent_identity", {}).get("name", agent_name),
                "description": agent_data.get("agent_identity", {}).get(
                    "description", ""
                ),
                "definition_path": str(yaml_file),
                "activation_triggers": _extract_triggers(agent_data),
                "capabilities": _flatten_capabilities(
                    agent_data.get("capabilities", [])
                ),
                "domain_context": agent_data.get("domain_context", "general"),
            }

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse {yaml_file}: {e}")
        except Exception as e:
            logger.warning(f"Error loading {yaml_file}: {e}")

    logger.debug(f"Built registry with {len(registry['agents'])} agents")
    return registry


def _flatten_capabilities(capabilities: Any) -> list[str]:
    """Flatten YAML capabilities structure into a list of strings.

    Agent YAML defines capabilities as a nested dict with keys like
    'primary', 'secondary', 'specialized' each containing a list of strings.
    This flattens that into a single list for scoring.
    """
    if isinstance(capabilities, list):
        return capabilities
    if isinstance(capabilities, dict):
        flat: list[str] = []
        for value in capabilities.values():
            if isinstance(value, list):
                flat.extend(str(item) for item in value)
            elif isinstance(value, str):
                flat.append(value)
        return flat
    return []


def _extract_triggers(agent_data: dict[str, Any]) -> list[str]:
    """Extract activation triggers from agent YAML data.

    Agent YAML files use various key names under activation_patterns.
    This extracts triggers from ALL known variants to ensure routing works
    regardless of which schema convention the YAML author used.
    """
    triggers: list[str] = []

    # Check activation_patterns - extract from ALL known sub-key variants
    activation_patterns = agent_data.get("activation_patterns", {})
    if isinstance(activation_patterns, dict):
        # Trigger keys used across agent YAMLs
        trigger_keys = (
            "explicit_triggers",
            "primary_triggers",
            "automatic_triggers",
            "auto_activation_triggers",
            "trigger_keywords",
            "trigger_conditions",
            "triggers",
            "activation_keywords",
            "domain_keywords",
        )
        # Context keys used across agent YAMLs
        context_keys = (
            "context_triggers",
            "context_indicators",
            "context_requirements",
            "contextual_patterns",
        )
        for key in trigger_keys + context_keys:
            value = activation_patterns.get(key, [])
            if isinstance(value, list):
                triggers.extend(str(item) for item in value)
            elif isinstance(value, dict):
                # Handle nested dicts (e.g., triggers: {primary: [...], domain_specific: [...]})
                for sub_value in value.values():
                    if isinstance(sub_value, list):
                        triggers.extend(str(item) for item in sub_value)

    # Check top-level activation_triggers
    if "activation_triggers" in agent_data:
        triggers.extend(agent_data["activation_triggers"])

    # Check top-level triggers (alternative YAML convention)
    if "triggers" in agent_data:
        value = agent_data["triggers"]
        if isinstance(value, list):
            triggers.extend(str(item) for item in value)
        elif isinstance(value, dict):
            for sub_value in value.values():
                if isinstance(sub_value, list):
                    triggers.extend(str(item) for item in sub_value)

    # Check agent_identity for keywords
    identity = agent_data.get("agent_identity", {})
    if "keywords" in identity:
        triggers.extend(identity["keywords"])

    return triggers


class AgentRouter:
    """
    Agent routing with confidence scoring and caching.

    Combines fuzzy matching, confidence scoring, and result caching
    to provide intelligent agent recommendations.
    """

    def __init__(
        self,
        configs_dir: Path | str | None = None,
        cache_ttl: int = 3600,
    ) -> None:
        """
        Initialize router.

        Args:
            configs_dir: Path to agent configs directory (uses default if None)
            cache_ttl: Cache time-to-live in seconds (default: 1 hour)
        """
        if configs_dir is None:
            configs_dir = AGENT_CONFIGS_DIR
        elif isinstance(configs_dir, str):
            configs_dir = Path(configs_dir)

        self.configs_dir = configs_dir

        # Build registry from individual YAML files
        self.registry = _build_registry_from_configs(configs_dir)

        if not self.registry["agents"]:
            logger.warning(f"No agents found in {configs_dir}")

        # Initialize components
        self.trigger_matcher = TriggerMatcher(self.registry)
        self.confidence_scorer = ConfidenceScorer()
        self.cache = ResultCache(default_ttl_seconds=cache_ttl)

        # Lock protecting routing_stats and last_routing_timing from
        # concurrent mutation in multi-threaded environments.
        self._stats_lock = threading.Lock()

        # Track routing stats
        self.routing_stats: dict[str, int] = {
            "total_routes": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "explicit_requests": 0,
            "fuzzy_matches": 0,
        }

        # Track performance timing for most recent route
        self.last_routing_timing: RoutingTiming | None = None

        logger.info(
            f"AgentRouter initialized with {len(self.registry['agents'])} agents"
        )

    def route(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
    ) -> list[AgentRecommendation]:
        """
        Route user request to best agent(s).

        Performance timing is captured and stored in self.last_routing_timing.

        Args:
            user_request: User's input text
            context: Optional execution context (domain, previous agent, etc.)
            max_recommendations: Maximum number of recommendations to return

        Returns:
            List of agent recommendations sorted by confidence (highest first)
        """
        try:
            routing_start_us = time.perf_counter_ns() // 1000

            with self._stats_lock:
                self.routing_stats["total_routes"] += 1
            context = context or {}

            logger.debug(f"Routing request: {user_request[:100]}...")

            # Track timing for cache lookup
            cache_lookup_start_us = time.perf_counter_ns() // 1000

            # 1. Check cache
            cached = self.cache.get(user_request, context)
            cache_lookup_end_us = time.perf_counter_ns() // 1000
            cache_lookup_time_us = cache_lookup_end_us - cache_lookup_start_us

            if cached is not None:
                routing_end_us = time.perf_counter_ns() // 1000
                with self._stats_lock:
                    self.routing_stats["cache_hits"] += 1
                    self.last_routing_timing = RoutingTiming(
                        total_routing_time_us=routing_end_us - routing_start_us,
                        cache_lookup_us=cache_lookup_time_us,
                        trigger_matching_us=0,
                        confidence_scoring_us=0,
                        cache_hit=True,
                    )
                logger.debug(
                    f"Cache hit - returning {len(cached)} cached recommendations"
                )

                return cached  # type: ignore[return-value]

            with self._stats_lock:
                self.routing_stats["cache_misses"] += 1

            # 2. Check for explicit agent request
            explicit_agent = self._extract_explicit_agent(user_request)
            if explicit_agent:
                with self._stats_lock:
                    self.routing_stats["explicit_requests"] += 1
                recommendation = self._create_explicit_recommendation(explicit_agent)
                if recommendation:
                    result = [recommendation]
                    self.cache.set(user_request, result, context)
                    logger.info(f"Explicit agent request: {explicit_agent}")

                    routing_end_us = time.perf_counter_ns() // 1000
                    with self._stats_lock:
                        self.last_routing_timing = RoutingTiming(
                            total_routing_time_us=routing_end_us - routing_start_us,
                            cache_lookup_us=cache_lookup_time_us,
                            trigger_matching_us=0,
                            confidence_scoring_us=0,
                            cache_hit=False,
                        )

                    return result

            # 3. Trigger-based matching with scoring
            with self._stats_lock:
                self.routing_stats["fuzzy_matches"] += 1

            trigger_matching_start_us = time.perf_counter_ns() // 1000
            trigger_matches = self.trigger_matcher.match(user_request)
            trigger_matching_end_us = time.perf_counter_ns() // 1000
            trigger_matching_time_us = (
                trigger_matching_end_us - trigger_matching_start_us
            )

            logger.debug(f"Found {len(trigger_matches)} trigger matches")

            # 4. Score each match
            confidence_scoring_start_us = time.perf_counter_ns() // 1000
            recommendations: list[AgentRecommendation] = []

            for agent_name, trigger_score, match_reason in trigger_matches:
                try:
                    agent_data = self.registry["agents"][agent_name]

                    confidence = self.confidence_scorer.score(
                        agent_name=agent_name,
                        agent_data=agent_data,
                        user_request=user_request,
                        context=context,
                        trigger_score=trigger_score,
                    )

                    recommendation = AgentRecommendation(
                        agent_name=agent_name,
                        agent_title=agent_data.get("title", agent_name),
                        confidence=confidence,
                        reason=match_reason,
                        definition_path=agent_data.get("definition_path", ""),
                    )

                    recommendations.append(recommendation)

                except KeyError as e:
                    logger.warning(f"Agent {agent_name} missing required field: {e}")
                    continue
                except Exception as e:
                    logger.warning(
                        f"Failed to score agent {agent_name}: {type(e).__name__}"
                    )
                    continue

            # 5. Sort by confidence
            recommendations.sort(key=lambda x: x.confidence.total, reverse=True)

            # 6. Limit to max recommendations
            recommendations = recommendations[:max_recommendations]

            confidence_scoring_end_us = time.perf_counter_ns() // 1000
            confidence_scoring_time_us = (
                confidence_scoring_end_us - confidence_scoring_start_us
            )

            # 7. Cache results
            self.cache.set(user_request, recommendations, context)

            # Calculate total routing time
            routing_end_us = time.perf_counter_ns() // 1000

            with self._stats_lock:
                self.last_routing_timing = RoutingTiming(
                    total_routing_time_us=routing_end_us - routing_start_us,
                    cache_lookup_us=cache_lookup_time_us,
                    trigger_matching_us=trigger_matching_time_us,
                    confidence_scoring_us=confidence_scoring_time_us,
                    cache_hit=False,
                )

            logger.info(
                f"Routed request to {len(recommendations)} agents, "
                f"top: {recommendations[0].agent_name if recommendations else 'none'}"
            )

            return recommendations

        except Exception as e:
            logger.error(f"Routing failed: {type(e).__name__}: {e}")
            return []

    def _extract_explicit_agent(self, text: str) -> str | None:
        """
        Extract explicit agent name from request.

        Supports patterns:
        - "use agent-X" - Specific agent request
        - "@agent-X" - Specific agent request
        - "agent-X" at start of text - Specific agent request
        - "use an agent", "spawn an agent", etc. - Generic request -> polymorphic-agent

        Args:
            text: User's input text

        Returns:
            Agent name if found and valid, None otherwise
        """
        try:
            text_lower = text.lower()

            # Patterns for specific agent requests
            specific_patterns = [
                r"use\s+(agent-[\w-]+)",
                r"@(agent-[\w-]+)",
                r"^(agent-[\w-]+)",
            ]

            for pattern in specific_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    agent_name = match.group(1)
                    if agent_name in self.registry["agents"]:
                        logger.debug(f"Extracted explicit agent: {agent_name}")
                        return agent_name

            # Generic agent requests -> polymorphic-agent
            generic_patterns = [
                r"\buse\s+an?\s+agent\b",
                r"\bspawn\s+an?\s+agent\b",
                r"\bspawn\s+an?\s+poly\b",
                r"\bdispatch\s+to\s+an?\s+agent\b",
                r"\bcall\s+an?\s+agent\b",
                r"\binvoke\s+an?\s+agent\b",
            ]

            for pattern in generic_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    # Try multiple naming conventions
                    for default_agent in [
                        "polymorphic-agent",
                        "agent-polymorphic-agent",
                        "agent-polymorphic",
                    ]:
                        if default_agent in self.registry["agents"]:
                            logger.debug(
                                f"Generic agent request, using: {default_agent}"
                            )
                            return default_agent

            return None

        except Exception as e:
            logger.warning(f"Failed to extract explicit agent: {type(e).__name__}")
            return None

    def _create_explicit_recommendation(
        self, agent_name: str
    ) -> AgentRecommendation | None:
        """Create recommendation for explicitly requested agent."""
        agent_data = self.registry["agents"].get(agent_name)
        if not agent_data:
            return None

        return AgentRecommendation(
            agent_name=agent_name,
            agent_title=agent_data.get("title", agent_name),
            confidence=ConfidenceScore(
                total=1.0,
                trigger_score=1.0,
                context_score=1.0,
                capability_score=1.0,
                historical_score=1.0,
                explanation="Explicit agent request",
            ),
            reason="Explicitly requested by user",
            definition_path=agent_data.get("definition_path", ""),
            is_explicit=True,
        )

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        cache_stats: dict[str, Any] = self.cache.stats()
        with self._stats_lock:
            cache_stats["cache_hit_rate"] = (
                self.routing_stats["cache_hits"] / self.routing_stats["total_routes"]
                if self.routing_stats["total_routes"] > 0
                else 0.0
            )
        return cache_stats

    def get_routing_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        with self._stats_lock:
            stats: dict[str, Any] = dict(self.routing_stats)

        total = stats["total_routes"]
        if total > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / total
            stats["explicit_request_rate"] = stats["explicit_requests"] / total
            stats["fuzzy_match_rate"] = stats["fuzzy_matches"] / total

        return stats

    def invalidate_cache(self) -> None:
        """Invalidate entire routing cache."""
        self.cache.clear()

    def reload_registry(self) -> None:
        """
        Reload agent registry from configs directory.

        Useful when agent definitions change.
        """
        logger.info(f"Reloading registry from {self.configs_dir}")

        self.registry = _build_registry_from_configs(self.configs_dir)
        self.trigger_matcher = TriggerMatcher(self.registry)
        self.cache.clear()

        logger.info(f"Registry reloaded: {len(self.registry['agents'])} agents")


# =============================================================================
# CLI Entry Point
# =============================================================================


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)

    # Accept query from command line or stdin
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = sys.stdin.read().strip()

    if not query:
        print(json.dumps({"error": "No query provided"}))
        sys.exit(1)

    router = AgentRouter()
    recommendations = router.route(query, max_recommendations=3)

    output = {
        "query": query,
        "recommendations": [
            {
                "agent_name": rec.agent_name,
                "agent_title": rec.agent_title,
                "confidence": rec.confidence.total,
                "reason": rec.reason,
                "explanation": rec.confidence.explanation,
            }
            for rec in recommendations
        ],
        "timing_us": (
            router.last_routing_timing.total_routing_time_us
            if router.last_routing_timing
            else 0
        ),
    }

    print(json.dumps(output, indent=2))
