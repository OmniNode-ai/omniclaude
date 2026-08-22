# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The three OMN-15600 alert call sites must not discard delivery outcome.

Named in the ticket:

* ``plugins/onex/hooks/scripts/common.sh`` :: ``slack_notify``
* ``plugins/onex/hooks/scripts/common.sh`` :: ``notify_hook_degraded``
* ``plugins/onex/hooks/scripts/error-guard.sh`` :: the EXIT trap alert

Each drove ``curl ... >/dev/null 2>&1`` and branched only on whether
``SLACK_WEBHOOK_URL`` was non-empty. Against a webhook returning HTTP 404 the
observable behaviour was byte-identical to a healthy send. These tests assert
the 404 case is now distinguishable from the 200 case at each call site.

RED at commit 8c1e3d96 (``origin/dev``): ``slack_notify`` returns 0 and writes
nothing when the endpoint is dead.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[4]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "onex"
_SCRIPTS_DIR = _PLUGIN_ROOT / "hooks" / "scripts"


@dataclass
class _FakeSlack:
    url: str
    requests: list[str] = field(default_factory=list)


class _Handler(http.server.BaseHTTPRequestHandler):
    status: int = 404
    body: bytes = b"no_service"
    sink: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        type(self).sink.append(self.path)
        self.send_response(type(self).status)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_args: object) -> None:
        """Silence the default stderr access log."""


def _serve(status: int, body: bytes) -> Iterator[_FakeSlack]:
    sink: list[str] = []
    handler = type(
        "_BoundHandler", (_Handler,), {"status": status, "body": body, "sink": sink}
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield _FakeSlack(
            url=f"http://{server.server_address[0]}:{server.server_address[1]}",
            requests=sink,
        )
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def dead_webhook() -> Iterator[_FakeSlack]:
    """Reproduces the live behaviour of the revoked webhook (404 no_service)."""
    yield from _serve(404, b"no_service")


@pytest.fixture
def live_webhook() -> Iterator[_FakeSlack]:
    yield from _serve(200, b"ok")


@dataclass
class _Bench:
    failure_log: Path
    notify_record: Path
    env: dict[str, str]


@pytest.fixture
def bench(tmp_path: Path) -> _Bench:
    failure_log = tmp_path / "alert_delivery_failures.log"
    notify_record = tmp_path / "local-notify.received"
    notifier = tmp_path / "notifier.sh"
    notifier.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{notify_record}"\n', encoding="utf-8"
    )
    notifier.chmod(0o755)
    return _Bench(
        failure_log=failure_log,
        notify_record=notify_record,
        env={
            "ONEX_ALERT_DELIVERY_LOG": str(failure_log),
            "ONEX_ALERT_LOCAL_NOTIFY_CMD": str(notifier),
            "ONEX_ALERT_LOCAL_NOTIFY_RATE_DIR": str(tmp_path / "rate"),
            "ONEX_ALERT_CURL_CONNECT_TIMEOUT": "2",
            "ONEX_ALERT_CURL_MAX_TIME": "5",
        },
    )


def _base_env(bench: _Bench, tmp_path: Path, webhook_url: str) -> dict[str, str]:
    """Build a hermetic environment for sourcing common.sh / error-guard.sh.

    ``common.sh`` sources ``${HOME}/.omnibase/.env`` under ``set -a``, which
    overrides anything the caller exported. Pointing HOME at a test-owned
    directory is therefore mandatory: without it these tests would pick up the
    developer's real Slack credentials and post to the real workspace.
    """
    fake_home = tmp_path / "home"
    (fake_home / ".omnibase").mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(fake_home),
        "PLUGIN_ROOT": str(_PLUGIN_ROOT),
        "PROJECT_ROOT": "",
        "LOG_FILE": str(tmp_path / "hooks.log"),
        "OMNICLAUDE_MODE": "full",
        "PLUGIN_PYTHON_BIN": sys.executable,
        "SLACK_WEBHOOK_URL": webhook_url,
        # Ensure the machine's real bot token is never used by these tests.
        "SLACK_BOT_TOKEN": "",
        "SLACK_CHANNEL_ID": "",
        **bench.env,
    }


def _run(
    script: str, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script, "--", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
        check=False,
    )


class TestSlackNotifyCallSite:
    """common.sh :: slack_notify (the generic hook/daemon failure alert)."""

    _SCRIPT = """\
set -uo pipefail
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
slack_notify "$1" "$2"
echo "rc=$?"
"""

    def test_dead_webhook_is_distinguishable_from_healthy(
        self, bench: _Bench, tmp_path: Path, dead_webhook: _FakeSlack
    ) -> None:
        env = _base_env(bench, tmp_path, f"{dead_webhook.url}/services/T0/B0/X")
        # Unique category per run so the 5-minute rate limiter cannot suppress.
        result = _run(self._SCRIPT, env, f"omn15600-dead-{os.getpid()}", "canary")
        assert "rc=1" in result.stdout, (
            f"slack_notify swallowed a 404: {result.stdout!r} {result.stderr!r}"
        )
        assert bench.failure_log.exists()
        assert "HTTP_404" in bench.failure_log.read_text(encoding="utf-8")
        assert bench.notify_record.exists()

    def test_live_webhook_stays_silent(
        self, bench: _Bench, tmp_path: Path, live_webhook: _FakeSlack
    ) -> None:
        env = _base_env(bench, tmp_path, f"{live_webhook.url}/services/T0/B0/X")
        result = _run(self._SCRIPT, env, f"omn15600-live-{os.getpid()}", "canary")
        assert "rc=0" in result.stdout, result.stdout
        assert not bench.failure_log.exists()


class TestNotifyHookDegradedCallSite:
    """common.sh :: notify_hook_degraded (the degraded-hook alert)."""

    _SCRIPT = """\
set -uo pipefail
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
notify_hook_degraded "$1" "$2"
echo "rc=$?"
"""

    def test_dead_webhook_is_reported(
        self, bench: _Bench, tmp_path: Path, dead_webhook: _FakeSlack
    ) -> None:
        env = _base_env(bench, tmp_path, f"{dead_webhook.url}/services/T0/B0/X")
        result = _run(
            self._SCRIPT,
            env,
            f"omn15600hook{os.getpid()}",
            f"ModuleNotFoundError canary {os.getpid()}",
        )
        assert "rc=1" in result.stdout, result.stdout
        assert bench.failure_log.exists()
        assert "HTTP_404" in bench.failure_log.read_text(encoding="utf-8")


class TestErrorGuardCallSite:
    """error-guard.sh :: EXIT trap alert.

    The trap must still exit 0 (Claude Code must never see the failure) while
    the dead channel is recorded on the durable surface.
    """

    _SCRIPT = """\
set -uo pipefail
_OMNICLAUDE_HOOK_NAME="omn15600-guard-canary"
source "${PLUGIN_ROOT}/hooks/scripts/error-guard.sh"
exit 3
"""

    def test_trap_still_exits_zero_but_records_dead_channel(
        self, bench: _Bench, tmp_path: Path, dead_webhook: _FakeSlack
    ) -> None:
        env = _base_env(bench, tmp_path, f"{dead_webhook.url}/services/T0/B0/X")
        env["_ERROR_GUARD_LOG_DIR"] = str(tmp_path / "guard")
        result = _run(self._SCRIPT, env)
        assert result.returncode == 0, (
            "error-guard must keep swallowing the hook failure for Claude Code"
        )
        assert bench.failure_log.exists(), (
            "error-guard discarded the alert delivery outcome"
        )
        assert "HTTP_404" in bench.failure_log.read_text(encoding="utf-8")
