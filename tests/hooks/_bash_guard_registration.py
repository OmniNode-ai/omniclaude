# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Where a Bash PreToolUse guard is registered (OMN-20118).

The seven Bash guards are reached through ONE registered entrypoint,
``pre_tool_use_bash_guards.sh``, which sources each of them in order. A guard
is live on the Bash matcher when hooks.json registers it directly, or registers
the entrypoint and the entrypoint's ``_OBG_GUARDS`` list names it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_HOOKS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks"
ENTRYPOINT = "pre_tool_use_bash_guards.sh"


def entrypoint_guards() -> list[str]:
    """The guard scripts the entrypoint sources, in order."""
    source = (_HOOKS_DIR / "scripts" / ENTRYPOINT).read_text(encoding="utf-8")
    block = re.search(r"_OBG_GUARDS=\(\n(.*?)\n\)", source, re.DOTALL)
    if block is None:
        return []
    return re.findall(r'/([A-Za-z0-9_]+\.sh)"', block.group(1))


def bash_matcher_commands() -> list[str]:
    hooks = json.loads((_HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    groups = hooks["hooks"]["PreToolUse"]
    return [
        h.get("command", "")
        for g in groups
        if g.get("matcher") == "Bash"
        for h in g["hooks"]
    ]


def is_live_on_bash_matcher(script: str) -> bool:
    commands = bash_matcher_commands()
    if any(c.endswith(f"/{script}") for c in commands):
        return True
    return any(c.endswith(f"/{ENTRYPOINT}") for c in commands) and (
        script in entrypoint_guards()
    )
