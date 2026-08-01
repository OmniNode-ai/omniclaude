# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Alert-channel liveness probe (OMN-15600).

A configured alert channel that no longer delivers is worse than no channel at
all: it reads as healthy on every surface while every alert goes nowhere. That
is the state ``SLACK_WEBHOOK_URL`` was in — a revoked webhook answering HTTP
404 ``no_service`` — for an unknown period, because nothing ever checked.

This probe is folded into the EXISTING hook-health check path (see
``hook_health_probe``), which runs at every session start. It is deliberately
not a new opt-in surface: a checker nobody runs is the failure mode this ticket
exists to close.

Probing without spamming the channel
------------------------------------
* Bot token: ``auth.test`` is a read-only Slack Web API call that posts nothing.
* Incoming webhook: POST an **empty** body. Slack answers HTTP 400
  ``invalid_payload`` for a webhook that still exists and HTTP 404
  ``no_service`` for one whose app was deleted. The distinction is exactly the
  liveness signal, and no message is delivered either way.

On a dead channel the probe writes the same durable failure log the shell
sender uses and raises a local notification, so the operator learns at the
console rather than through the channel that is broken.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Kept in lockstep with plugins/onex/hooks/scripts/alert-channel.sh.
_DEFAULT_FAILURE_LOG = ".omnibase/alert_delivery_failures.log"
_DEFAULT_CACHE = ".omnibase/alert_channel_liveness.json"
_DEFAULT_TTL_SECONDS = 3600
_DEFAULT_TIMEOUT_SECONDS = 3.0


class EnumChannelStatus(StrEnum):
    """Alert-channel liveness. Three states, never two.

    ``NOT_CONFIGURED`` and ``DEAD`` are deliberately distinct: collapsing them
    into "not usable" is what let a revoked webhook read as a healthy one.
    """

    LIVE = "live"
    DEAD = "dead"
    NOT_CONFIGURED = "not_configured"


class ModelAlertChannelHealth(BaseModel):
    """Liveness of the configured alert delivery channels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EnumChannelStatus = EnumChannelStatus.NOT_CONFIGURED
    live_channels: list[str] = Field(default_factory=list)
    dead_channels: list[str] = Field(default_factory=list)
    detail: str = ""
    from_cache: bool = False

    @property
    def healthy(self) -> bool:
        """A channel that was never configured is not a failure; a dead one is."""
        return self.status is not EnumChannelStatus.DEAD


def _failure_log_path() -> Path:
    override = os.environ.get("ONEX_ALERT_DELIVERY_LOG", "").strip()
    if override:
        return Path(override)
    return Path.home() / _DEFAULT_FAILURE_LOG


def _cache_path() -> Path:
    override = os.environ.get("ONEX_ALERT_LIVENESS_CACHE", "").strip()
    if override:
        return Path(override)
    return Path.home() / _DEFAULT_CACHE


def _timeout() -> float:
    raw = os.environ.get("ONEX_ALERT_LIVENESS_TIMEOUT_SECONDS", "").strip()
    try:
        return float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS


def _ttl() -> int:
    raw = os.environ.get("ONEX_ALERT_LIVENESS_TTL_SECONDS", "").strip()
    try:
        return int(raw) if raw else _DEFAULT_TTL_SECONDS
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _post(url: str, data: bytes, headers: dict[str, str]) -> tuple[int, str]:
    """POST and return ``(status, body)``, treating an HTTP error as a result.

    A 4xx is a first-class answer here — it is how a live webhook and a revoked
    one are told apart — so it must not raise.
    """
    # S310: the URL is operator-supplied Slack configuration, not user input.
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        url, data=data, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            request, timeout=_timeout()
        ) as response:
            return int(response.status), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, f"transport_error: {exc}"


def _probe_bot_token(token: str) -> tuple[bool, str]:
    # Slack's public API host is not an OmniNode service, so there is no routing-
    # authority / integration-catalog entry to resolve it from. The env override
    # exists only so tests can point at a local stand-in.
    api_base = os.environ.get("SLACK_API_BASE_URL", "https://slack.com/api").rstrip("/")  # url-authority-ok: third-party public API host, no ONEX contract to resolve from  # fmt: skip
    status, body = _post(
        f"{api_base}/auth.test",
        b"",
        {"Authorization": f"Bearer {token}"},
    )
    if status == 200:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return False, "bot_token=HTTP_200 unparseable_body"
        if parsed.get("ok") is True:
            return True, "bot_token=ok"
        # Slack answers 200 with ok:false for a revoked token — status alone lies.
        return False, f"bot_token=HTTP_200 slack_error={parsed.get('error', 'unknown')}"
    return False, f"bot_token=HTTP_{status}"


def _probe_webhook(url: str) -> tuple[bool, str]:
    status, body = _post(url, b"", {"Content-Type": "application/json"})
    snippet = body.strip()[:64]
    if status == 400 or "invalid_payload" in snippet:
        # The webhook exists and rejected the empty payload: alive, nothing posted.
        return True, "webhook=alive (invalid_payload)"
    if 200 <= status < 300:
        return True, f"webhook=HTTP_{status}"
    return False, f"webhook=HTTP_{status} body={snippet}"


def _local_notify(summary: str) -> bool:
    """Raise a notification on this machine. Mirrors alert-channel.sh."""
    override = os.environ.get("ONEX_ALERT_LOCAL_NOTIFY_CMD", "").strip()
    try:
        if override:
            return (
                subprocess.run(  # noqa: S603
                    [override, summary], capture_output=True, timeout=15, check=False
                ).returncode
                == 0
            )
        if platform.system() == "Darwin" and Path("/usr/bin/osascript").exists():
            escaped = summary.replace("\\", "\\\\").replace('"', '\\"')
            return (
                subprocess.run(  # noqa: S603
                    [
                        "/usr/bin/osascript",
                        "-e",
                        f'display notification "{escaped}" with title '
                        '"OmniClaude alerting BROKEN" sound name "Sosumi"',
                    ],
                    capture_output=True,
                    timeout=15,
                    check=False,
                ).returncode
                == 0
            )
        notify_send = shutil.which("notify-send")
        if notify_send:
            return (
                subprocess.run(  # noqa: S603
                    [notify_send, "OmniClaude alerting BROKEN", summary],
                    capture_output=True,
                    timeout=15,
                    check=False,
                ).returncode
                == 0
            )
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _report_dead(detail: str) -> None:
    """Fail loudly: durable log line plus a notification on this machine."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = _failure_log_path()
    line = f"{stamp} [alert-channel][liveness] CHANNEL DEAD {detail}\n"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        logger.error(
            "[alert-channel] channel dead and failure log unwritable: %s", detail
        )
    delivered = _local_notify(
        f"Slack alert channel is DEAD ({detail}). Alerts are going nowhere. See {log_path}"
    )
    if not delivered:
        logger.error(
            "[alert-channel] channel dead, no local notifier available: %s", detail
        )


def _read_cache() -> ModelAlertChannelHealth | None:
    path = _cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        checked_at = float(raw.pop("checked_at", 0.0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if time.time() - checked_at > _ttl():
        return None
    try:
        return ModelAlertChannelHealth(**raw, from_cache=True)
    except (TypeError, ValueError):
        return None


def _write_cache(result: ModelAlertChannelHealth) -> None:
    path = _cache_path()
    payload = result.model_dump(exclude={"from_cache"})
    payload["checked_at"] = time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.debug("[alert-channel] liveness cache unwritable at %s", path)


def probe_alert_channel(*, force: bool = False) -> ModelAlertChannelHealth:
    """Probe every configured alert channel. NEVER raises.

    Result is cached for ``ONEX_ALERT_LIVENESS_TTL_SECONDS`` (default 1h) so
    that wiring this into session start costs one network round trip per hour,
    not one per session. Pass ``force=True`` to bypass the cache.
    """
    try:
        if not force:
            cached = _read_cache()
            if cached is not None:
                return cached

        # Read raw, strip at use: the secret validator whitelists a bare
        # `os.environ.get(...)` assignment but not one wrapped in `.strip()`.
        token = os.environ.get("SLACK_BOT_TOKEN", "")
        channel_id = os.environ.get("SLACK_CHANNEL_ID", "")
        # An incoming-webhook URL IS the credential — the secret is in its path — so
        # it lives in the canonical operator env file and cannot be published in a
        # contract. Same read as blocked_notifier.py / bash_guard.py.
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")  # url-authority-ok: the URL is itself the secret credential  # fmt: skip

        live: list[str] = []
        dead: list[str] = []
        details: list[str] = []

        if token.strip() and channel_id.strip():
            ok, detail = _probe_bot_token(token.strip())
            details.append(detail)
            (live if ok else dead).append("bot_token")
        if webhook.strip():
            ok, detail = _probe_webhook(webhook.strip())
            details.append(detail)
            (live if ok else dead).append("webhook")

        if not live and not dead:
            result = ModelAlertChannelHealth(status=EnumChannelStatus.NOT_CONFIGURED)
        elif live:
            # At least one channel delivers. A dead secondary is still recorded
            # in `dead_channels` so it can be cleaned up, but alerting works.
            result = ModelAlertChannelHealth(
                status=EnumChannelStatus.LIVE,
                live_channels=live,
                dead_channels=dead,
                detail="; ".join(details),
            )
        else:
            result = ModelAlertChannelHealth(
                status=EnumChannelStatus.DEAD,
                dead_channels=dead,
                detail="; ".join(details),
            )
            _report_dead(result.detail)

        _write_cache(result)
        return result
    except Exception as exc:  # noqa: BLE001 — a health probe must never crash a hook
        return ModelAlertChannelHealth(
            status=EnumChannelStatus.NOT_CONFIGURED,
            detail=f"probe_failed: {exc}",
        )


__all__ = ["EnumChannelStatus", "ModelAlertChannelHealth", "probe_alert_channel"]
