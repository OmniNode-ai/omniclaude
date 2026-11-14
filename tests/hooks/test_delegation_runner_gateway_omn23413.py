# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One Claude switch: the legacy hook stands down while the gateway is on (OMN-23413).

`onex claude enable` sends every Claude Code request through the ONEX gateway
and records its ownership in ``~/.onex/claude_gateway.json`` with
``"phase":"enabled"``. The legacy bit-11 PreToolUse hook (OMN-22498) must not
also route the same Agent call while that is so. Its bit is never changed, so
`onex claude disable` leaves the user's own bit-11 choice exactly as it was.

Failure modes:
  F1. Gateway enabled, legacy hook still routes: the request is delegated twice.
  F2. Gateway disabled (journal phase "disabled"), legacy routing stays off
      although the user turned the gateway off: the switch is not reversible.
  F3. No gateway journal at all (a user who never ran onex claude enable), and
      legacy routing stops: the check is not scoped to the gateway.
  F4. An unreadable or malformed journal crashes the runner into a routing
      decision instead of passing the call through.

A stub classifier that always says "delegatable" is the positive control: with
the gateway off the same call must come back DELEGATED, so a pass-through in
F1 is the gateway check and nothing else.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

_MODULE_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "delegation_hook_runner.py"
)

_AGENT_CALL = json.dumps(
    {"tool_name": "Agent", "tool_input": {"prompt": "write a haiku about rivers"}}
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "delegation_hook_runner_omn23413", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _AlwaysDelegates:
    def is_delegatable(self, _text: str) -> SimpleNamespace:
        return SimpleNamespace(
            delegatable=True,
            delegate_to_model="local-coder",
            classified_intent="implement",
        )


def _first_line(home: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("HOME", str(home))
    runner = _load_runner()
    out = io.StringIO()
    with (
        patch.object(runner, "_import_gate", return_value=None),
        patch.object(runner, "_import_classifier", return_value=_AlwaysDelegates()),
        patch.object(runner, "_build_telemetry_json", return_value=""),
        patch.object(sys, "stdin", io.StringIO(_AGENT_CALL)),
        patch.object(sys, "stdout", out),
    ):
        assert runner.main() == 0
    return out.getvalue().splitlines()[0]


def _journal(home: Path, phase: str) -> None:
    path = home / ".onex" / "claude_gateway.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phase": phase,
                "gateway_url": "http://127.0.0.1:8181",
            },
            separators=(",", ":"),
        )
        + "\n"
    )


@pytest.mark.unit
def test_delegation_gateway_enabled_legacy_runner_does_not_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1."""
    _journal(tmp_path, "enabled")
    assert _first_line(tmp_path, monkeypatch) == "not_delegatable:gateway"


@pytest.mark.unit
def test_delegation_gateway_disabled_legacy_runner_routes_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2, and the positive control for F1."""
    _journal(tmp_path, "disabled")
    assert _first_line(tmp_path, monkeypatch).startswith("DELEGATED: implement")


@pytest.mark.unit
def test_delegation_gateway_never_enabled_legacy_runner_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3."""
    assert _first_line(tmp_path, monkeypatch).startswith("DELEGATED: implement")


@pytest.mark.unit
def test_delegation_gateway_unreadable_journal_never_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4: a journal that cannot be read is treated as the gateway owning the session."""
    (tmp_path / ".onex" / "claude_gateway.json").mkdir(parents=True)
    assert _first_line(tmp_path, monkeypatch) == "not_delegatable:gateway"
