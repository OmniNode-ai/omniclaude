# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fixture bindings shared by the Claude Code hook adapter tests (OMN-18531)."""

from __future__ import annotations

from typing import Any

import pytest

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumBindingKind,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientArgument,
    ModelClientBinding,
)


def make_binding(**overrides: Any) -> ModelClientBinding:
    fields: dict[str, Any] = {
        "name": "delegation",
        "kind": EnumBindingKind.REPLACING,
        "hook_event": "tool.call",
        "matcher_tool": "Agent",
        "command_topic": TopicBase.CLAUDE_CODE_HOOK_ADAPT.value,
        "command_type": "fixture_command",
        "arguments": (
            ModelClientArgument(name="session_id", source="$.session.id"),
            ModelClientArgument(name="prompt", source="$.input.prompt"),
        ),
        "awaited_events": (TopicBase.CLAUDE_CODE_HOOK_ADAPTED.value,),
        "verdict_compute": "fixture_verdict",
        "deadline_ms": 30000,
        "probe_rows": ("P0", "P1"),
    }
    fields.update(overrides)
    return ModelClientBinding(**fields)


@pytest.fixture
def replacing_binding() -> ModelClientBinding:
    return make_binding()


@pytest.fixture
def additive_binding() -> ModelClientBinding:
    return make_binding(
        name="session_start",
        kind=EnumBindingKind.ADDITIVE,
        hook_event="SessionStart",
        matcher_tool=None,
        probe_rows=("P16",),
    )
