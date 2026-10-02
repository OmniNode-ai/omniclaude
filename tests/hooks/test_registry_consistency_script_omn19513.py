# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The registry-consistency script reports, not crashes, on an unregistered type.

A hook-side event type can land in omniclaude before omnimarket registers it
(hook.event, OMN-19513; content.captured, OMN-19551). The gate must print that
ordering violation. Before this fix it raised AttributeError on the missing
daemon entry, so CI showed a traceback instead of the reason.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

pytestmark = pytest.mark.unit

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / "check_registry_consistency.py"
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_registry_consistency", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_event_type_missing_from_the_daemon_is_a_violation_not_a_crash(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "topics.yaml"
    registry.write_text("events: {}\n", encoding="utf-8")
    violations = _load_checker().check_registry_consistency(registry)
    missing = [v for v in violations if "missing from omnimarket daemon registry" in v]
    assert missing, violations


def _matching_daemon_registry(checker: ModuleType, path: Path) -> list[str]:
    """Write a daemon registry that mirrors omniclaude's own; return its types."""
    supported = checker._supported_event_types(checker.EMIT_CLIENT)
    topics = checker._event_registry_topics(
        checker.EVENT_REGISTRY, checker._topic_base_values(checker.TOPICS)
    )
    events = {
        event_type: {
            "fan_out": [
                {"topic": topic, "tier": "duty_critical"}
                for topic in sorted(topics.get(event_type, set()))
            ]
        }
        for event_type in sorted(supported)
    }
    path.write_text(yaml.safe_dump({"events": events}), encoding="utf-8")
    return sorted(events)


def test_a_registry_that_matches_omniclaude_passes(tmp_path: Path) -> None:
    checker = _load_checker()
    registry = tmp_path / "topics.yaml"
    _matching_daemon_registry(checker, registry)
    assert checker.check_registry_consistency(registry) == []
    assert checker.main(["--daemon-registry", str(registry)]) == 0


def test_a_registry_missing_one_type_omniclaude_has_fails(tmp_path: Path) -> None:
    """Strict drift: the pinned registry lacking one type is a nonzero exit.

    The matching registry above is the positive control; this one differs from
    it by exactly one removed event type.
    """
    checker = _load_checker()
    registry = tmp_path / "topics.yaml"
    types = _matching_daemon_registry(checker, registry)
    dropped = next(t for t in types if t not in checker.CAPTURE_EVENT_TYPES)
    raw = yaml.safe_load(registry.read_text(encoding="utf-8"))
    del raw["events"][dropped]
    registry.write_text(yaml.safe_dump(raw), encoding="utf-8")

    violations = checker.check_registry_consistency(registry)
    missing = [v for v in violations if "missing from omnimarket daemon" in v]
    assert missing and dropped in missing[0], violations
    assert checker.main(["--daemon-registry", str(registry)]) == 1
