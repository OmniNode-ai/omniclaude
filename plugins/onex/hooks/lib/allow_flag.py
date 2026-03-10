#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI to create one-time override flag files for hook policies.

Delegates entirely to HookPolicy.create_flag() — no flag-path logic duplicated here.

Called by:
  - Mode A (terminal): shell alias `allow-no-verify "reason" <session_prefix>`
  - Mode B (chat): agent calls this after user approves in Claude chat
    NOTE: Mode B is procedurally defined but not fully wired in this plan.
    The agent must call this script after user confirmation; the approval
    flow itself requires a future agent-side implementation ticket.

Usage:
    python allow_flag.py --policy no_verify --session-prefix abcdef123456 \\
        --reason "Merging hotfix — pre-commit broken upstream" [--flag-dir /tmp]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

_HOOKS_LIB = pathlib.Path(__file__).parent
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from hook_policy import HookPolicy  # noqa: E402

_DEFAULT_FLAG_DIR = "/tmp"  # noqa: S108


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="allow_flag",
        description="Create one-time hook policy override flag via HookPolicy.create_flag().",
    )
    parser.add_argument("--policy", required=True, help="Policy name (e.g. no_verify)")
    parser.add_argument(
        "--session-prefix",
        required=True,
        dest="session_prefix",
        help="First 12 chars of session ID (operator convenience token, not security primitive)",
    )
    parser.add_argument("--reason", required=True, help="Human-readable justification")
    parser.add_argument("--flag-dir", default=_DEFAULT_FLAG_DIR, dest="flag_dir")
    args = parser.parse_args(argv)

    # Patch the module-level _FLAG_DIR so HookPolicy uses the override dir
    import hook_policy as _hp

    original_flag_dir = _hp._FLAG_DIR
    _hp._FLAG_DIR = args.flag_dir
    try:
        policy = HookPolicy(name=args.policy)
        flag_path = policy.create_flag(
            session_id=args.session_prefix, reason=args.reason
        )
        print(f"Override flag created: {flag_path}")
        print(
            f"  Policy: {args.policy} | Session: {args.session_prefix}... | Reason: {args.reason}"
        )
        print("The agent will be unblocked on its next retry.")
        return 0
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        _hp._FLAG_DIR = original_flag_dir


if __name__ == "__main__":
    sys.exit(main())
