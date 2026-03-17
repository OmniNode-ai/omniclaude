#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
slack_gate_poll.py — Poll a Slack thread for approval/rejection replies.

Part of the slack-gate skill (OMN-2627). Called by the gate agent after posting
via chat.postMessage to poll the reply thread for approval or rejection keywords.

Exit codes:
    0  Accepted — reply matched an accept keyword
    1  Rejected — reply matched a reject keyword
    2  Timeout  — no qualifying reply before deadline

Output (stdout):
    ACCEPTED:<reply_text>  on exit code 0
    REJECTED:<reply_text>  on exit code 1
    TIMEOUT                on exit code 2
    ERROR:<message>        on configuration/API error (exit code 3)

Usage:
    python3 slack_gate_poll.py \\
        --channel C08Q3TWNX2Q \\
        --thread-ts 1234567890.123456 \\
        --bot-token xoxb-... \\
        --timeout-minutes 60 \\
        --poll-interval 60 \\
        --accept-keywords '["merge", "approve", "yes", "proceed"]' \\
        --reject-keywords '["no", "reject", "cancel", "hold", "deny"]'
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gate decision emitter (OMN-2922)
# Dynamically resolves emit_client_wrapper from the hooks/lib directory so
# this standalone script can emit without declaring a package dependency.
# Failures are silently swallowed — gate outcome is never blocked by telemetry.
# ---------------------------------------------------------------------------


def _resolve_emit_wrapper() -> object | None:
    """Locate and import emit_client_wrapper relative to this script's location.

    Searches: ../../../hooks/lib/emit_client_wrapper.py (relative to this file).
    Returns the module on success, None if not found or import fails.
    """
    try:
        candidate = (
            Path(__file__).resolve().parent.parent.parent  # skills/
            / ".."  # onex/
            / "hooks"
            / "lib"
            / "emit_client_wrapper.py"
        ).resolve()
        if not candidate.exists():
            return None
        spec = importlib.util.spec_from_file_location("emit_client_wrapper", candidate)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception:
        return None


_emit_mod = _resolve_emit_wrapper()


def _emit_gate_decision(
    *,
    gate_id: str,
    decision: str,
    ticket_id: str,
    gate_type: str,
    wait_seconds: float,
    responder: str | None,
    correlation_id: str,
    session_id: str | None,
) -> None:
    """Emit a gate.decision event via the emit daemon (fire-and-forget).

    Never raises. All failures are logged at DEBUG and silently suppressed.
    """
    if _emit_mod is None:
        return
    try:
        emit_fn = getattr(_emit_mod, "emit_event", None)
        if emit_fn is None:
            return
        payload: dict[str, object] = {
            "event_id": str(uuid.uuid4()),
            "gate_id": gate_id,
            "decision": decision,
            "ticket_id": ticket_id,
            "gate_type": gate_type,
            "wait_seconds": wait_seconds,
            "responder": responder,
            "correlation_id": correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        if session_id is not None:
            payload["session_id"] = session_id
        emit_fn("gate.decision", payload)
    except Exception:
        pass  # Telemetry must never block gate outcome


_DEFAULT_ACCEPT: list[str] = ["merge", "approve", "yes", "proceed"]
_DEFAULT_REJECT: list[str] = ["no", "reject", "cancel", "hold", "deny"]
_SLACK_API_BASE = "https://slack.com/api"


def _slack_get(
    endpoint: str, params: dict[str, str], bot_token: str
) -> dict[str, object]:
    """Make a GET request to the Slack Web API."""
    url = f"{_SLACK_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)  # noqa: S310 — URL always https://slack.com
    req.add_header("Authorization", f"Bearer {bot_token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data: dict[str, object] = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Slack API request failed: {exc}") from exc


def _fetch_replies_since(
    channel: str,
    thread_ts: str,
    since_ts: float,
    bot_token: str,
) -> list[dict[str, object]]:
    """
    Fetch replies in a thread posted after since_ts.

    Returns list of reply message dicts (excluding the original gate message).
    """
    data = _slack_get(
        "conversations.replies",
        {"channel": channel, "ts": thread_ts},
        bot_token,
    )
    if not data.get("ok"):
        error = data.get("error", "unknown")
        raise RuntimeError(f"conversations.replies failed: {error}")

    messages: list[dict[str, object]] = data.get("messages", [])  # type: ignore[assignment]
    # Skip the first message (the gate post itself); include replies after since_ts
    replies = [m for m in messages[1:] if float(str(m.get("ts", "0"))) > since_ts]
    return replies


def _match_keywords(text: str, keywords: list[str]) -> str | None:
    """Return the first matching keyword found in text (case-insensitive), or None."""
    lowered = text.lower()
    for kw in keywords:
        if kw.lower() in lowered:
            return kw
    return None


def poll_for_reply(
    channel: str,
    thread_ts: str,
    bot_token: str,
    timeout_minutes: int,
    poll_interval_seconds: int,
    accept_keywords: list[str],
    reject_keywords: list[str],
    gate_id: str | None = None,
    ticket_id: str = "",
    gate_type: str = "HIGH_RISK",
    correlation_id: str = "",
    session_id: str | None = None,
) -> tuple[int, str]:
    """
    Poll the Slack thread for a reply matching accept or reject keywords.

    Returns:
        (exit_code, output_line) where:
            exit_code 0 → output_line = "ACCEPTED:<reply>"
            exit_code 1 → output_line = "REJECTED:<reply>"
            exit_code 2 → output_line = "TIMEOUT"
    """
    deadline = time.monotonic() + (timeout_minutes * 60)
    start_time = time.monotonic()
    # Treat the gate post timestamp as the since_ts baseline
    since_ts = float(thread_ts)
    poll_count = 0
    resolved_gate_id = gate_id or str(uuid.uuid4())

    while time.monotonic() < deadline:
        poll_count += 1
        try:
            replies = _fetch_replies_since(channel, thread_ts, since_ts, bot_token)
        except RuntimeError as exc:
            # Log error to stderr but continue polling (transient errors)
            print(f"[poll #{poll_count}] WARNING: {exc}", file=sys.stderr)
            time.sleep(min(poll_interval_seconds, 30))
            continue

        for reply in replies:
            text = str(reply.get("text", ""))
            # Skip bot messages (avoid feedback loops)
            if reply.get("bot_id"):
                continue

            matched_accept = _match_keywords(text, accept_keywords)
            if matched_accept:
                _emit_gate_decision(
                    gate_id=resolved_gate_id,
                    decision="ACCEPTED",
                    ticket_id=ticket_id,
                    gate_type=gate_type,
                    wait_seconds=time.monotonic() - start_time,
                    responder=str(reply.get("user", "")),
                    correlation_id=correlation_id,
                    session_id=session_id,
                )
                return 0, f"ACCEPTED:{text.strip()}"

            matched_reject = _match_keywords(text, reject_keywords)
            if matched_reject:
                _emit_gate_decision(
                    gate_id=resolved_gate_id,
                    decision="REJECTED",
                    ticket_id=ticket_id,
                    gate_type=gate_type,
                    wait_seconds=time.monotonic() - start_time,
                    responder=str(reply.get("user", "")),
                    correlation_id=correlation_id,
                    session_id=session_id,
                )
                return 1, f"REJECTED:{text.strip()}"

            # Update since_ts so we don't re-process this reply next poll
            reply_ts = float(str(reply.get("ts", since_ts)))
            if reply_ts > since_ts:
                since_ts = reply_ts

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        sleep_secs = min(poll_interval_seconds, remaining)
        print(
            f"[poll #{poll_count}] No qualifying reply yet. "
            f"Next poll in {sleep_secs:.0f}s "
            f"({remaining / 60:.1f}m remaining).",
            file=sys.stderr,
        )
        time.sleep(sleep_secs)

    _emit_gate_decision(
        gate_id=resolved_gate_id,
        decision="TIMEOUT",
        ticket_id=ticket_id,
        gate_type=gate_type,
        wait_seconds=time.monotonic() - start_time,
        responder=None,
        correlation_id=correlation_id,
        session_id=session_id,
    )
    return 2, "TIMEOUT"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll a Slack thread for approval/rejection replies (OMN-2627).",
    )
    parser.add_argument(
        "--channel", required=True, help="Slack channel ID (e.g. C08Q3TWNX2Q)"
    )
    parser.add_argument(
        "--thread-ts", required=True, help="Thread timestamp from chat.postMessage"
    )
    parser.add_argument("--bot-token", required=True, help="Slack Bot Token (xoxb-...)")
    parser.add_argument(
        "--timeout-minutes", type=int, required=True, help="Gate timeout in minutes"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds between polls (default: 60)",
    )
    parser.add_argument(
        "--accept-keywords",
        default=json.dumps(_DEFAULT_ACCEPT),
        help=f"JSON array of accept keywords (default: {_DEFAULT_ACCEPT})",
    )
    parser.add_argument(
        "--reject-keywords",
        default=json.dumps(_DEFAULT_REJECT),
        help=f"JSON array of reject keywords (default: {_DEFAULT_REJECT})",
    )
    # OMN-2922: gate decision emit args (optional; omit to skip telemetry)
    parser.add_argument(
        "--gate-id",
        default=None,
        help="Unique gate ID for telemetry (generated if omitted)",
    )
    parser.add_argument(
        "--ticket-id",
        default="",
        help="Linear ticket ID for gate telemetry (e.g. OMN-2922)",
    )
    parser.add_argument(
        "--gate-type",
        default="HIGH_RISK",
        choices=["HIGH_RISK", "MEDIUM_RISK"],
        help="Gate risk level for telemetry (default: HIGH_RISK)",
    )
    parser.add_argument(
        "--correlation-id",
        default="",
        help="End-to-end correlation ID for telemetry",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Claude Code session ID for telemetry",
    )
    args = parser.parse_args()

    try:
        accept_keywords: list[str] = json.loads(args.accept_keywords)
        reject_keywords: list[str] = json.loads(args.reject_keywords)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON for keywords: {exc}", flush=True)
        sys.exit(3)

    started_at = datetime.now(UTC).isoformat()
    print(
        f"[slack-gate poll] Started at {started_at}. "
        f"Timeout: {args.timeout_minutes}m, poll interval: {args.poll_interval}s.",
        file=sys.stderr,
    )
    print(
        f"[slack-gate poll] Monitoring thread {args.thread_ts} in channel {args.channel}.",
        file=sys.stderr,
    )

    try:
        exit_code, output = poll_for_reply(
            channel=args.channel,
            thread_ts=args.thread_ts,
            bot_token=args.bot_token,
            timeout_minutes=args.timeout_minutes,
            poll_interval_seconds=args.poll_interval,
            accept_keywords=accept_keywords,
            reject_keywords=reject_keywords,
            gate_id=args.gate_id,
            ticket_id=args.ticket_id,
            gate_type=args.gate_type,
            correlation_id=args.correlation_id,
            session_id=args.session_id,
        )
    except RuntimeError as exc:
        print(f"ERROR:{exc}", flush=True)
        sys.exit(3)

    print(output, flush=True)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
