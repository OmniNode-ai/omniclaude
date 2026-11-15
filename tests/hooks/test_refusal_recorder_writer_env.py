# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The recorder's writer process publishes over the bus, not into the file (OMN-24504).

The friction guard runs inside the ledger serve's held lock and calls the recorder from there, so
the recorder inherits the serve's direct-write markers. Left in place, ``onex-ledger`` appends the
row to the file and the row carries no ``via=`` cell.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (
    handler_hook_refusal_record as recorder,
)

pytestmark = pytest.mark.unit

SERVE_ENV = {
    "ONEX_LEDGER_WRITE_VIA": "local",
    "ONEX_LEDGER_RECORD_WRITER": "work-ledger-serve",
}


def _record_env(
    monkeypatch: pytest.MonkeyPatch, caller: dict[str, str] = SERVE_ENV
) -> dict[str, str]:
    """The environment the writer subprocess is started with, from a caller with ``caller``."""
    seen: list[dict[str, str]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        seen.append(env)
        return subprocess.CompletedProcess(args, returncode=0)

    for name, value in caller.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    done = recorder._run_writer(
        "row", ledger=Path("/x"), project=Path("/y"), timeout="1s"
    )
    assert done is not None and done.returncode == 0
    assert len(seen) == 1
    return seen[0]


def test_writer_environment_drops_the_direct_write_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _record_env(monkeypatch)

    assert not set(SERVE_ENV) & set(env)
    assert "PATH" in env


def test_bus_environment_keeps_a_declared_bus_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host that declares the bus keeps it: only the direct-write settings are dropped."""
    env = _record_env(monkeypatch, {"ONEX_LEDGER_WRITE_VIA": "bus"})

    assert env["ONEX_LEDGER_WRITE_VIA"] == "bus"


def test_bus_environment_control_keeps_the_markers_when_the_list_is_emptied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failing control: the injected break (an empty marker list) leaves them in place."""
    monkeypatch.setattr(recorder, "DIRECT_WRITE_ENV", ())

    env = _record_env(monkeypatch)

    assert set(SERVE_ENV) <= set(env)


def test_error_chain_writer_that_cannot_start_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error chain: a writer that raises OSError is a failed recording, never an exception."""

    def raise_os_error(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("fixture writer unavailable")

    monkeypatch.setattr(recorder.subprocess, "run", raise_os_error)

    assert (
        recorder._run_writer("row", ledger=Path("/x"), project=Path("/y"), timeout="1s")
        is None
    )
