# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Alert-channel delivery must fail LOUDLY on a dead channel (OMN-15600).

RED-before / GREEN-after contract for the defect filed in OMN-15600:

    ``SLACK_WEBHOOK_URL`` pointed at a revoked Slack webhook (live HTTP 404
    ``no_service``) for an unknown period. All three hook alert call sites
    branched only on whether the variable was non-empty and discarded the
    ``curl`` outcome, so a configured-but-dead webhook was indistinguishable
    from a healthy one and every alert delivered to nothing, silently.

These tests drive the real shell artifacts that run in production
(``alert-channel.sh``, ``common.sh``, ``error-guard.sh``) against a local HTTP
server that reproduces Slack's dead-webhook response, and assert three distinct
states — delivered / configured-but-dead / not configured. The middle state is
the one that did not exist before this change.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[4]
_SCRIPTS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
_ALERT_CHANNEL_SH = _SCRIPTS_DIR / "alert-channel.sh"

# Slack's verbatim response for a webhook whose owning app no longer exists.
_DEAD_WEBHOOK_BODY = b"no_service"


@dataclass
class _FakeSlack:
    """A local stand-in for Slack's HTTP surface."""

    url: str
    requests: list[tuple[str, int]] = field(default_factory=list)


class _Handler(http.server.BaseHTTPRequestHandler):
    # Set per-server by _serve().
    status: int = 200
    body: bytes = b"ok"
    sink: list[tuple[str, int]] = []

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0") or 0)
        self.rfile.read(length)
        type(self).sink.append((self.path, length))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_args: object) -> None:
        """Silence the default stderr access log."""


def _serve(status: int, body: bytes) -> Iterator[_FakeSlack]:
    sink: list[tuple[str, int]] = []
    handler = type(
        "_BoundHandler",
        (_Handler,),
        {"status": status, "body": body, "sink": sink},
    )
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield _FakeSlack(url=f"http://{host}:{port}", requests=sink)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def dead_webhook() -> Iterator[_FakeSlack]:
    """A webhook that answers exactly like the revoked OMN-15058 webhook."""
    yield from _serve(404, _DEAD_WEBHOOK_BODY)


@pytest.fixture
def live_webhook() -> Iterator[_FakeSlack]:
    yield from _serve(200, b"ok")


@pytest.fixture
def live_api() -> Iterator[_FakeSlack]:
    """Slack Web API shape: HTTP 200 plus an ``ok`` field in the JSON body."""
    yield from _serve(200, json.dumps({"ok": True, "ts": "1.0"}).encode())


@dataclass
class _Bench:
    """Isolated durable-log + local-notification surfaces for one test."""

    failure_log: Path
    notify_record: Path
    env: dict[str, str]


@pytest.fixture
def bench(tmp_path: Path) -> _Bench:
    """Point the durable log and the local notifier at test-owned files.

    ``ONEX_ALERT_LOCAL_NOTIFY_CMD`` is the same real seam a headless host uses
    to swap ``osascript`` for another notifier — the test drives the production
    code path, it does not stub it.
    """
    failure_log = tmp_path / "alert_delivery_failures.log"
    notify_record = tmp_path / "local-notify.received"
    notifier = tmp_path / "notifier.sh"
    notifier.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{notify_record}"\n',
        encoding="utf-8",
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


def _run_send(
    bench: _Bench,
    *,
    category: str = "test_category",
    message: str = "alerting canary",
    webhook_url: str | None = None,
    bot_token: str | None = None,
    channel_id: str | None = None,
    api_base: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke alert_channel_send from the real library file."""
    script = f'source "{_ALERT_CHANNEL_SH}"\nalert_channel_send "$1" "$2"\n'
    env = {
        # A deliberately minimal environment: the library must not depend on
        # common.sh, Python, or jq (error-guard.sh sources it before common.sh).
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        **bench.env,
    }
    if webhook_url is not None:
        env["SLACK_WEBHOOK_URL"] = webhook_url
    if bot_token is not None:
        env["SLACK_BOT_TOKEN"] = bot_token
    if channel_id is not None:
        env["SLACK_CHANNEL_ID"] = channel_id
    if api_base is not None:
        env["SLACK_API_BASE_URL"] = api_base
    return subprocess.run(
        ["bash", "-c", script, "--", category, message],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


class TestDeadWebhookFailsLoudly:
    """The load-bearing half of OMN-15600 AC-2 and AC-3."""

    def test_dead_webhook_returns_failure(
        self, bench: _Bench, dead_webhook: _FakeSlack
    ) -> None:
        """A 404 webhook must be reported as a delivery failure, not swallowed."""
        result = _run_send(bench, webhook_url=f"{dead_webhook.url}/services/T0/B0/X")
        assert result.returncode == 1, (
            "configured-but-dead webhook must return 1 (delivery failed); "
            f"got {result.returncode}. stderr={result.stderr}"
        )
        assert dead_webhook.requests, "the send must actually have been attempted"

    def test_dead_webhook_writes_durable_log_entry(
        self, bench: _Bench, dead_webhook: _FakeSlack
    ) -> None:
        """A human must be able to find out later that alerting was broken."""
        _run_send(bench, webhook_url=f"{dead_webhook.url}/services/T0/B0/X")
        assert bench.failure_log.exists(), "no durable delivery-failure log written"
        contents = bench.failure_log.read_text(encoding="utf-8")
        assert "DELIVERY FAILED" in contents
        assert "HTTP_404" in contents, f"HTTP status not recorded: {contents!r}"

    def test_dead_webhook_fires_local_fallback_notification(
        self, bench: _Bench, dead_webhook: _FakeSlack
    ) -> None:
        """A human at the machine must be told the alert channel is broken."""
        _run_send(bench, webhook_url=f"{dead_webhook.url}/services/T0/B0/X")
        assert bench.notify_record.exists(), (
            "no local fallback notification fired — a dead alert channel that "
            "only logs is still silent to the operator"
        )
        assert "alert" in bench.notify_record.read_text(encoding="utf-8").lower()

    def test_secret_never_appears_in_failure_log(
        self, bench: _Bench, dead_webhook: _FakeSlack
    ) -> None:
        """Failing loudly must not turn the log into a credential leak."""
        url = f"{dead_webhook.url}/services/T08SECRET/B09SECRET/tokenvalue"
        _run_send(bench, webhook_url=url)
        contents = bench.failure_log.read_text(encoding="utf-8")
        assert "tokenvalue" not in contents
        assert "T08SECRET" not in contents


class TestThreeDistinctStates:
    """OMN-15600 AC-5: set-but-dead is a distinct state from unset."""

    def test_live_webhook_is_silent_and_succeeds(
        self, bench: _Bench, live_webhook: _FakeSlack
    ) -> None:
        result = _run_send(bench, webhook_url=f"{live_webhook.url}/services/T0/B0/X")
        assert result.returncode == 0
        assert not bench.failure_log.exists()
        assert not bench.notify_record.exists()

    def test_unconfigured_is_a_silent_no_op(self, bench: _Bench) -> None:
        """No channel configured is not an alerting failure — return 2, stay quiet."""
        result = _run_send(bench)
        assert result.returncode == 2, (
            "unset must be its own state (2), distinguishable from "
            f"configured-but-dead (1); got {result.returncode}"
        )
        assert not bench.failure_log.exists()
        assert not bench.notify_record.exists()


class TestBotTokenPreferredOverWebhook:
    """OMN-15600: a bot token is webhook-independent, so prefer it."""

    def test_bot_token_used_first_and_webhook_not_touched(
        self, bench: _Bench, live_api: _FakeSlack, dead_webhook: _FakeSlack
    ) -> None:
        result = _run_send(
            bench,
            bot_token="xoxb-test-token",  # secret-ok: test fixture
            channel_id="C0TEST",
            api_base=f"{live_api.url}/api",
            webhook_url=f"{dead_webhook.url}/services/T0/B0/X",
        )
        assert result.returncode == 0, result.stderr
        assert any(path.endswith("/chat.postMessage") for path, _ in live_api.requests)
        assert not dead_webhook.requests, (
            "webhook must not be used when the bot token already delivered"
        )

    def test_webhook_is_the_fallback_when_bot_token_fails(
        self, bench: _Bench, live_webhook: _FakeSlack, dead_webhook: _FakeSlack
    ) -> None:
        result = _run_send(
            bench,
            bot_token="xoxb-revoked",  # secret-ok: test fixture
            channel_id="C0TEST",
            api_base=f"{dead_webhook.url}/api",
            webhook_url=f"{live_webhook.url}/services/T0/B0/X",
        )
        assert result.returncode == 0, result.stderr
        assert live_webhook.requests

    def test_http_200_with_ok_false_counts_as_dead(
        self, bench: _Bench, tmp_path: Path
    ) -> None:
        """Slack answers 200 + ``{"ok":false}`` for a revoked bot token.

        Status-code-only checking would score that as delivered.
        """
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            result = _run_send(
                bench,
                bot_token="xoxb-revoked",  # secret-ok: test fixture
                channel_id="C0TEST",
                api_base=f"{api.url}/api",
            )
        finally:
            with pytest.raises(StopIteration):
                next(gen)
        assert result.returncode == 1, (
            'HTTP 200 with {"ok":false} must be treated as a delivery failure'
        )
        contents = bench.failure_log.read_text(encoding="utf-8")
        assert "invalid_auth" in contents


class TestLocalNotifierDefaultsToOsascriptOnMacOS:
    """The default notifier must be real, not only the test-supplied one."""

    @pytest.mark.skipif(
        not Path("/usr/bin/osascript").exists(), reason="macOS-only default"
    )
    def test_default_notifier_is_osascript(self) -> None:
        script = f'source "{_ALERT_CHANNEL_SH}"\nalert_channel_local_notifier_cmd\n'
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        assert result.stdout.strip() == "/usr/bin/osascript"
