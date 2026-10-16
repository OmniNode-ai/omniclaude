# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook lands each raw event on the host's local bus first (OMN-19513).

A stand-in HTTP proxy (``http.server`` on a loopback port) plays the Redpanda
HTTP proxy, so every test exercises the real HTTP request the hook makes.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_HANDLER = (
    _REPO / "src" / "omniclaude" / "handlers" / "handler_hook_local_bus_publish.py"
)
_CONTRACT = _REPO / "src" / "omniclaude" / "contracts" / "hook_local_bus.json"
_LIB_DIR = _REPO / "plugins" / "onex" / "hooks" / "lib"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def handler() -> Any:
    return _load(_HANDLER, "handler_hook_local_bus_publish_under_test")


class _Proxy:
    """What the stand-in proxy received, and how it answers."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], bytes]] = []
        self.answer: dict[str, object] = {"offsets": [{"partition": 0, "offset": 7}]}
        self.hang_s = 0.0


@pytest.fixture
def proxy() -> Iterator[tuple[_Proxy, str]]:
    state = _Proxy()

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state.requests.append((self.path, dict(self.headers), body))
            if state.hang_s:
                time.sleep(state.hang_s)
            blob = json.dumps(state.answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.kafka.v2+json")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _contract() -> dict[str, Any]:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _event(handler: Any, tmp_path: Path, **overrides: object) -> Any:
    fields: dict[str, object] = {
        "event_type": "tool.executed",
        "payload": {"session_id": "s-1", "tool_name": "Bash"},
        "correlation_id": "c-1",
        "journal_dir": tmp_path / "journal",
    }
    fields.update(overrides)
    return handler.ModelHookBusPublishRequest(**fields)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_no_local_bus_declared_sends_nothing(handler: Any, tmp_path: Path) -> None:
    result = handler.handle(_event(handler, tmp_path), environ={})
    assert result.outcome == handler.EnumHookBusPublishOutcome.NO_LOCAL_BUS


def test_publishes_an_emit_request_envelope_to_the_contract_topic(
    handler: Any, tmp_path: Path, proxy: tuple[_Proxy, str]
) -> None:
    state, url = proxy
    contract = _contract()
    result = handler.handle(
        _event(handler, tmp_path), environ={contract["url_env"]: url}
    )
    assert result.outcome == handler.EnumHookBusPublishOutcome.PUBLISHED
    assert len(state.requests) == 1
    path, headers, body = state.requests[0]
    assert path == f"/topics/{contract['command_topic']}"
    assert headers["Content-Type"] == "application/vnd.kafka.json.v2+json"
    record = json.loads(body)["records"][0]
    assert record["key"] == "s-1"
    envelope = record["value"]
    assert envelope["event_type"] == contract["command_topic"]
    emit = envelope["payload"]
    assert emit["event_type"] == "tool.executed"
    assert emit["correlation_id"] == "c-1"
    assert emit["event_id"] == result.event_id
    assert emit["payload"]["tool_name"] == "Bash"
    # The fire time the drainer stamped travels with the event.
    assert emit["payload"][contract["fire_time_key"]].startswith("20")
    assert not (tmp_path / "journal").exists()


def test_a_record_error_from_the_proxy_is_unreachable(
    handler: Any, tmp_path: Path, proxy: tuple[_Proxy, str]
) -> None:
    state, url = proxy
    state.answer = {"offsets": [{"partition": -1, "offset": -1, "error_code": 50003}]}
    result = handler.handle(
        _event(handler, tmp_path), environ={_contract()["url_env"]: url}
    )
    assert result.outcome == handler.EnumHookBusPublishOutcome.UNREACHABLE
    assert "50003" in result.detail


def test_a_refused_connection_is_unreachable(handler: Any, tmp_path: Path) -> None:
    url = f"http://127.0.0.1:{_free_port()}"
    result = handler.handle(
        _event(handler, tmp_path), environ={_contract()["url_env"]: url}
    )
    assert result.outcome == handler.EnumHookBusPublishOutcome.UNREACHABLE


def test_a_hung_proxy_is_cut_off_at_the_contract_timeout(
    handler: Any, tmp_path: Path, proxy: tuple[_Proxy, str]
) -> None:
    state, url = proxy
    state.hang_s = 3.0
    started = time.monotonic()
    result = handler.handle(
        _event(handler, tmp_path), environ={_contract()["url_env"]: url}
    )
    elapsed = time.monotonic() - started
    assert result.outcome == handler.EnumHookBusPublishOutcome.UNREACHABLE
    assert elapsed < _contract()["timeout_ms"] / 1000 + 0.5


def test_an_oversized_event_is_quarantined_with_a_reason_and_never_sent(
    handler: Any, tmp_path: Path, proxy: tuple[_Proxy, str]
) -> None:
    state, url = proxy
    contract = _contract()
    big = {"session_id": "s-1", "blob": "x" * (contract["max_record_bytes"] + 1)}
    result = handler.handle(
        _event(handler, tmp_path, payload=big), environ={contract["url_env"]: url}
    )
    assert result.outcome == handler.EnumHookBusPublishOutcome.QUARANTINED
    assert state.requests == []
    held = tmp_path / "journal" / contract["quarantine_dirname"]
    records = sorted(held.glob("*.json"))
    assert [p.name for p in records] == [f"{result.event_id}.json"]
    stored = json.loads(records[0].read_text(encoding="utf-8"))
    assert stored["reason"]["reason_code"] == "payload_too_large"
    assert stored["reason"]["limit_bytes"] == contract["max_record_bytes"]
    assert stored["record"]["event_type"] == "tool.executed"


def test_handler_imports_nothing_heavy() -> None:
    """The hook fast path stays stdlib-only (the OMN-17224 regression guard)."""
    probe = (
        "import importlib.util, sys; "
        f"spec = importlib.util.spec_from_file_location('h', {str(_HANDLER)!r}); "
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
        "heavy = sorted(n for n in sys.modules "
        "if n.split('.')[0] in {'omnibase_infra', 'omnimarket', 'pydantic', 'aiokafka', 'yaml'}); "
        "print(','.join(heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert out.stdout.strip() == ""


def _append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str | None) -> Path:
    contract = _contract()
    if url is None:
        monkeypatch.delenv(contract["url_env"], raising=False)
    else:
        monkeypatch.setenv(contract["url_env"], url)
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    jdir = tmp_path / "journal"
    sys.path.insert(0, str(_LIB_DIR))
    try:
        append = _load(_LIB_DIR / "hook_emit_append.py", "hook_emit_append_under_test")
        append.append_event(
            event_type="tool.executed",
            payload={"session_id": "s-1", "tool_name": "Bash"},
            correlation_id="c-1",
            cwd=str(tmp_path),
            actor=None,
            host_turn_id=None,
            agent_id=None,
            transcript_path=None,
            session_id="s-1",
            journal_dir=str(jdir),
        )
    finally:
        sys.path.remove(str(_LIB_DIR))
    return jdir


def _journalled(jdir: Path) -> list[Path]:
    return sorted(jdir.glob("*.json")) if jdir.is_dir() else []


def test_append_lands_on_the_local_bus_and_journals_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, proxy: tuple[_Proxy, str]
) -> None:
    state, url = proxy
    jdir = _append(tmp_path, monkeypatch, url)
    assert len(state.requests) == 1
    assert _journalled(jdir) == []


def test_append_journals_while_the_local_bus_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jdir = _append(tmp_path, monkeypatch, f"http://127.0.0.1:{_free_port()}")
    assert len(_journalled(jdir)) == 1


def test_append_journals_on_a_host_with_no_local_bus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jdir = _append(tmp_path, monkeypatch, None)
    assert len(_journalled(jdir)) == 1
