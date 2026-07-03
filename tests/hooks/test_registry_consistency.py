# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Cross-registry consistency gate for hook event types (OMN-13092).

Three registries describe the same emit surface and can drift independently:

1. The hook-side frozenset ``SUPPORTED_EVENT_TYPES`` in
   ``plugins/onex/hooks/lib/emit_client_wrapper.py`` (client-side allowlist).
2. omniclaude's ``EVENT_REGISTRY`` in ``src/omniclaude/hooks/event_registry.py``
   (fan-out rules, the source the daemon YAML is generated from).
3. The omnimarket emit daemon YAML registry
   ``node_emit_daemon/registries/topics.yaml`` (runtime routing authority).

Before this gate existed, three event types (``delegate.task``,
``agent.action``, ``llm.cost.completed``) were silently emittable by hooks but
unroutable by the daemon. This module is the minimal drift gate for the
skill-output-suppression slice; full registry unification is parent Phase 2.

Daemon-registry resolution order:

1. ``OMNIMARKET_TOPICS_REGISTRY_PATH`` — explicit path (set by the CI job that
   checks out omnimarket@dev). If set but missing, the test FAILS — a
   misconfigured gate must never silently skip.
2. ``$OMNI_HOME/omnimarket/...`` — local canonical clone.
3. Neither available — skip (the dedicated CI job provides blocking coverage).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from omniclaude.hooks.event_registry import EVENT_REGISTRY
from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

pytestmark = pytest.mark.unit

_REGISTRY_RELATIVE_PATH = "src/omnimarket/nodes/node_emit_daemon/registries/topics.yaml"

# Capture topics must be duty-critical: suppression of tool output from the
# LLM context is only allowed when the full bytes are content-addressed and an
# event records the capture (no-hidden-loss invariant, OMN-13089).
_CAPTURE_EVENT_TOPICS = {
    "artifact.captured": "onex.evt.omnimarket.artifact-captured.v1",
    "tool.output.captured": "onex.evt.omnimarket.tool-output-captured.v1",
}


def _resolve_daemon_registry_path() -> Path:
    """Resolve the omnimarket daemon registry YAML or skip/fail explicitly."""
    explicit = os.environ.get("OMNIMARKET_TOPICS_REGISTRY_PATH")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            pytest.fail(
                "OMNIMARKET_TOPICS_REGISTRY_PATH is set but does not point to "
                f"a file: {explicit}. A misconfigured registry-consistency "
                "gate must fail, not skip."
            )
        return path

    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        candidate = Path(omni_home) / "omnimarket" / _REGISTRY_RELATIVE_PATH
        if candidate.is_file():
            return candidate

    pytest.skip(
        "omnimarket daemon registry not resolvable (no "
        "OMNIMARKET_TOPICS_REGISTRY_PATH, no $OMNI_HOME/omnimarket checkout). "
        "The registry-consistency CI job provides blocking coverage."
    )
    raise AssertionError("pytest.skip returned unexpectedly")


def _load_daemon_events() -> dict[str, object]:
    raw = yaml.safe_load(_resolve_daemon_registry_path().read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "daemon registry YAML must be a mapping"
    events = raw.get("events")
    assert isinstance(events, dict), "daemon registry YAML must have an events mapping"
    return events


class TestRegistryConsistency:
    """Hook frozenset ⊆ omniclaude EVENT_REGISTRY ⊆ daemon YAML registry."""

    def test_registry_consistency_frozenset_subset_of_event_registry(self) -> None:
        """Every client-emittable event type has an omniclaude fan-out rule."""
        missing = sorted(SUPPORTED_EVENT_TYPES - set(EVENT_REGISTRY))
        assert not missing, (
            "SUPPORTED_EVENT_TYPES entries missing from omniclaude "
            f"EVENT_REGISTRY (unroutable client events): {missing}"
        )

    def test_registry_consistency_frozenset_subset_of_daemon_registry(self) -> None:
        """Every client-emittable event type is registered in the daemon YAML."""
        daemon_events = _load_daemon_events()
        missing = sorted(SUPPORTED_EVENT_TYPES - set(daemon_events))
        assert not missing, (
            "SUPPORTED_EVENT_TYPES entries missing from the omnimarket emit "
            f"daemon registry (daemon would reject these events): {missing}"
        )

    def test_registry_consistency_capture_topics_duty_critical(self) -> None:
        """The OMN-13092 capture events route to duty_critical topics."""
        daemon_events = _load_daemon_events()
        for event_type, expected_topic in _CAPTURE_EVENT_TOPICS.items():
            event_def = daemon_events.get(event_type)
            assert isinstance(event_def, dict), f"{event_type} not registered"
            fan_out = event_def.get("fan_out")
            assert isinstance(fan_out, list) and fan_out, (
                f"{event_type} has no fan_out rules"
            )
            rules = {rule["topic"]: rule["tier"] for rule in fan_out}
            assert rules == {expected_topic: "duty_critical"}, (
                f"{event_type} must fan out to exactly {expected_topic} at "
                f"duty_critical tier, got: {rules}"
            )

    def test_registry_consistency_event_topics_subset_of_daemon_topics(self) -> None:
        """Per event type, omniclaude fan-out topics ⊆ daemon fan-out topics.

        Subset, not equality: the daemon is the runtime routing authority and
        may fan out wider than the hook-side registration (e.g.
        ``diagnostic.daemon.health`` adds the non-standard
        ``onex.evt.diagnostic.daemon-health.v1`` target that omniclaude's
        TopicBase cannot carry without failing the topic-naming lint). A topic
        the hook side would route that the daemon does not know is real drift.
        """
        daemon_events = _load_daemon_events()
        mismatches: dict[str, set[str]] = {}
        for event_type in sorted(SUPPORTED_EVENT_TYPES):
            registration = EVENT_REGISTRY[event_type]
            source_topics = {str(rule.topic_base) for rule in registration.fan_out}
            event_def = daemon_events[event_type]
            assert isinstance(event_def, dict)
            daemon_topics = {rule["topic"] for rule in event_def.get("fan_out", [])}
            missing = source_topics - daemon_topics
            if missing:
                mismatches[event_type] = missing
        assert not mismatches, (
            "omniclaude EVENT_REGISTRY fan-out topics missing from the daemon "
            f"registry for these event types: {mismatches}"
        )
