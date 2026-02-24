"""Bash command guard hook for Claude Code pre-tool-use interception.

Reads the Claude Code hook input JSON from stdin (containing ``tool_name`` and
``tool_input.command``), classifies the command against two ordered tiers, and
responds accordingly:

HARD_BLOCK tier
    The command matches a pattern so catastrophic (filesystem format, disk
    wipe, recursive rm on root/home, obfuscated shell execution) that it must
    never run.  The hook emits a ``{"decision": "block", "reason": "..."}``
    JSON response and exits with code **2**, causing Claude Code to abort the
    tool call entirely.

SOFT_ALERT tier
    The command is risky but not categorically forbidden (force push, hard
    reset, kill -9, curl-pipe-sh, etc.).  The hook fires a non-blocking Slack
    webhook notification in a background thread, prints ``{}``, and exits 0 so
    the tool call proceeds.

ALLOW (default)
    No pattern matched.  The hook prints ``{}`` and exits 0.

Pattern design
    HARD_BLOCK patterns are a focused subset of the full ``DESTRUCTIVE_PATTERNS``
    list in ``pre_tool_use_permissions.py`` — only the worst-offenders that have
    no legitimate use in everyday development are included.  SOFT_ALERT covers
    the broader set of risky-but-sometimes-necessary operations.

    Known bypass vectors (variable expansion, command substitution, encoding
    tricks) are intentionally left uncovered — this guard provides
    defense-in-depth, not a security boundary.  See the header comment in
    ``pre_tool_use_permissions.py`` for a full discussion of limitations.

Slack integration
    Set the ``SLACK_WEBHOOK_URL`` environment variable to enable notifications.
    If the variable is absent or empty, notifications are silently skipped and
    the guard still functions correctly.

    HARD_BLOCK notifications are sent synchronously (up to 9 s) so the message
    arrives before the block response.  SOFT_ALERT notifications are
    fire-and-forget (daemon thread); the tool call is not delayed.

Exit codes
    0  — pass (allow or soft-alert)
    2  — block (Claude Code interprets exit 2 as "deny tool call")

Usage (standalone)
    $ echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \\
          | python bash_guard.py

Related modules
    plugins/onex/hooks/scripts/pre_tool_use_permissions.py
        Source of the full ``DESTRUCTIVE_PATTERNS`` list and ``normalize_bash_command``.
    plugins/onex/hooks/lib/blocked_notifier.py
        Pattern for fire-and-forget Slack delivery via ``urllib.request``.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import threading
import urllib.request

# ---------------------------------------------------------------------------
# Re-exported helpers from the existing permissions module (scripts/ layer).
# Import lazily inside functions so that import errors don't crash the hook
# when the scripts/ directory is not on sys.path.
# ---------------------------------------------------------------------------

__all__ = [
    "HARD_BLOCK_PATTERNS",
    "SOFT_ALERT_PATTERNS",
    "matches_any",
    "main",
]

# =============================================================================
# HARD_BLOCK patterns
# =============================================================================
# Only the catastrophic subset — commands with essentially zero legitimate use
# inside an automated coding session.

HARD_BLOCK_PATTERNS: list[re.Pattern[str]] = [
    # rm targeting root, home, bare wildcard, or $HOME — catastrophic data loss
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/(?:local/)?)?bin/)?rm\s+-\S*[rf]\S*\s+"
        r"(?:/(?!\S)|~(?:/|\s|$)|\*|\./\*|\$HOME(?:/|\s|$)|\$\{?HOME\}?(?:/|\s|$))",
        re.IGNORECASE | re.MULTILINE,
    ),
    # mkfs — filesystem formatting (any variant: mkfs.ext4, mkfs.xfs, …)
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/)?s?bin/)?mkfs(?:\.\w+)?\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # dd writing to disk devices (block devices only — /dev/sd*, /dev/nvme*, etc.)
    re.compile(
        r"\bdd\b.*\bof=/dev/(?:sd|nvme|disk|hd|vd)\w+",
        re.IGNORECASE | re.MULTILINE,
    ),
    # shred — secure/irreversible file deletion
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/)?bin/)?shred\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # fdisk / gdisk / parted — partition table manipulation
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/)?s?bin/)?(?:fdisk|gdisk|parted)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # base64 decoded and piped directly to a shell — code-execution obfuscation
    re.compile(
        r"base64\b\s+(?:-d|--decode)[^|]*\|\s*(?:ba)?sh\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # printf with hex escapes piped to shell — obfuscated shell execution
    re.compile(
        r"printf\b\s+['\"]?\\x[0-9a-f]+[^|]*\|\s*(?:ba)?sh\b",
        re.IGNORECASE | re.MULTILINE,
    ),
]

# =============================================================================
# SOFT_ALERT patterns
# =============================================================================
# Risky but sometimes legitimate.  Allowed to proceed; operator is notified.

SOFT_ALERT_PATTERNS: list[re.Pattern[str]] = [
    # git force push (--force or -f)
    re.compile(
        r"git\b\s+push\b[^;|&\n]*(?:--force|-f)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # git reset --hard
    re.compile(
        r"git\b\s+reset\b\s+--hard\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # git clean -fd / -fx / -fdx / etc.
    re.compile(
        r"git\b\s+clean\b\s+-[fdxX]+",
        re.IGNORECASE | re.MULTILINE,
    ),
    # kill -9 / kill -KILL / kill -SIGKILL
    re.compile(
        r"(?:^|[;&|]\s*)(?:/bin/)?kill\b\s+(?:-(?:9|KILL|SIGKILL))\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # pkill / killall — broad process termination
    re.compile(
        r"(?:^|[;&|]\s*)(?:/bin/)?(?:pkill|killall)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # chmod/chown -R on system paths
    re.compile(
        r"(?:chmod|chown)\b\s+-[rR]\s+[^/]*(?:/bin|/etc|/usr|/var|/sys|/proc)",
        re.IGNORECASE | re.MULTILINE,
    ),
    # curl or wget piped to shell — remote code execution vector
    re.compile(
        r"(?:curl|wget)\b\s+[^|]*\|\s*(?:ba)?sh\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # eval with a following argument — dynamic code execution
    re.compile(
        r"(?:^|[;&|]\s*)eval\b\s+",
        re.IGNORECASE | re.MULTILINE,
    ),
    # xargs piped into rm
    re.compile(
        r"xargs\b\s+(?:-\S+\s+)*rm\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Any rm invocation not already caught by HARD_BLOCK (lower-risk tail)
    re.compile(
        r"(?:^|[;&|]\s*)(?:/(?:usr/(?:local/)?)?bin/)?rm\b\s+(?:-\S+\s+)*",
        re.IGNORECASE | re.MULTILINE,
    ),
]


# =============================================================================
# Helpers
# =============================================================================


def matches_any(command: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return ``True`` if *command* matches at least one compiled pattern.

    Args:
        command: Raw bash command string.
        patterns: List of compiled :class:`re.Pattern` objects to test.

    Returns:
        ``True`` if any pattern produces a match, ``False`` otherwise.
    """
    for pattern in patterns:
        if pattern.search(command):
            return True
    return False


def _send_slack_alert(
    webhook_url: str,
    command: str,
    tier: str,
    session_id: str,
) -> None:
    """Send a Slack webhook notification for a flagged command.

    Designed to be called from a :class:`threading.Thread`.  All exceptions
    are silently swallowed so that a failed notification never crashes or
    delays the hook.

    Args:
        webhook_url: Incoming Webhook URL (from ``SLACK_WEBHOOK_URL`` env var).
        command: The bash command that was flagged (truncated to 500 chars in
            the message).
        tier: ``"HARD_BLOCK"`` or ``"SOFT_ALERT"`` — controls emoji and
            action wording.
        session_id: Claude Code session identifier (truncated to 16 chars in
            the message for readability).
    """
    try:
        emoji = ":no_entry:" if tier == "HARD_BLOCK" else ":warning:"
        action = (
            "BLOCKED — command was NOT executed"
            if tier == "HARD_BLOCK"
            else "ALLOWED — but flagged for awareness"
        )
        payload: dict[str, str] = {
            "text": (
                f"{emoji} *{tier}: Bash Command Intercepted*\n\n"
                f"```{command[:500]}```\n\n"
                f"*Action*: {action}\n"
                f"*Session*: `{session_id[:16]}...`\n"
                f"*Time*: {datetime.datetime.now(datetime.UTC).isoformat()}"
            )
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)  # noqa: S310
    except Exception:  # noqa: BLE001
        # Fail-open: notification failure must never affect hook outcome
        pass


# =============================================================================
# Main entry point
# =============================================================================


def main() -> int:
    """Process one Claude Code pre-tool-use hook invocation from stdin.

    Reads a JSON object from stdin with the shape::

        {
            "tool_name": "Bash",
            "tool_input": {"command": "<bash command string>"},
            "session_id": "<uuid>"   // optional
        }

    Writes a JSON object to stdout and exits with an appropriate code:

    * Exit 0 + ``{}``          — allow (no match or soft-alert)
    * Exit 2 + block JSON      — deny (hard-block match)

    Non-Bash tool calls, empty input, and JSON parse errors all exit 0
    (fail-open) so the guard never interrupts unrelated tool use.

    Returns:
        Integer exit code: 0 (allow) or 2 (block).
    """
    raw = sys.stdin.read().strip()
    if not raw:
        print("{}")
        return 0

    try:
        hook_input: dict[str, object] = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return 0

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        print("{}")
        return 0

    tool_input = hook_input.get("tool_input", {})
    if not isinstance(tool_input, dict):
        print("{}")
        return 0

    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command:
        print("{}")
        return 0

    # Support both camelCase and snake_case session ID keys
    session_id = str(
        hook_input.get("session_id", hook_input.get("sessionId", "unknown"))
    )

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    # ------------------------------------------------------------------
    # Tier 1 — HARD_BLOCK
    # ------------------------------------------------------------------
    if matches_any(command, HARD_BLOCK_PATTERNS):
        block_response: dict[str, str] = {
            "decision": "block",
            "reason": (
                "Destructive command blocked by bash_guard: matches hard-block "
                f"pattern. Command: {command[:200]}"
            ),
        }
        if webhook_url:
            notifier = threading.Thread(
                target=_send_slack_alert,
                args=(webhook_url, command, "HARD_BLOCK", session_id),
                daemon=True,
            )
            notifier.start()
            # Wait briefly so the Slack message arrives before the block response
            # is consumed by Claude Code and the session potentially ends.
            notifier.join(timeout=9)
        print(json.dumps(block_response))
        return 2

    # ------------------------------------------------------------------
    # Tier 2 — SOFT_ALERT
    # ------------------------------------------------------------------
    if matches_any(command, SOFT_ALERT_PATTERNS):
        if webhook_url:
            # Fire-and-forget — do NOT delay the tool call
            threading.Thread(
                target=_send_slack_alert,
                args=(webhook_url, command, "SOFT_ALERT", session_id),
                daemon=True,
            ).start()
        print("{}")
        return 0

    # ------------------------------------------------------------------
    # Default — ALLOW
    # ------------------------------------------------------------------
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
