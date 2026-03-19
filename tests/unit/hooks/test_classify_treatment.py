# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for treatment group classification (OMN-5551)."""

from __future__ import annotations

import pytest

# Import from the plugins path — these are standalone modules
# that run in the hooks subprocess.  For unit tests we can import
# them directly after adjusting sys.path.
import sys
from pathlib import Path

# Add plugins/onex/hooks/lib to sys.path so we can import classify_treatment
_HOOKS_LIB = str(
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
)
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from classify_treatment import (  # noqa: E402
    classify_treatment_group,
    classify_from_env,
)

pytestmark = pytest.mark.unit


class TestClassifyTreatmentGroup:
    """Test classify_treatment_group with explicit capability sets."""

    def test_all_capabilities_present_is_treatment(self) -> None:
        caps = {
            "intelligence_pattern_injection",
            "intelligence_local_model_routing",
            "intelligence_validator_hooks",
            "intelligence_memory_rag_retrieval",
        }
        assert classify_treatment_group(caps) == "treatment"

    def test_no_capabilities_is_control(self) -> None:
        assert classify_treatment_group(set()) == "control"

    def test_partial_capabilities_is_unknown(self) -> None:
        caps = {"intelligence_pattern_injection"}
        assert classify_treatment_group(caps) == "unknown"

    def test_superset_capabilities_is_treatment(self) -> None:
        caps = {
            "intelligence_pattern_injection",
            "intelligence_local_model_routing",
            "intelligence_validator_hooks",
            "intelligence_memory_rag_retrieval",
            "some_other_capability",
        }
        assert classify_treatment_group(caps) == "treatment"

    def test_unrelated_capabilities_is_control(self) -> None:
        caps = {"some_unrelated_capability", "another_one"}
        assert classify_treatment_group(caps) == "control"


class TestClassifyFromEnv:
    """Test env-based classification."""

    def test_default_env_is_not_control(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With defaults, pattern injection + validator hooks are active → unknown or treatment."""
        monkeypatch.delenv("OMNICLAUDE_CONTEXT_API_ENABLED", raising=False)
        monkeypatch.delenv("USE_EVENT_ROUTING", raising=False)
        monkeypatch.delenv("ENFORCEMENT_MODE", raising=False)
        monkeypatch.delenv("QDRANT_URL", raising=False)
        result = classify_from_env()
        # Default: injection=on, routing=off, validators=on, rag=off → partial → unknown
        assert result == "unknown"

    def test_all_enabled_is_treatment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_API_ENABLED", "true")
        monkeypatch.setenv("USE_EVENT_ROUTING", "true")
        monkeypatch.setenv("ENFORCEMENT_MODE", "warn")
        monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
        assert classify_from_env() == "treatment"

    def test_all_disabled_is_control(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CONTEXT_API_ENABLED", "false")
        monkeypatch.setenv("USE_EVENT_ROUTING", "false")
        monkeypatch.setenv("ENFORCEMENT_MODE", "silent")
        monkeypatch.delenv("QDRANT_URL", raising=False)
        assert classify_from_env() == "control"
