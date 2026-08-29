# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Alert-channel liveness must be checked, not assumed (OMN-15600).

AC-2 of the ticket: "point the checker at a known-dead channel ... and assert
the checker reports FAILURE and emits on the fallback path."

RED at commit 8c1e3d96 (``origin/dev``): ``omniclaude.hooks.alert_channel`` did
not exist and ``probe_hook_health()`` had no notion of alert delivery, so a
revoked webhook scored as healthy on every surface.

Revised AC1 (2026-08-27): the incoming webhook (``SLACK_WEBHOOK_URL``) is
retired entirely — it was revoked and never regenerated, and
``#omninode-notifications`` is already served by the bot-token path. The bot
token is the sole channel this probe checks; ``SLACK_WEBHOOK_URL`` is not read
anywhere in this module and must have zero effect if set.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from omniclaude.hooks.alert_channel import ModelAlertChannelHealth, probe_alert_channel
from omniclaude.hooks.hook_health_probe import probe_hook_health


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


@dataclass
class _Bench:
    failure_log: Path
    notify_record: Path


@pytest.fixture
def bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Bench:
    failure_log = tmp_path / "alert_delivery_failures.log"
    notify_record = tmp_path / "local-notify.received"
    notifier = tmp_path / "notifier.sh"
    notifier.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{notify_record}"\n', encoding="utf-8"
    )
    notifier.chmod(0o755)
    monkeypatch.setenv("ONEX_ALERT_DELIVERY_LOG", str(failure_log))
    monkeypatch.setenv("ONEX_ALERT_LOCAL_NOTIFY_CMD", str(notifier))
    monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "liveness.json"))
    monkeypatch.setenv("ONEX_ALERT_LIVENESS_TIMEOUT_SECONDS", "5")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_CHANNEL_ID", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    return _Bench(failure_log=failure_log, notify_record=notify_record)


class TestLivenessDetectsDeadChannel:
    def test_bot_token_http_200_with_ok_false_is_dead(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slack answers 200 + ok:false for a revoked token."""
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            token = "xoxb-revoked"  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_BOT_TOKEN", token)
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            result = probe_alert_channel(force=True)
        finally:
            with pytest.raises(StopIteration):
                next(gen)
        assert result.status == "dead"
        assert result.healthy is False
        assert result.dead_channels == ["bot_token"]
        assert "invalid_auth" in result.detail

    def test_dead_channel_emits_on_the_fallback_path(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure must surface through a channel that is NOT the dead one."""
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            monkeypatch.setenv(
                "SLACK_BOT_TOKEN", "xoxb-revoked"
            )  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            probe_alert_channel(force=True)
        finally:
            with pytest.raises(StopIteration):
                next(gen)
        assert bench.failure_log.exists()
        assert "CHANNEL DEAD" in bench.failure_log.read_text(encoding="utf-8")
        assert bench.notify_record.exists(), "no local fallback notification emitted"

    def test_live_bot_token_reports_live(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen = _serve(200, json.dumps({"ok": True, "team": "t"}).encode())
        api = next(gen)
        try:
            monkeypatch.setenv(
                "SLACK_BOT_TOKEN", "xoxb-live"
            )  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            result = probe_alert_channel(force=True)
        finally:
            with pytest.raises(StopIteration):
                next(gen)
        assert result.status == "live"
        assert result.healthy is True
        assert not bench.failure_log.exists()

    def test_unconfigured_is_not_dead(self, bench: _Bench) -> None:
        """Three states: unset is quiet, dead is loud (AC-5)."""
        result = probe_alert_channel(force=True)
        assert result.status == "not_configured"
        assert result.healthy is True
        assert not bench.failure_log.exists()

    def test_slack_webhook_url_has_zero_effect(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OMN-15600 revised AC1: the webhook is retired, not merely unread.

        Setting SLACK_WEBHOOK_URL to a value that looks like the historically
        dead webhook must not change the verdict — the module no longer reads
        that variable at all, and no bot token is configured, so this must
        still classify as NOT_CONFIGURED, never DEAD or LIVE.
        """
        monkeypatch.setenv(
            "SLACK_WEBHOOK_URL",
            "https://hooks.slack.com/services/T0/B0/XXXXXXXX",
        )
        result = probe_alert_channel(force=True)
        assert result.status == "not_configured"
        assert result.dead_channels == []
        assert result.live_channels == []


class TestLivenessCache:
    def test_second_probe_is_served_from_cache(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session start must not pay a network round trip every session."""
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            monkeypatch.setenv(
                "SLACK_BOT_TOKEN", "xoxb-revoked"
            )  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            probe_alert_channel(force=True)
            before = len(api.requests)
            cached = probe_alert_channel()
            assert cached.from_cache is True
            assert cached.status == "dead"
            assert len(api.requests) == before, "cache did not prevent a re-probe"
        finally:
            with pytest.raises(StopIteration):
                next(gen)

    def test_expired_cache_is_reprobed(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            monkeypatch.setenv(
                "SLACK_BOT_TOKEN", "xoxb-revoked"
            )  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            monkeypatch.setenv("ONEX_ALERT_LIVENESS_TTL_SECONDS", "0")
            probe_alert_channel(force=True)
            before = len(api.requests)
            probe_alert_channel()
            assert len(api.requests) > before
        finally:
            with pytest.raises(StopIteration):
                next(gen)


class TestHookHealthProbeSurfacesDeadChannel:
    """AC-4: the liveness check rides the EXISTING periodic health surface."""

    def test_probe_hook_health_reports_dead_channel(
        self, bench: _Bench, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen = _serve(200, json.dumps({"ok": False, "error": "invalid_auth"}).encode())
        api = next(gen)
        try:
            monkeypatch.setenv(
                "SLACK_BOT_TOKEN", "xoxb-revoked"
            )  # secret-ok: test fixture
            monkeypatch.setenv("SLACK_CHANNEL_ID", "C0TEST")
            monkeypatch.setenv("SLACK_API_BASE_URL", f"{api.url}/api")
            result = probe_hook_health()
        finally:
            with pytest.raises(StopIteration):
                next(gen)
        assert result.alert_channel_status == "dead"
        assert result.healthy is False, (
            "a dead alert channel must make hook health unhealthy — otherwise "
            "the check that would report it is the check that is broken"
        )
        assert any("ALERT CHANNEL DEAD" in w for w in result.warnings)

    def test_probe_hook_health_unaffected_when_channel_unconfigured(
        self, bench: _Bench
    ) -> None:
        result = probe_hook_health()
        assert result.alert_channel_status == "not_configured"
        assert not any("ALERT CHANNEL DEAD" in w for w in result.warnings)


def test_model_is_frozen_and_strict() -> None:
    health = ModelAlertChannelHealth(status="dead", dead_channels=["bot_token"])
    with pytest.raises(Exception):  # noqa: B017, PT011 — pydantic ValidationError
        health.status = "live"  # type: ignore[misc]
