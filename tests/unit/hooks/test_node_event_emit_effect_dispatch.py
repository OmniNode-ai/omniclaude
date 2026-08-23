# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for ``node_event_emit_effect_dispatch.py`` (OMN-16162).

Covers the fail-open contract of the SessionStart/SessionEnd direct-dispatch
caller: ``main()`` must return 0 (never raise, never propagate a non-zero
exit) for every failure mode named in the ticket -- an emit node that never
publishes (no reachable Kafka bus), a handler that raises outright (e.g. a
durability-layer ``SpoolFullError``-class exception), and malformed
``--payload`` JSON on stdin/argv.

``omnimarket`` is a real, pinned dependency of this repo (see
``pyproject.toml``), so these tests import the actual
``HandlerEventEmitEffect`` / ``ModelEmitRequest`` classes rather than a
fake stand-in -- no Kafka mocking is required because ``KAFKA_BOOTSTRAP_SERVERS``
is deliberately left unset/unreachable in the unit-test environment, which
is itself the "emit node unreachable" failure mode under test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import node_event_emit_effect_dispatch as dispatch_module  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_kafka_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee no unit test can reach a live Kafka broker.

    Also doubles as the "emit node unreachable" failure-injection fixture:
    an absent bootstrap-server target is exactly the fail-open scenario
    AC3 requires (dispatch must degrade to spool-only / a caught exception,
    never raise out of ``main()``).
    """
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)


def test_parse_payload_returns_empty_dict_for_malformed_json() -> None:
    """Malformed --payload JSON must never raise -- degrades to {}."""
    assert dispatch_module._parse_payload("{not valid json") == {}
    assert dispatch_module._parse_payload("") == {}
    assert dispatch_module._parse_payload("null") == {}
    assert dispatch_module._parse_payload("[1, 2, 3]") == {}


def test_parse_payload_returns_dict_for_valid_json() -> None:
    raw = json.dumps({"session_id": "abc123", "working_directory": "/tmp"})
    assert dispatch_module._parse_payload(raw) == {
        "session_id": "abc123",
        "working_directory": "/tmp",
    }


def test_main_exits_zero_with_malformed_payload_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC3: malformed --payload input never raises and always exits 0."""
    exit_code = dispatch_module.main(
        [
            "--event-type",
            "onex.evt.omniclaude.session-started.v1",
            "--payload",
            "{this is not json",
        ]
    )
    assert exit_code == 0


def test_main_exits_zero_when_required_argument_missing() -> None:
    """AC3: argparse SystemExit on bad args must not propagate a non-zero exit."""
    exit_code = dispatch_module.main([])  # missing required --event-type
    assert exit_code == 0


def test_main_exits_zero_when_emit_node_unreachable() -> None:
    """AC3: no reachable Kafka bus (KAFKA_BOOTSTRAP_SERVERS unset) -> exit 0.

    Drives the REAL HandlerEventEmitEffect / ModelEmitRequest classes (a
    pinned omnimarket dependency) with no bus target configured. Whatever
    omnimarket's own contract does internally (spool-only degrade or a
    raised configuration error), this wrapper's fail-open boundary must
    absorb it.
    """
    exit_code = dispatch_module.main(
        [
            "--event-type",
            "onex.evt.omniclaude.session-started.v1",
            "--payload",
            json.dumps({"session_id": "unit-test-unreachable"}),
        ]
    )
    assert exit_code == 0


def test_dispatch_returns_false_when_emit_node_unreachable() -> None:
    """The lower-level _dispatch() helper mirrors the same fail-open contract."""
    published = dispatch_module._dispatch(
        event_type="onex.evt.omniclaude.session-started.v1",
        payload={"session_id": "unit-test-unreachable"},
        correlation_id="unit-test-corr",
        max_attempts=1,
    )
    assert published is False


def test_dispatch_absorbs_handler_raising_outright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3: a handler that raises (e.g. a spool-full-class exception) never propagates.

    Simulates the emit node's own durability layer refusing to accept the
    event (the ``SpoolFullError`` failure mode named in the ticket) by
    monkeypatching ``HandlerEventEmitEffect.handle`` to raise directly.
    """
    from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
        HandlerEventEmitEffect,
    )

    def _raise(self: object, request: object) -> None:
        raise RuntimeError("simulated SpoolFullError: outbox at capacity")

    monkeypatch.setattr(HandlerEventEmitEffect, "handle", _raise)

    published = dispatch_module._dispatch(
        event_type="onex.evt.omniclaude.session-started.v1",
        payload={"session_id": "unit-test-spool-full"},
        correlation_id="unit-test-corr",
        max_attempts=2,
    )
    assert published is False


def test_dispatch_absorbs_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: an unimportable omnimarket package degrades to a no-op, not a raise."""
    import builtins

    real_import = builtins.__import__

    def _blow_up(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("omnimarket"):
            raise ModuleNotFoundError(f"simulated missing package: {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blow_up)

    published = dispatch_module._dispatch(
        event_type="onex.evt.omniclaude.session-started.v1",
        payload={"session_id": "unit-test-import-failure"},
        correlation_id="unit-test-corr",
        max_attempts=1,
    )
    assert published is False


def test_dispatch_constructs_request_with_given_event_type_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirms the direct-dispatch call site: event_type/payload/correlation_id
    flow through to a real ``ModelEmitRequest`` and ``HandlerEventEmitEffect.handle()``
    call (asserted via a handle() spy), independent of publish success.
    """
    from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
        HandlerEventEmitEffect,
    )

    captured: dict[str, object] = {}

    def _spy_handle(self: object, request: Any) -> object:
        captured["event_type"] = request.event_type
        captured["payload"] = request.payload
        captured["correlation_id"] = request.correlation_id

        class _FakeResult:
            published = True
            spool_only = False
            topics_published = [request.event_type]
            event_id = "fake-event-id"

        return _FakeResult()

    monkeypatch.setattr(HandlerEventEmitEffect, "handle", _spy_handle)

    published = dispatch_module._dispatch(
        event_type="onex.evt.omniclaude.session-ended.v1",
        payload={"session_id": "unit-test-construct", "reason": "clear"},
        correlation_id="unit-test-corr-construct",
        max_attempts=1,
    )

    assert published is True
    assert captured["event_type"] == "onex.evt.omniclaude.session-ended.v1"
    assert captured["payload"] == {
        "session_id": "unit-test-construct",
        "reason": "clear",
    }
    assert captured["correlation_id"] == "unit-test-corr-construct"


def test_dispatch_retries_up_to_max_attempts_then_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bounded retry: a persistently-failing publish stops after max_attempts."""
    from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
        HandlerEventEmitEffect,
    )

    call_count = {"n": 0}

    def _always_unpublished(self: object, request: object) -> object:
        call_count["n"] += 1

        class _FakeResult:
            published = False
            spool_only = False

        return _FakeResult()

    monkeypatch.setattr(HandlerEventEmitEffect, "handle", _always_unpublished)

    published = dispatch_module._dispatch(
        event_type="onex.evt.omniclaude.session-started.v1",
        payload={},
        correlation_id=None,
        max_attempts=3,
    )
    assert published is False
    assert call_count["n"] == 3


def test_main_always_returns_int_zero_type() -> None:
    """main() return type must be exactly int 0 (used as a process exit code)."""
    exit_code = dispatch_module.main(
        ["--event-type", "onex.evt.omniclaude.session-started.v1", "--payload", "{}"]
    )
    assert exit_code == 0
    assert isinstance(exit_code, int)
