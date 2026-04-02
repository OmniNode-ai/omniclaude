# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for persona context client."""

import sys
from pathlib import Path

import pytest

# hooks/lib modules live under plugins/onex/hooks/lib/ and use sys.path shimming
_HOOKS_LIB = str(
    Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
)
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from persona_context_client import (
    format_persona_context,  # type: ignore[import-untyped]
)


@pytest.mark.unit
class TestFormatPersonaContext:
    def test_none_returns_empty(self) -> None:
        assert format_persona_context(None) == ""

    def test_empty_dict_returns_empty(self) -> None:
        assert format_persona_context({}) == ""

    def test_beginner_explanatory(self) -> None:
        persona = {
            "technical_level": "beginner",
            "preferred_tone": "explanatory",
            "vocabulary_complexity": 0.2,
            "domain_familiarity": {"omnimemory": 0.3, "omniclaude": 0.1},
        }
        md = format_persona_context(persona)
        assert "## User Persona" in md
        assert "beginner" in md
        assert "explanatory" in md
        assert "simple" in md
        assert "omnimemory" in md

    def test_expert_concise(self) -> None:
        persona = {
            "technical_level": "expert",
            "preferred_tone": "concise",
            "vocabulary_complexity": 0.9,
            "domain_familiarity": {
                "omnibase_core": 0.95,
                "omniclaude": 0.8,
                "omnimemory": 0.7,
                "omnidash": 0.3,
            },
        }
        md = format_persona_context(persona)
        assert "expert" in md
        assert "concise" in md
        assert "advanced" in md
        # Only top 3 domains
        assert "omnibase_core" in md
        assert "omniclaude" in md
        assert "omnimemory" in md
        assert "omnidash" not in md

    def test_intermediate_defaults(self) -> None:
        persona = {
            "technical_level": "intermediate",
            "preferred_tone": "formal",
            "vocabulary_complexity": 0.5,
        }
        md = format_persona_context(persona)
        assert "intermediate" in md
        assert "formal" in md
        assert "standard" in md
        # No domain section when empty
        assert "Top domains" not in md

    def test_adaptation_hint_line(self) -> None:
        persona = {
            "technical_level": "advanced",
            "preferred_tone": "concise",
            "vocabulary_complexity": 0.6,
        }
        md = format_persona_context(persona)
        assert "Adapt output" in md
        assert "advanced users prefer concise responses" in md

    def test_empty_domain_familiarity_omitted(self) -> None:
        persona = {
            "technical_level": "beginner",
            "preferred_tone": "explanatory",
            "vocabulary_complexity": 0.1,
            "domain_familiarity": {},
        }
        md = format_persona_context(persona)
        assert "Top domains" not in md

    def test_missing_fields_use_defaults(self) -> None:
        """Persona dict with only some fields still produces valid output."""
        persona = {"technical_level": "expert"}
        md = format_persona_context(persona)
        assert "expert" in md
        assert "explanatory" in md  # default tone
        assert "standard" in md  # default vocab 0.5
