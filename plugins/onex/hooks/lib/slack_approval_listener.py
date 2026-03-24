#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Mode C: Slack approval listener daemon — STUB ONLY.

Full implementation requires a follow-up ticket. The interface is defined here
so config.yaml can reference channel: slack_poll without import errors in
bash_guard.py, and so the maturity level is explicit in the codebase.

When fully implemented, this daemon will:
  1. Poll a Slack channel for messages matching an approval token
  2. On approval match, call HookPolicy.create_flag() with the session prefix
  3. Continue polling until session expires or SIGTERM received
"""

from __future__ import annotations


class SlackApprovalListener:
    """Stub. Not implemented. Use channel: terminal or channel: chat instead.

    Args:
        policy:     Policy name (e.g. ``no_verify``).
        channel_id: Slack channel ID to poll.
        token:      Approval token embedded in the block Slack message.
        pid_file:   Optional path to write daemon PID.
    """

    def __init__(
        self, policy: str, channel_id: str, token: str = "", pid_file: str = ""
    ) -> None:
        self.policy = policy
        self.channel_id = channel_id
        self.token = token
        self.pid_file = pid_file

    def start(  # stub-ok: intentional placeholder for future Slack listener
        self,
    ) -> None:
        """Not implemented -- raises RuntimeError always."""
        raise RuntimeError(
            "SlackApprovalListener is not yet available. "
            "Use channel: terminal (fully implemented) or channel: chat (procedurally defined) instead."
        )


__all__ = ["SlackApprovalListener"]
