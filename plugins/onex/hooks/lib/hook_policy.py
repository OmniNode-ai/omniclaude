#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reusable approval-gating policy for bash_guard and future hook policies.

Standalone stdlib-only module (except PyYAML for config loading).
No omnibase_core imports — hooks must run independently of the platform.
Mirrors EnumEnforcementMode naming from omnibase_core for conceptual alignment.

Policy modes:
    HARD      — block unconditionally (no override possible, fail-safe default)
    SOFT      — block but check for a one-time flag file override first
    ADVISORY  — allow but include advisory message in response
    DISABLED  — pass through without enforcement

Approval channels (active only when mode=SOFT):
    TERMINAL   — human runs allow-no-verify shell alias (FULLY IMPLEMENTED)
    CHAT       — agent calls allow_flag.py after user approves in Claude chat
                 (PROCEDURALLY DEFINED — agent-side wiring is a future task)
    SLACK_POLL — background Slack listener daemon (STUB ONLY — follow-up ticket)

Flag file path: /tmp/onex-allow-{policy_name}-{session_prefix}.flag
  session_prefix = first 12 chars of session_id

  IMPORTANT: session_prefix is an operator convenience scoping token only.
  It is NOT a security primitive. Flags are local, one-time, and user-mediated.
  Acceptable on a single-user workstation; a 12-char prefix collision is
  theoretically possible but operationally negligible at MVP.

Fail-safe vs fail-open:
  - Infra/notification failures (Slack, Kafka) follow the hook fail-open pattern
  - Policy-load failures ALWAYS fail-safe to HARD — never fail-open on policy state

Config YAML shape (in hooks/config.yaml):
    hook_policies:
      no_verify:
        mode: hard        # hard | soft | advisory | disabled
        channel: terminal # terminal | chat | slack_poll

If PyYAML is absent or config.yaml is unreadable/malformed: returns {} -> HARD mode.
No custom YAML parser — fail closed cleanly rather than silently misparse.
"""

from __future__ import annotations

import enum
import pathlib
from typing import Any

# Patchable in tests
_FLAG_DIR: str = "/tmp"  # noqa: S108
_CONFIG_PATH: pathlib.Path = pathlib.Path(__file__).parent.parent / "config.yaml"


class EnforcementMode(str, enum.Enum):
    HARD = "hard"
    SOFT = "soft"
    ADVISORY = "advisory"
    DISABLED = "disabled"


class ApprovalChannel(str, enum.Enum):
    TERMINAL = "terminal"
    CHAT = "chat"
    SLACK_POLL = "slack_poll"


def load_config() -> dict[str, Any]:
    """Load hooks/config.yaml. Returns {} on any failure (fail-safe to HARD).

    No fallback parser. If PyYAML is unavailable or the file is malformed,
    we return {} and let HookPolicy.from_config() default to HARD mode.
    Partial parses are more dangerous than clean failures for policy state.
    """
    try:
        import yaml
    except ImportError:
        return {}
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


class HookPolicy:
    """Encapsulates enforcement mode, channel, and flag-file helpers for one policy.

    Args:
        name:         Policy identifier used in flag file names and config lookups.
        mode:         Enforcement mode (default: HARD).
        channel:      Approval channel for SOFT mode (default: TERMINAL).
        consume_flag: If True, delete flag file after a successful override read.
    """

    def __init__(
        self,
        name: str,
        mode: EnforcementMode = EnforcementMode.HARD,
        channel: ApprovalChannel = ApprovalChannel.TERMINAL,
        consume_flag: bool = True,
    ) -> None:
        self.name = name
        self.mode = mode
        self.channel = channel
        self.consume_flag = consume_flag

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        policy_name: str,
        consume_flag: bool = True,
    ) -> HookPolicy:
        """Construct from a loaded config dict.

        Fails closed to HARD on any missing, invalid, or malformed key.
        Never returns a policy with an unrecognized mode or channel.
        """
        policies = config.get("hook_policies", {})
        if not isinstance(policies, dict):
            return cls(name=policy_name, consume_flag=consume_flag)

        policy_cfg = policies.get(policy_name, {})
        if not isinstance(policy_cfg, dict):
            return cls(name=policy_name, consume_flag=consume_flag)

        raw_mode = str(policy_cfg.get("mode", "hard")).lower()
        try:
            mode = EnforcementMode(raw_mode)
        except ValueError:
            mode = EnforcementMode.HARD  # fail-safe

        raw_channel = str(policy_cfg.get("channel", "terminal")).lower()
        try:
            channel = ApprovalChannel(raw_channel)
        except ValueError:
            channel = ApprovalChannel.TERMINAL  # fail-safe

        return cls(
            name=policy_name, mode=mode, channel=channel, consume_flag=consume_flag
        )

    def flag_file_path(self, session_id: str) -> pathlib.Path:
        """Return /tmp/onex-allow-{name}-{session_prefix}.flag

        session_prefix is the first 12 chars of session_id.
        This is an operator convenience token, not a security boundary.
        """
        prefix = session_id[:12]
        return pathlib.Path(_FLAG_DIR) / f"onex-allow-{self.name}-{prefix}.flag"

    def is_override_active(self, session_id: str) -> bool:
        """Check for one-time override flag. Consumes (deletes) it if consume_flag=True."""
        flag = self.flag_file_path(session_id)
        if not flag.exists():
            return False
        if self.consume_flag:
            try:
                flag.unlink()
            except OSError:
                pass  # Deletion failure doesn't block the override
        return True

    def create_flag(self, session_id: str, reason: str = "") -> pathlib.Path:
        """Create one-time override flag file with embedded reason."""
        flag = self.flag_file_path(session_id)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(f"approved: {reason}\n", encoding="utf-8")
        return flag

    def terminal_command(self, session_id: str, reason: str = "emergency") -> str:
        """Return the shell command the human must run to grant a one-time override.

        NOTE: This method is currently specialized for the `no_verify` policy —
        it hardcodes the `allow-no-verify` shell alias. When this class is reused
        for other policies, this method should be generalized (e.g., derive alias
        from policy name) or overridden. Treat it as reusable policy core +
        `no_verify`-specific terminal UX for now.

        The session prefix is embedded in the command so the user can copy-paste
        from the Slack or chat block message without knowing the full session ID.
        """
        prefix = session_id[:12]
        escaped = reason.replace('"', '\\"')
        return f'allow-no-verify "{escaped}" {prefix}'
