# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Persona signal extraction from session behavior.

Pure heuristic functions that analyze session data (tool usage, prompt text,
error recovery) and produce persona signal tuples of (value, confidence).

These signals feed into node_persona_builder_compute to incrementally update
a user's PersonaProfile. No external dependencies — all classification is
rule-based.

Consent enforcement is deferred to Phase B (OMN-3980). Phase 3 assumes
trusted internal deployment.

Related Tickets:
    - OMN-7306: Persona signal emitter in hooks/lib
    - OMN-7305: Phase 3 Adaptive Personalization epic
"""

from __future__ import annotations

import re

# Technical terms that indicate advanced/expert usage
_EXPERT_TERMS = frozenset(
    {
        "contract.yaml",
        "handler",
        "mixin",
        "orchestrator",
        "reducer",
        "effect node",
        "compute node",
        "kafka",
        "redpanda",
        "onex",
        "pydantic",
        "configdict",
        "frozen",
        "asyncpg",
        "worktree",
        "pre-commit",
    }
)

_BEGINNER_PHRASES = frozenset(
    {
        "what does",
        "what is",
        "how do i",
        "explain",
        "help me understand",
        "i don't understand",
        "can you explain",
        "what's the difference",
    }
)

_EXPLANATORY_PHRASES = frozenset(
    {
        "explain",
        "why",
        "how does",
        "what does",
        "can you explain",
        "tell me about",
        "walk me through",
    }
)

_FORMAL_INDICATORS = frozenset(
    {
        "please",
        "kindly",
        "would you",
        "could you",
        "i'd like",
        "i would like",
    }
)


def extract_technical_level_signal(
    tools_used: list[str],
    prompt_preview: str,
    error_count: int,
    recovery_count: int,
) -> tuple[str, float]:
    """Infer technical level from session behavior.

    Returns (level_value, confidence) where level_value is one of:
    beginner, intermediate, advanced, expert.

    Signals:
    - Beginner: few tools, asks "what does X mean?", low error recovery
    - Intermediate: standard tool usage, some jargon
    - Advanced: many tools, precise prompts, high error recovery rate
    - Expert: terse prompts, architectural language, drives design decisions
    """
    prompt_lower = prompt_preview.lower()
    tool_count = len(tools_used)
    unique_tools = len(set(tools_used))
    recovery_rate = recovery_count / max(error_count, 1) if error_count > 0 else 0.0

    # Check for beginner indicators
    beginner_hits = sum(1 for phrase in _BEGINNER_PHRASES if phrase in prompt_lower)
    if beginner_hits >= 2 and unique_tools <= 3:
        return ("beginner", min(0.6 + beginner_hits * 0.1, 0.95))

    # Check for expert indicators
    expert_hits = sum(1 for term in _EXPERT_TERMS if term in prompt_lower)
    words = prompt_lower.split()
    avg_word_len = sum(len(w) for w in words) / max(len(words), 1)

    if expert_hits >= 3 and avg_word_len > 5.0:
        return ("expert", min(0.65 + expert_hits * 0.05, 0.95))
    if expert_hits >= 2 and unique_tools >= 5 and recovery_rate > 0.7:
        return ("expert", min(0.6 + expert_hits * 0.05, 0.9))

    # Check for advanced
    if unique_tools >= 4 and recovery_rate > 0.5 and expert_hits >= 1:
        return ("advanced", min(0.55 + recovery_rate * 0.2, 0.85))
    if tool_count >= 8 and expert_hits >= 1:
        return ("advanced", 0.6)

    # Default: intermediate
    confidence = 0.5
    if unique_tools >= 2:
        confidence += 0.1
    if avg_word_len > 4.5:
        confidence += 0.1
    return ("intermediate", min(confidence, 0.8))


def extract_vocabulary_signal(prompt_preview: str) -> tuple[float, float]:
    """Score vocabulary complexity from prompt text.

    Returns (complexity_score, confidence) where complexity_score is 0.0-1.0.
    Uses simple heuristics: average word length, technical term density,
    code-to-prose ratio.
    """
    if not prompt_preview.strip():
        return (0.5, 0.1)

    words = prompt_preview.split()
    word_count = len(words)
    if word_count == 0:
        return (0.5, 0.1)

    # Average word length (normalized: 3-8 chars maps to 0.0-1.0)
    avg_len = sum(len(w) for w in words) / word_count
    len_score = max(0.0, min(1.0, (avg_len - 3.0) / 5.0))

    # Technical term density
    prompt_lower = prompt_preview.lower()
    tech_hits = sum(1 for term in _EXPERT_TERMS if term in prompt_lower)
    tech_density = min(1.0, tech_hits / max(word_count / 20, 1))

    # Code-to-prose ratio (lines with code-like patterns)
    lines = prompt_preview.split("\n")
    code_lines = sum(
        1
        for line in lines
        if re.search(r"[{}\[\]();=]|def |class |import |from |->", line)
    )
    code_ratio = code_lines / max(len(lines), 1)

    complexity = (len_score * 0.3) + (tech_density * 0.4) + (code_ratio * 0.3)
    confidence = min(0.4 + (word_count / 100) * 0.4, 0.85)

    return (round(complexity, 3), round(confidence, 3))


def extract_tone_signal(
    prompt_preview: str,
    response_style_hints: list[str],
) -> tuple[str, float]:
    """Infer preferred tone from interaction patterns.

    Returns (tone_value, confidence) where tone_value is one of:
    explanatory, concise, formal, casual.

    Signals:
    - "explain this" / "why" / "how does" -> explanatory
    - Short imperative prompts -> concise
    - Structured/numbered requests -> formal
    - Casual language, emoji, humor -> casual
    """
    prompt_lower = prompt_preview.lower()
    words = prompt_lower.split()
    word_count = len(words)

    # Check explanatory
    explanatory_hits = sum(
        1 for phrase in _EXPLANATORY_PHRASES if phrase in prompt_lower
    )
    if explanatory_hits >= 2:
        return ("explanatory", min(0.6 + explanatory_hits * 0.1, 0.9))

    # Check casual (emoji, slang, exclamation)
    has_emoji = bool(
        re.search(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF]", prompt_preview)
    )
    casual_indicators = sum(
        1 for hint in response_style_hints if "casual" in hint.lower()
    )
    exclamation_count = prompt_preview.count("!")
    if has_emoji or (casual_indicators >= 1 and exclamation_count >= 2):
        return ("casual", 0.65)

    # Check formal (structured, numbered lists, polite language)
    formal_hits = sum(1 for phrase in _FORMAL_INDICATORS if phrase in prompt_lower)
    has_numbered_list = bool(re.search(r"\n\s*\d+[.)]\s", prompt_preview))
    if formal_hits >= 2 or (formal_hits >= 1 and has_numbered_list):
        return ("formal", min(0.55 + formal_hits * 0.1, 0.85))

    # Check concise (short, imperative)
    avg_prompt_len = word_count
    if avg_prompt_len <= 15 and not explanatory_hits:
        return ("concise", min(0.5 + (15 - avg_prompt_len) * 0.02, 0.8))

    # Default: explanatory (safe default)
    return ("explanatory", 0.4)
