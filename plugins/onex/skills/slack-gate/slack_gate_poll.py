#!/usr/bin/env python3
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
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

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
    # Treat the gate post timestamp as the since_ts baseline
    since_ts = float(thread_ts)
    poll_count = 0

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
                return 0, f"ACCEPTED:{text.strip()}"

            matched_reject = _match_keywords(text, reject_keywords)
            if matched_reject:
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
        )
    except RuntimeError as exc:
        print(f"ERROR:{exc}", flush=True)
        sys.exit(3)

    print(output, flush=True)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
