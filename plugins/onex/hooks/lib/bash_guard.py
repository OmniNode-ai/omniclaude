"""Bash command guard hook for Claude Code pre-tool-use interception.

Reads the Claude Code hook input JSON from stdin (containing ``tool_name`` and
``tool_input.command``), classifies the command against two ordered tiers, and
responds accordingly:

HARD_BLOCK tier
    The command matches a pattern so catastrophic (filesystem format, disk
    wipe, recursive rm on root/home, obfuscated shell execution) or
    categorically forbidden in agent sessions (``--no-verify`` on git hooks)
    that it must never run.  The hook emits a
    ``{"decision": "block", "reason": "..."}`` JSON response and exits with
    code **2**, causing Claude Code to abort the tool call entirely.

    ``--no-verify`` is classified as a hard-block for agents (not humans)
    because agents have zero legitimate need to bypass pre-commit hooks.  If a
    hook is broken, the correct action is to fix the hook or create a ticket.
    Bypassing hooks masks pre-existing violations that OMN-3201 is tasked with
    eliminating.  Human operators retain an out-of-band emergency path via
    shell alias or direct terminal access.

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
# Validator catch event emission (OMN-5549)
# Fire-and-forget — never blocks the guard decision.
# ---------------------------------------------------------------------------


def _emit_validator_catch(
    *,
    session_id: str,
    validator_type: str,
    validator_name: str,
    catch_description: str,
    severity: str,
) -> None:
    """Emit a validator-catch event via emit_client_wrapper (fire-and-forget)."""
    try:
        from emit_client_wrapper import (
            emit_event,  # type: ignore[import-not-found]  # noqa: PLC0415
        )

        payload = {
            "session_id": session_id,
            "validator_type": validator_type,
            "validator_name": validator_name,
            "catch_description": catch_description[:500],
            "severity": severity,
            "timestamp_iso": datetime.datetime.now(datetime.UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z",
        }
        emit_event("validator.catch", json.dumps(payload))
    except Exception:  # noqa: BLE001
        pass  # Fire-and-forget — guard must not fail on emit errors


# ---------------------------------------------------------------------------
# Policy integration (OMN-4383)
# Fail-safe rule: policy-load failures → HARD mode. Never fail-open on policy.
# ---------------------------------------------------------------------------


def _load_no_verify_policy() -> object:
    """Load the no_verify HookPolicy from config.yaml.

    Returns a HookPolicy in HARD mode on any failure (fail-safe, not fail-open).
    This is a policy boundary — not an infra notification — so fail-open is wrong.
    """
    try:
        import hook_policy  # type: ignore[import-not-found]

        return hook_policy.HookPolicy.from_config(
            hook_policy.load_config(), "no_verify"
        )
    except Exception:  # noqa: BLE001
        # Return a real HookPolicy if possible, else a minimal stand-in
        try:
            import hook_policy as _hp  # type: ignore[import-not-found]

            return _hp.HookPolicy(name="no_verify", mode=_hp.EnforcementMode.HARD)
        except Exception:  # noqa: BLE001
            return _PolicyHardFallback()


def _check_override_flag(policy: object, session_id: str) -> bool:
    """Check for one-time override flag. Returns False on any error (fail-safe)."""
    try:
        return policy.is_override_active(session_id)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return False


class _PolicyHardFallback:
    """Minimal stand-in when hook_policy.py is entirely unimportable.

    Uses plain string attributes — mode_value and channel_value are what
    bash_guard.py actually reads (via getattr defensively). No nested class tricks.
    """

    name = "no_verify"
    mode_value = "hard"
    channel_value = "terminal"

    def is_override_active(self, session_id: str) -> bool:  # noqa: ARG002
        return False

    def terminal_command(self, session_id: str, reason: str = "") -> str:  # noqa: ARG002
        prefix = session_id[:12]
        return f'allow-no-verify "{reason}" {prefix}'


# ---------------------------------------------------------------------------
# Re-exported helpers from the existing permissions module (scripts/ layer).
# Import lazily inside functions so that import errors don't crash the hook
# when the scripts/ directory is not on sys.path.
# ---------------------------------------------------------------------------

__all__ = [
    "HARD_BLOCK_PATTERNS",
    "SOFT_ALERT_PATTERNS",
    "CONTEXT_ADVISORY_PATTERNS",
    "matches_any",
    "main",
]

# =============================================================================
# HARD_BLOCK patterns
# =============================================================================
# Only the catastrophic subset — commands with essentially zero legitimate use
# inside an automated coding session.

HARD_BLOCK_PATTERNS: list[re.Pattern[str]] = [
    # --no-verify on any git command — forbidden in agent sessions (CLAUDE.md policy).
    # Agents must fix pre-commit violations, not bypass them.  Matches:
    #   git commit --no-verify
    #   git push --no-verify
    #   git commit -m "..." --no-verify
    # The flag may appear anywhere in the git command, so we match broadly.
    re.compile(
        r"\bgit\b[^;|&\n]*--no-verify\b",
        re.IGNORECASE | re.MULTILINE,
    ),
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
    # Branch protection: block re-enabling required_pull_request_reviews.
    # Solo developer — reviews block all PRs.  Agents must never re-enable them.
    # Matches gh api / curl calls that set required_pull_request_reviews or
    # required_approving_review_count to any truthy value.
    re.compile(
        r"required_pull_request_reviews"
        r'[^}]*"required_approving_review_count"\s*:\s*[1-9]',
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    ),
    re.compile(
        r"required_approving_review_count\]?\s*[=:]\s*[1-9]",
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
# CONTEXT_ADVISORY patterns
# =============================================================================
# Commands that are not dangerous but warrant an informational advisory to
# the operator.  The hook exits 0 (allow) but includes an ``"advisory"`` key
# in the JSON response so the caller can surface the message.

# Module-level compiled pattern for raw git worktree add detection.
# Used in both CONTEXT_ADVISORY_PATTERNS and the advisory body generation.
_WORKTREE_ADD_RE: re.Pattern[str] = re.compile(
    r"\bgit\b[^;|&\n]*\bworktree\s+add\b",
    re.IGNORECASE | re.MULTILINE,
)

# Pattern to strip single- and double-quoted strings from a command.
# Used to avoid false positives on "worktree" appearing inside commit messages,
# grep patterns, or echo arguments.
_QUOTED_STRING_RE: re.Pattern[str] = re.compile(
    r"""(?:"(?:[^"\\]|\\.)*"|'[^']*')""",
)


def _is_real_worktree_add(command: str) -> bool:
    """Return True only if *command* contains ``git worktree add`` as an actual command.

    Strips quoted strings first so that occurrences inside commit messages
    (``git commit -m "fix worktree add"``) or grep patterns
    (``grep "git worktree add" file``) do not trigger false positives.
    """
    stripped = _QUOTED_STRING_RE.sub("", command)
    return bool(_WORKTREE_ADD_RE.search(stripped))


CONTEXT_ADVISORY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^\s*uv\s+lock\b", re.IGNORECASE),
        "ADVISORY: uv lock detected. Before modifying uv.lock, verify the CI-pinned uv version matches your local version to prevent lock-file drift between environments.",
    ),
    (
        _WORKTREE_ADD_RE,
        (
            "Managed worktree creation via `WorktreeManager.create()` installs pre-commit hooks automatically. "
            "Raw `git worktree add` does not — this is a bypass of the managed path. "
            "If you bypass WorktreeManager, run "
            "`pre-commit install --hook-type pre-commit --hook-type pre-push` "
            "in the new worktree before committing. "
            "Skipping this causes silent CI failures (ruff, SPDX, contract validation all bypass)."
        ),
    ),
]


# =============================================================================
# Helpers
# =============================================================================


CANONICAL_WORKTREE_ROOT = "/Volumes/PRO-G40/Code/omni_worktrees"  # local-path-ok


def _check_worktree_path(command: str) -> str | None:
    """Check if a ``git worktree add`` targets the canonical root.

    Returns a block reason string if the command should be blocked,
    or ``None`` if it is allowed (or not a worktree add command).

    Phase 1 supports the common form: ``git worktree add <path> [-b <branch>]``.
    Flags before the path (``--lock``, ``--detach``) cause the path to be
    unparseable, which triggers a conservative block (fail closed).
    """
    if not _is_real_worktree_add(command):
        return None

    # Tokenize and extract the first non-flag argument after "add"
    tokens = command.split()
    worktree_path = ""
    past_add = False
    for token in tokens:
        if past_add and not token.startswith("-"):
            worktree_path = token
            break
        if token == "add":  # noqa: S105
            past_add = True

    if not worktree_path:
        return (
            "BLOCKED: Could not parse worktree path from command. "
            "Use: git worktree add <path> [-b <branch>]"
        )

    if not worktree_path.startswith(f"{CANONICAL_WORKTREE_ROOT}/"):
        return (
            f"BLOCKED: Worktrees must be created under {CANONICAL_WORKTREE_ROOT}. "
            f"Got: {worktree_path}"
        )

    return None


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
        _no_verify_re = re.compile(
            r"\bgit\b[^;|&\n]*--no-verify\b", re.IGNORECASE | re.MULTILINE
        )
        if _no_verify_re.search(command):
            # Load policy — fail-safe to HARD on any failure
            policy = _load_no_verify_policy()
            # Normalize values immediately; defensive getattr handles both HookPolicy
            # (mode.value) and _PolicyHardFallback (mode_value plain string).
            mode_val: str = getattr(
                getattr(policy, "mode", None), "value", None
            ) or getattr(policy, "mode_value", "hard")
            channel_val: str = getattr(
                getattr(policy, "channel", None), "value", None
            ) or getattr(policy, "channel_value", "terminal")

            # DISABLED: command passes through
            if mode_val == "disabled":
                print(json.dumps({"decision": "allow"}))
                return 0

            # ADVISORY: allow with advisory message
            if mode_val == "advisory":
                print(
                    json.dumps(
                        {
                            "decision": "allow",
                            "advisory": (
                                "--no-verify detected (advisory mode). "
                                "Discouraged in agent sessions per CLAUDE.md. "
                                "Fix pre-commit violations instead of bypassing hooks."
                            ),
                        }
                    )
                )
                return 0

            # SOFT: check one-time override flag before blocking
            if mode_val == "soft":
                if _check_override_flag(policy, session_id):
                    print(
                        json.dumps(
                            {
                                "decision": "allow",
                                "advisory": (
                                    "--no-verify allowed via one-time override. "
                                    "Override consumed — next attempt will be blocked again."
                                ),
                            }
                        )
                    )
                    return 0
                # No override — build block reason with recovery instructions
                terminal_cmd = policy.terminal_command(  # type: ignore[union-attr]
                    session_id=session_id, reason="emergency bypass"
                )
                # channel_val already resolved above via getattr
                if channel_val == "chat":
                    override_msg = (
                        "Procedural: reply 'approve' in this chat. "
                        "You (or the agent) must then manually run `allow_flag.py` to create the flag. "
                        "Agent-side automatic wiring is not yet implemented. "
                        f"For immediate access, use terminal: {terminal_cmd}"
                    )
                elif channel_val == "slack_poll":
                    override_msg = (
                        "Slack polling is not yet implemented (stub only). "
                        f"Use terminal instead:\n  {terminal_cmd}"
                    )
                else:  # terminal (default)
                    override_msg = f"Run in your terminal:\n  {terminal_cmd}"
                block_reason = (
                    f"--no-verify is blocked (CLAUDE.md policy, soft mode). "
                    f"Fix pre-commit violations instead of bypassing hooks. "
                    f"Session: {session_id[:16]}...\n\n"
                    f"To grant a ONE-TIME override: {override_msg}"
                )
            else:
                # HARD (default and fail-safe) — same as current behavior
                block_reason = (
                    "--no-verify is forbidden in agent sessions (CLAUDE.md policy). "
                    "Fix the pre-commit violation in your code. "
                    "If the hook itself is broken, create a ticket (see OMN-3201). "
                    "Human operators retain an emergency bypass via direct terminal access."
                )
        elif re.search(
            r"required_pull_request_reviews|required_approving_review_count",
            command,
            re.IGNORECASE,
        ):
            block_reason = (
                "Re-enabling required_pull_request_reviews is forbidden. "
                "Solo developer — reviews block all PRs. "
                "required_approving_review_count must always be null/0. "
                "See memory: feedback_no_required_reviews.md"
            )
        else:
            block_reason = f"Destructive command blocked by bash_guard: {command[:200]}"

        block_response: dict[str, str] = {
            "decision": "block",
            "reason": block_reason,
        }
        # OMN-5549: Emit validator catch event (fire-and-forget)
        _emit_validator_catch(
            session_id=session_id,
            validator_type="pre_commit",
            validator_name="bash-guard-hard-block",
            catch_description=block_reason[:500],
            severity="error",
        )
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
    # Tier 1b — WORKTREE_PATH_ENFORCEMENT (OMN-7018)
    # Phase 1: supports common `git worktree add <path> [-b <branch>]`.
    # Unsupported flag/order variants fail closed (block).
    # ------------------------------------------------------------------
    worktree_result = _check_worktree_path(command)
    if worktree_result is not None:
        block_response = {"decision": "block", "reason": worktree_result}
        _emit_validator_catch(
            session_id=session_id,
            validator_type="pre_commit",
            validator_name="bash-guard-worktree-path",
            catch_description=worktree_result[:500],
            severity="error",
        )
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
    # Tier 3 — CONTEXT_ADVISORY
    # ------------------------------------------------------------------
    # Strip quoted strings so patterns don't false-positive on worktree
    # mentions inside commit messages, grep patterns, or echo arguments.
    command_unquoted = _QUOTED_STRING_RE.sub("", command)
    for pattern, advisory_message in CONTEXT_ADVISORY_PATTERNS:
        if pattern.search(command_unquoted):
            print(json.dumps({"advisory": advisory_message}))
            return 0

    # ------------------------------------------------------------------
    # Default — ALLOW
    # ------------------------------------------------------------------
    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
