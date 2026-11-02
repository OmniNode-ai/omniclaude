# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Process entry of the lane GitHub read guard: ``python -m`` this module (OMN-20916).

The PreToolUse entrypoint (``pre_tool_use_bash_guards.sh``) pipes the hook payload
here when its text pre-filter matches: a GitHub MCP tool, ``api.github.com``, or a
``/gh`` path, and passes the session's omniclaude_mode. This module reads the payload, takes the NAMES of the lane marker
variables that are set (never a value, so no token reaches the model or the
output), runs :class:`HandlerLaneGithubReadGuard` and prints the verdict.

Exit codes: 0 allow (nothing printed), 2 refuse (the block JSON on stdout), 1 an
input it cannot judge (the entrypoint refuses that too, fail-closed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import (
    EnumLaneGithubReadVerdict,
    EnumSessionMode,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.handlers.handler_lane_github_read_guard import (
    LANE_ENV_MARKERS,
    HandlerLaneGithubReadGuard,
)
from omniclaude.nodes.node_lane_github_read_guard_effect.models import (
    ModelLaneGithubReadRequest,
)

EXIT_ALLOW = 0
EXIT_ERROR = 1
EXIT_REFUSE = 2


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def build_request(
    payload: dict[str, object],
    environ: dict[str, str],
    fallback_cwd: str,
    mode: EnumSessionMode = EnumSessionMode.FULL,
) -> ModelLaneGithubReadRequest:
    """The request for one hook payload and the caller's environment."""
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = _string(tool_input.get("command"))
    home = environ.get("HOME", "")
    return ModelLaneGithubReadRequest(
        tool_name=_string(payload.get("tool_name")),
        command=command,
        cwd=_string(payload.get("cwd")) or fallback_cwd,
        home=home if home and Path(home).is_absolute() else "",
        agent_id=_string(payload.get("agent_id")),
        entrypoint=environ.get("CLAUDE_CODE_ENTRYPOINT", ""),
        mode=mode,
        lane_markers=tuple(m for m in LANE_ENV_MARKERS if environ.get(m)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lane GitHub read guard (OMN-20916)")
    parser.add_argument("--cwd", default="", help="the caller's working directory")
    parser.add_argument(
        "--mode",
        default=EnumSessionMode.FULL.value,
        choices=[mode.value for mode in EnumSessionMode],
        help="omniclaude_mode of the session",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError as exc:
        sys.stderr.write(f"lane GitHub read guard: unreadable hook payload ({exc})\n")
        return EXIT_ERROR
    if not isinstance(payload, dict):
        sys.stderr.write("lane GitHub read guard: hook payload is not an object\n")
        return EXIT_ERROR
    request = build_request(
        payload, dict(os.environ), args.cwd or os.getcwd(), EnumSessionMode(args.mode)
    )
    decision = HandlerLaneGithubReadGuard().handle(request)
    if decision.verdict is EnumLaneGithubReadVerdict.REFUSE:
        sys.stdout.write(json.dumps(decision.hook_payload()) + "\n")
        return EXIT_REFUSE
    return EXIT_ALLOW


if __name__ == "__main__":
    sys.exit(main())
