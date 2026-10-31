# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""scripts/bus_audit.py resolves its topic tables through topic_registry.yaml (OMN-21623).

Before this change the script imported ``ModelRoutingFeedbackSkippedPayload``, which
OMN-2622 removed, so it exited at import; the tables also named an agent-status
topic the registry and ``TopicBase`` do not carry.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.topics import TopicBase

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bus_audit.py"


def _load_bus_audit(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    stub = ModuleType("confluent_kafka")
    for name in ("Consumer", "KafkaException", "TopicPartition"):
        setattr(stub, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "confluent_kafka", stub)
    spec = importlib.util.spec_from_file_location("bus_audit_omn21623", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_script_imports_and_every_audited_topic_is_a_topic_base_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bus_audit(monkeypatch)
    topicbase_values = {member.value for member in TopicBase}
    assert len(module.TOPIC_SCHEMA_MAP) == 13
    assert set(module.TOPIC_SCHEMA_MAP) <= topicbase_values
    assert set(module.FIELD_EXEMPTIONS) == set(module.TOPIC_SCHEMA_MAP)
    emitted = {topic for topics in module.HOOK_EMISSIONS.values() for topic in topics}
    assert emitted <= topicbase_values
    assert topicbase_values >= module.CORE_PRESENCE_TOPICS


@pytest.mark.unit
def test_hook_emissions_resolve_to_the_registered_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_bus_audit(monkeypatch)
    assert module.HOOK_EMISSIONS == {
        "SessionStart": ["onex.evt.omniclaude.session-started.v1"],
        "SessionEnd": [
            "onex.evt.omniclaude.session-ended.v1",
            "onex.cmd.omniintelligence.session-outcome.v1",
            "onex.evt.omniclaude.session-outcome.v1",
            "onex.evt.omniclaude.routing-feedback.v1",
        ],
        "UserPromptSubmit": [
            "onex.evt.omniclaude.prompt-submitted.v1",
            "onex.cmd.omniintelligence.claude-hook-event.v1",
        ],
        "PostToolUse": ["onex.evt.omniclaude.tool-executed.v1"],
    }
    assert {
        (
            "onex.evt.omniclaude.prompt-submitted.v1",
            "onex.cmd.omniintelligence.claude-hook-event.v1",
        ),
        (
            "onex.evt.omniclaude.session-outcome.v1",
            "onex.cmd.omniintelligence.session-outcome.v1",
        ),
    } == module.DUAL_EMISSION_ALLOWLIST


@pytest.mark.unit
def test_undeclared_event_type_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_bus_audit(monkeypatch)
    with pytest.raises(ValueError, match=r"no\.such\.event"):
        module._topic("no.such.event")


@pytest.mark.unit
def test_script_code_holds_no_topic_literal() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(
            r"onex\.(?:cmd|evt)\.[a-z0-9_-]+\.[a-z0-9._-]+\.v[0-9]+", node.value
        )
    ]
    assert literals == []
