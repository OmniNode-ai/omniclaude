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


def test_an_event_type_ahead_of_the_pinned_daemon_registry_is_tolerated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The daemon registry is read at the omnimarket rev uv.lock pins (OMN-20001).

    A hook-side event type the pinned registry does not carry yet is omniclaude
    ahead of its pin, so the consumer can land first. It is reported, not failed,
    and not a crash (the earlier AttributeError on the missing daemon entry).
    """
    registry = tmp_path / "topics.yaml"
    registry.write_text("events: {}\n", encoding="utf-8")
    violations = _load_checker().check_registry_consistency(registry)
    assert not [v for v in violations if "missing from omnimarket daemon" in v]
    assert not [v for v in violations if "fan-out topics missing" in v]
    assert "ahead of the pinned omnimarket daemon registry" in capsys.readouterr().out


def test_a_registered_type_with_a_missing_fan_out_topic_is_still_a_violation(
    tmp_path: Path,
) -> None:
    """Ahead-of-pin tolerance must not mask drift on a type the pin does register."""
    checker = _load_checker()
    event_type = sorted(checker._supported_event_types(checker.EMIT_CLIENT))[0]
    registry = tmp_path / "topics.yaml"
    registry.write_text(
        f"events:\n  {event_type}:\n    fan_out:\n"
        "      - topic: onex.evt.nobody.unrelated.v1\n",
        encoding="utf-8",
    )
    violations = checker.check_registry_consistency(registry)
    assert [v for v in violations if "fan-out topics missing" in v], violations
