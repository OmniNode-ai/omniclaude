# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for persona signal extraction heuristics."""

import pytest

from plugins.onex.hooks.lib.persona_signal_emitter import (
    extract_technical_level_signal,
    extract_tone_signal,
    extract_vocabulary_signal,
)


@pytest.mark.unit
class TestExtractTechnicalLevel:
    def test_beginner_asks_what_does(self) -> None:
        level, conf = extract_technical_level_signal(
            tools_used=["Read"],
            prompt_preview="What does frozen=True mean? What is a handler?",
            error_count=0,
            recovery_count=0,
        )
        assert level == "beginner"
        assert conf >= 0.6

    def test_expert_architectural_language(self) -> None:
        level, conf = extract_technical_level_signal(
            tools_used=["Read", "Edit", "Bash", "Grep", "Glob"],
            prompt_preview=(
                "Wire the contract.yaml handler pattern through the orchestrator "
                "with frozen pydantic models and kafka topics"
            ),
            error_count=3,
            recovery_count=3,
        )
        assert level == "expert"
        assert conf >= 0.6

    def test_intermediate_standard_usage(self) -> None:
        level, conf = extract_technical_level_signal(
            tools_used=["Read", "Edit"],
            prompt_preview="Fix the bug in the login function",
            error_count=1,
            recovery_count=0,
        )
        assert level == "intermediate"
        assert conf >= 0.5

    def test_advanced_many_tools_good_recovery(self) -> None:
        level, conf = extract_technical_level_signal(
            tools_used=["Read", "Edit", "Bash", "Grep", "Glob", "Read", "Edit", "Bash"],
            prompt_preview="Trace the handler import path through onex nodes",
            error_count=4,
            recovery_count=3,
        )
        assert level in ("advanced", "expert")
        assert conf >= 0.55

    def test_empty_prompt_defaults_intermediate(self) -> None:
        level, conf = extract_technical_level_signal(
            tools_used=[],
            prompt_preview="",
            error_count=0,
            recovery_count=0,
        )
        assert level == "intermediate"

    def test_returns_tuple(self) -> None:
        result = extract_technical_level_signal(
            tools_used=["Read"],
            prompt_preview="Hello",
            error_count=0,
            recovery_count=0,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)
        assert 0.0 <= result[1] <= 1.0


@pytest.mark.unit
class TestExtractVocabulary:
    def test_simple_vocabulary(self) -> None:
        score, conf = extract_vocabulary_signal("fix the bug in my code please")
        assert score < 0.4

    def test_complex_vocabulary(self) -> None:
        score, conf = extract_vocabulary_signal(
            "Refactor the contract.yaml handler to use frozen pydantic "
            "configdict with asyncpg adapter orchestrator pattern"
        )
        assert score > 0.3

    def test_code_heavy_prompt(self) -> None:
        score, conf = extract_vocabulary_signal(
            "def handler():\n    return {}\n\nclass MyModel:\n    pass\n"
        )
        assert score > 0.2

    def test_empty_prompt(self) -> None:
        score, conf = extract_vocabulary_signal("")
        assert score == 0.5
        assert conf == 0.1

    def test_confidence_increases_with_length(self) -> None:
        short_prompt = "fix bug"
        long_prompt = " ".join(["technical"] * 50)
        _, short_conf = extract_vocabulary_signal(short_prompt)
        _, long_conf = extract_vocabulary_signal(long_prompt)
        assert long_conf > short_conf

    def test_returns_bounded_values(self) -> None:
        score, conf = extract_vocabulary_signal("test prompt with some words")
        assert 0.0 <= score <= 1.0
        assert 0.0 <= conf <= 1.0


@pytest.mark.unit
class TestExtractTone:
    def test_explanatory_explicit_request(self) -> None:
        tone, conf = extract_tone_signal(
            "Explain how this works. Why does it fail? How does the handler connect?",
            [],
        )
        assert tone == "explanatory"
        assert conf >= 0.6

    def test_concise_short_imperative(self) -> None:
        tone, conf = extract_tone_signal(
            "Fix the test.",
            [],
        )
        assert tone == "concise"
        assert conf >= 0.5

    def test_formal_polite_structured(self) -> None:
        tone, conf = extract_tone_signal(
            "Please kindly review the following:\n1. Check imports\n2. Validate types",
            [],
        )
        assert tone == "formal"
        assert conf >= 0.55

    def test_casual_with_hints(self) -> None:
        tone, conf = extract_tone_signal(
            "yeah just ship it!! looks good!!",
            ["casual"],
        )
        assert tone == "casual"
        assert conf >= 0.6

    def test_default_explanatory(self) -> None:
        tone, conf = extract_tone_signal(
            "Implement the feature following the existing pattern in the codebase",
            [],
        )
        assert tone in ("explanatory", "concise", "formal")

    def test_returns_tuple(self) -> None:
        result = extract_tone_signal("test", [])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] in ("explanatory", "concise", "formal", "casual")
        assert 0.0 <= result[1] <= 1.0
