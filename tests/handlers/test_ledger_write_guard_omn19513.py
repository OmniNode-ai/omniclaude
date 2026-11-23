# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The ledger test-write guard: a test process never writes the canonical ledger (OMN-19513).

The falsifier reproduces the leak of 2026-10-01 (fixture rows from a lab host's test run reached
the ledger of record) for the v2 work-ledger emit through a daemon that reaches the real topics.
It is refused with exit 79 / the guard named and emits nothing; the same emit to a scratch socket
succeeds; and with the refusal switched off the same emit lands, so these tests fail without the
guard. The hook-process canary's ledger writer no longer opens a ledger file (OMN-26568), so it
has no file-write case here.

"Canonical" is judged against the temporary directory, so each test narrows the guard's temporary
root to ``tmp_path/scratch`` and puts the "real" socket beside it: every byte these tests could
write, even on a regression, stays under ``tmp_path``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from omniclaude.handlers import handler_ledger_write_guard as guard
from omniclaude.hooks.event_registry import EVENT_REGISTRY
from plugins.onex.hooks.lib import emit_client_wrapper

REPO = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO / "src" / "omniclaude" / "handlers" / "handler_ledger_write_guard.py"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(guard, "_temp_root", scratch.resolve)
    return {"scratch": scratch}


class FakeClient:
    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self.emitted: list[tuple[str, dict[str, object]]] = []

    def emit_sync(self, event_type: str, payload: dict[str, object]) -> str:
        self.emitted.append((event_type, payload))
        return "event-1"


def with_client(monkeypatch: pytest.MonkeyPatch, socket_path: Path) -> FakeClient:
    client = FakeClient(str(socket_path))
    monkeypatch.setattr(emit_client_wrapper, "_get_client", lambda: client)
    return client


def test_v2_ledger_emit_through_a_real_socket_is_refused_and_emits_nothing(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = with_client(monkeypatch, tmp_path / "real-emit.sock")
    with pytest.raises(guard.LedgerTestWriteRefused, match=guard.GUARD_NAME):
        emit_client_wrapper.emit_event("work.ledger.typed.claim", {"ledger_id": "x"})
    assert client.emitted == []


def test_v2_ledger_emit_through_a_scratch_socket_succeeds(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = with_client(monkeypatch, world["scratch"] / "emit.sock")
    assert emit_client_wrapper.emit_event("work.ledger.typed.claim", {"ledger_id": "x"})
    assert [e[0] for e in client.emitted] == ["work.ledger.typed.claim"]


def test_v2_ledger_emit_lands_with_the_refusal_switched_off(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = with_client(monkeypatch, tmp_path / "real-emit.sock")
    monkeypatch.setattr(guard, "_refuse_if_test", lambda kind, target: None)
    assert emit_client_wrapper.emit_event("work.ledger.typed.claim", {"ledger_id": "x"})
    assert len(client.emitted) == 1


def test_a_non_ledger_event_through_a_real_socket_is_not_judged(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = with_client(monkeypatch, tmp_path / "real-emit.sock")
    assert emit_client_wrapper.emit_event("session.started", {"session_id": "s"})
    assert len(client.emitted) == 1


def test_cli_emit_of_a_v2_ledger_event_exits_79(
    world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = with_client(monkeypatch, tmp_path / "real-emit.sock")
    args = type(
        "Args",
        (),
        {"payload": "{}", "timeout": None, "event_type": "work.ledger.typed.msg"},
    )
    assert emit_client_wrapper._cli_emit(args) == 79
    assert client.emitted == []


@pytest.mark.parametrize(
    ("topic", "code"),
    [
        ("onex.evt.omnimarket.work-ledger-claim.v2", 79),
        ("onex.cmd.omnimarket.work-ledger-append-requested.v1", 79),
        ("onex.evt.omnimarket.test-scratch.v1", 0),
    ],
)
def test_the_command_form_refuses_a_canonical_topic(topic: str, code: int) -> None:
    done = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--topic", topic],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == code
    assert (guard.GUARD_NAME in done.stderr) == (code == 79)


def test_every_registry_event_that_fans_out_to_a_ledger_topic_is_judged() -> None:
    ledger_events = {
        event_type
        for event_type, registration in EVENT_REGISTRY.items()
        if any(
            guard.topic_is_canonical(rule.topic_base.value)
            for rule in registration.fan_out
        )
    }
    assert ledger_events
    assert all(e.startswith(guard.LEDGER_EVENT_PREFIX) for e in ledger_events)
    typed = {e for e in EVENT_REGISTRY if e.startswith(guard.LEDGER_EVENT_PREFIX)}
    assert typed == ledger_events


def test_the_suite_gives_each_test_a_scratch_ledger_and_no_bus() -> None:
    assert os.environ["ONEX_TEST_CONTEXT"] == "pytest"
    assert re.search(r"no-ledger\.md$", os.environ["ONEX_LEDGER_PATH"])
    assert "ONEX_LEDGER_WRITE_VIA" not in os.environ
    assert not any(k.startswith("KAFKA_") for k in os.environ)
