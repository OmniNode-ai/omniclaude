# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20074 S8: the topic and TODO hooks are consumed from omnibase_core.

``no-hardcoded-topics`` and ``no-untracked-todos`` moved from onex_change_control
into omnibase_core under the same hook ids. This repository's
``.pre-commit-config.yaml`` must take each from an omnibase_core repo block
pinned to a full commit sha or a release tag, never from onex_change_control.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
OCC_REPO = "https://github.com/OmniNode-ai/onex_change_control"
CORE_PIN = re.compile(r"^(?:[0-9a-f]{40}|v\d+\.\d+\.\d+)$")
MOVED_HOOKS = ("no-hardcoded-topics", "no-untracked-todos")
# The exclude no-hardcoded-topics carried in the onex_change_control block, byte for byte.
EXPECTED_TOPICS_EXCLUDE = r"^(src/omniclaude/hooks/(topic_allowlist|topic_registry)\.yaml|src/omniclaude/hooks/contracts/(capture_redaction|contract_hook_.*|wire/.*)\.yaml|src/omniclaude/lib/(config/intelligence_config|core/intelligence_event_client)\.py|src/omniclaude/nodes/(contracts|.*/contracts)/.*\.yaml|src/omniclaude/nodes/node_agent_inbox_effect/handler_kafka_inbox\.py|src/omniclaude/runtime/(__main__|wiring_dispatchers)\.py|src/omniclaude/services/linear_relay/publisher\.py|plugins/onex/(hooks/lib/pattern_cache\.py|skills/_lib/contract_generator/generate_contract\.py)|schemas/quirks/.*\.yaml|scripts/(bus_audit|demo_runner|validation/validate_golden_chain_integrity|validation/generate_event_registry)\.py|tests/validate_event_integration\.py|tests/(integration|unit)/skills/aislop_sweep/fixtures/.*)$"


def _owners(hook_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(repo url, rev, hook entry)`` for every block that lists *hook_id*."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [
        (block["repo"], str(block.get("rev", "")), hook)
        for block in config["repos"]
        for hook in block.get("hooks", [])
        if hook.get("id") == hook_id
    ]


@pytest.mark.parametrize("hook_id", MOVED_HOOKS)
def test_moved_hook_comes_from_omnibase_core(hook_id: str) -> None:
    owners = _owners(hook_id)
    assert [url for url, _, _ in owners] == [CORE_REPO]
    _, rev, hook = owners[0]
    assert CORE_PIN.match(rev), (
        f"omnibase_core rev must be a full sha or release tag, got {rev!r}"
    )
    assert hook.get("stages") == ["pre-commit"]
    if hook_id == "no-hardcoded-topics":
        assert hook.get("exclude") == EXPECTED_TOPICS_EXCLUDE


@pytest.mark.parametrize("hook_id", MOVED_HOOKS)
def test_moved_hook_is_not_consumed_from_onex_change_control(hook_id: str) -> None:
    assert OCC_REPO not in {url for url, _, _ in _owners(hook_id)}
