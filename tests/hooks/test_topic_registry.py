# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for topic_registry.yaml and Wave 2 pipeline topics (OMN-2922).

Validates:
1. topic_registry.yaml is valid YAML and has required fields per entry.
2. Every entry in topic_registry.yaml has a matching constant in TopicBase.
3. Topic values in registry match TopicBase constants.
4. Wave 2 topic constants are present in TopicBase.
5. Wave 2 event types are in SUPPORTED_EVENT_TYPES in emit_client_wrapper.
6. Wave 2 event types are registered in EVENT_REGISTRY.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "src" / "omniclaude" / "hooks" / "topic_registry.yaml"
EMIT_WRAPPER_PATH = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "emit_client_wrapper.py"
)

# ---------------------------------------------------------------------------
# Wave 2 constants under test
# ---------------------------------------------------------------------------

WAVE2_TOPIC_CONSTANTS = [
    "EPIC_RUN_UPDATED",
    "PR_WATCH_UPDATED",
    "GATE_DECISION",
    "BUDGET_CAP_HIT",
    "CIRCUIT_BREAKER_TRIPPED",
]

WAVE2_TOPIC_VALUES = {
    "EPIC_RUN_UPDATED": "onex.evt.omniclaude.epic-run-updated.v1",
    "PR_WATCH_UPDATED": "onex.evt.omniclaude.pr-watch-updated.v1",
    "GATE_DECISION": "onex.evt.omniclaude.gate-decision.v1",
    "BUDGET_CAP_HIT": "onex.evt.omniclaude.budget-cap-hit.v1",
    "CIRCUIT_BREAKER_TRIPPED": "onex.evt.omniclaude.circuit-breaker-tripped.v1",
}

WAVE2_EVENT_TYPES = [
    "epic.run.updated",
    "pr.watch.updated",
    "gate.decision",
    "budget.cap.hit",
    "circuit.breaker.tripped",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry_data() -> dict[str, Any]:
    """Load and return topic_registry.yaml as a dict."""
    assert REGISTRY_PATH.exists(), f"topic_registry.yaml not found at {REGISTRY_PATH}"
    with open(REGISTRY_PATH) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "topic_registry.yaml must be a YAML mapping"
    return data


@pytest.fixture(scope="module")
def registry_topics(registry_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of topic entries from the registry."""
    topics = registry_data.get("topics", [])
    assert isinstance(topics, list), "topic_registry.yaml must have a 'topics' list"
    return topics


# ---------------------------------------------------------------------------
# Tests: topic_registry.yaml structure
# ---------------------------------------------------------------------------


class TestTopicRegistryStructure:
    """Validate the structure of topic_registry.yaml."""

    def test_registry_file_exists(self) -> None:
        assert REGISTRY_PATH.exists(), (
            f"topic_registry.yaml not found at {REGISTRY_PATH}"
        )

    def test_registry_is_valid_yaml(self, registry_data: dict[str, Any]) -> None:
        assert "topics" in registry_data

    def test_each_entry_has_required_fields(
        self, registry_topics: list[dict[str, Any]]
    ) -> None:
        required = {"event_type", "topic", "topic_base_constant"}
        for entry in registry_topics:
            missing = required - set(entry.keys())
            assert not missing, (
                f"Entry {entry.get('event_type', '?')} missing fields: {missing}"
            )

    def test_each_topic_value_is_string(
        self, registry_topics: list[dict[str, Any]]
    ) -> None:
        for entry in registry_topics:
            assert isinstance(entry["event_type"], str), (
                f"event_type must be str: {entry}"
            )
            assert isinstance(entry["topic"], str), f"topic must be str: {entry}"
            assert isinstance(entry["topic_base_constant"], str), (
                f"topic_base_constant must be str: {entry}"
            )

    def test_no_duplicate_event_types(
        self, registry_topics: list[dict[str, Any]]
    ) -> None:
        event_types = [e["event_type"] for e in registry_topics]
        duplicates = [et for et in set(event_types) if event_types.count(et) > 1]
        assert not duplicates, f"Duplicate event_types in registry: {duplicates}"


# ---------------------------------------------------------------------------
# Tests: registry → TopicBase consistency
# ---------------------------------------------------------------------------


class TestRegistryTopicBaseConsistency:
    """Validate every registry entry has a matching TopicBase constant."""

    def test_every_registry_entry_has_topic_base_constant(
        self, registry_topics: list[dict[str, Any]]
    ) -> None:
        from omniclaude.hooks.topics import TopicBase

        topic_base_names = {t.name for t in TopicBase}

        for entry in registry_topics:
            const = entry["topic_base_constant"]
            assert const in topic_base_names, (
                f"Registry entry '{entry['event_type']}' references "
                f"TopicBase.{const} which does not exist"
            )

    def test_registry_topic_values_match_topic_base(
        self, registry_topics: list[dict[str, Any]]
    ) -> None:
        from omniclaude.hooks.topics import TopicBase

        topic_base_map = {t.name: t.value for t in TopicBase}

        for entry in registry_topics:
            const = entry["topic_base_constant"]
            expected_topic = entry["topic"]
            actual_topic = topic_base_map.get(const)
            assert actual_topic == expected_topic, (
                f"Registry entry '{entry['event_type']}': "
                f"topic '{expected_topic}' != TopicBase.{const} '{actual_topic}'"
            )


# ---------------------------------------------------------------------------
# Tests: Wave 2 topic constants in TopicBase
# ---------------------------------------------------------------------------


class TestWave2TopicConstants:
    """Validate Wave 2 topic constants are correctly defined in TopicBase."""

    @pytest.mark.parametrize("constant_name", WAVE2_TOPIC_CONSTANTS)
    def test_wave2_constant_exists_in_topic_base(self, constant_name: str) -> None:
        from omniclaude.hooks.topics import TopicBase

        assert hasattr(TopicBase, constant_name), (
            f"TopicBase is missing Wave 2 constant: {constant_name}"
        )

    @pytest.mark.parametrize(
        ("constant_name", "expected_value"), WAVE2_TOPIC_VALUES.items()
    )
    def test_wave2_constant_value(
        self, constant_name: str, expected_value: str
    ) -> None:
        from omniclaude.hooks.topics import TopicBase

        actual = getattr(TopicBase, constant_name).value
        assert actual == expected_value, (
            f"TopicBase.{constant_name} = '{actual}', expected '{expected_value}'"
        )


# ---------------------------------------------------------------------------
# Tests: Wave 2 event types in SUPPORTED_EVENT_TYPES
# ---------------------------------------------------------------------------


class TestWave2EventTypesInWrapper:
    """Validate Wave 2 event types are in emit_client_wrapper.SUPPORTED_EVENT_TYPES."""

    @pytest.mark.parametrize("event_type", WAVE2_EVENT_TYPES)
    def test_wave2_event_type_in_supported(self, event_type: str) -> None:
        import importlib.util

        # Load emit_client_wrapper from its file path (it's not a proper package)
        spec = importlib.util.spec_from_file_location(
            "emit_client_wrapper", EMIT_WRAPPER_PATH
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Avoid polluting sys.modules across tests
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]

        supported: frozenset[str] = mod.SUPPORTED_EVENT_TYPES  # type: ignore[attr-defined]
        assert event_type in supported, (
            f"emit_client_wrapper.SUPPORTED_EVENT_TYPES is missing '{event_type}'"
        )


# ---------------------------------------------------------------------------
# Tests: Wave 2 event types in EVENT_REGISTRY
# ---------------------------------------------------------------------------


class TestWave2EventTypesInRegistry:
    """Validate Wave 2 event types are registered in event_registry.EVENT_REGISTRY."""

    @pytest.mark.parametrize("event_type", WAVE2_EVENT_TYPES)
    def test_wave2_event_type_in_event_registry(self, event_type: str) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert event_type in EVENT_REGISTRY, (
            f"event_registry.EVENT_REGISTRY is missing '{event_type}'"
        )

    def test_wave2_gate_decision_fan_out_topic(self) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["gate.decision"]
        assert len(reg.fan_out) == 1
        assert reg.fan_out[0].topic_base == TopicBase.GATE_DECISION
        assert reg.partition_key_field == "gate_id"
        assert "gate_id" in reg.required_fields

    def test_wave2_epic_run_updated_fan_out_topic(self) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["epic.run.updated"]
        assert reg.fan_out[0].topic_base == TopicBase.EPIC_RUN_UPDATED
        assert reg.partition_key_field == "run_id"

    def test_wave2_pr_watch_updated_fan_out_topic(self) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["pr.watch.updated"]
        assert reg.fan_out[0].topic_base == TopicBase.PR_WATCH_UPDATED
        assert reg.partition_key_field == "run_id"

    def test_wave2_budget_cap_hit_fan_out_topic(self) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["budget.cap.hit"]
        assert reg.fan_out[0].topic_base == TopicBase.BUDGET_CAP_HIT
        assert reg.partition_key_field == "run_id"

    def test_wave2_circuit_breaker_tripped_fan_out_topic(self) -> None:
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["circuit.breaker.tripped"]
        assert reg.fan_out[0].topic_base == TopicBase.CIRCUIT_BREAKER_TRIPPED
        assert reg.partition_key_field == "session_id"
