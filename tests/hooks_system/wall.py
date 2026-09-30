# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Measure the hook wall time and interpreter starts of one tool call (OMN-20109).

``uv run python -m tests.hooks_system.wall [--runs N]`` replays, per call shape,
the hook side of one tool call the way Claude Code does it (every PreToolUse
hook registered for the tool starts together and is waited on, then every
PostToolUse hook), ``N`` times, and prints per shape the median and worst wall
time, the Python interpreter starts, and the exact count of PATH-resolved
commands the hooks ran.

It runs WITHOUT the process sampler of ``ProcessLedger``: the sampler is a
thread walking the process table every few milliseconds, which is load on the
thing being timed. The counts here are therefore the exact spawn-log counts
(every shimmed command and every interpreter start through
``PLUGIN_PYTHON_BIN``), not the sampled union the budget test uses.

Shapes:

* ``bash``: a plain command that trips no guard pre-filter.
* ``bash-guarded``: one command that trips every Bash guard's pre-filter and is
  allowed by every guard, so each guard pays for its decision core.
* ``skill`` and ``read``: as in the budget test.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    Rig,
    finish_hook,
    hook_payload,
    kill_tagged,
    make_rig,
    registered_hooks,
    start_hook,
    wait_for_settle,
)

# Trips every Bash guard's pre-filter (worktree-add vocabulary, a gh api verb,
# credential vocabulary, the word stash, git with a refused verb, a body flag, a
# backtick) and is allowed by every decision core: nothing in it is a mutation.
GUARDED_COMMAND = (
    "git log --oneline -1 | grep -c 'secret-branch-push'; "
    "echo 'the `git worktree add` note'; git stash list; "
    "gh api repos/o/r/pulls/1 --jq .title; printf '%s\\n' --body"
)

SHAPES: list[tuple[str, str, str | None, str]] = [
    ("bash", "Bash", None, "ls"),
    ("bash-guarded", "Bash", None, GUARDED_COMMAND),
    ("skill", "Skill", "onex:delegate", "true"),
    ("read", "Read", None, "true"),
]


def _one_call(
    rig: Rig, tool: str, skill: str | None, command: str
) -> tuple[float, list]:
    tool_use_id = f"toolu_wall_{time.monotonic_ns()}"
    t0 = time.monotonic()
    runs = []
    for event in ("PreToolUse", "PostToolUse"):
        started = []
        for hook in registered_hooks(event, tool):
            payload = hook_payload(
                event,
                tool_name=tool,
                skill=skill,
                command=command,
                tool_use_id=tool_use_id,
            )
            proc, t = start_hook(hook, payload, rig)
            started.append((hook, proc, t))
        runs += [
            finish_hook(h.name, p, t, budget.BUDGET_SECONDS_PER_HOOK)
            for h, p, t in started
        ]
    wall = time.monotonic() - t0
    return wall, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tests.hooks_system.wall")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--shape", action="append", default=None)
    args = parser.parse_args(argv)
    for name, tool, skill, command in SHAPES:
        if args.shape and name not in args.shape:
            continue
        walls: list[float] = []
        pythons: list[int] = []
        execs: list[int] = []
        blocked: set[str] = set()
        for _ in range(args.runs):
            rig = make_rig(Path(tempfile.mkdtemp(prefix="hookwall-")))
            try:
                wall, runs = _one_call(rig, tool, skill, command)
                wait_for_settle(rig.token, budget.SETTLE_SECONDS)
                spawned = rig.shim_pids()
                walls.append(wall)
                pythons.append(sum(1 for n in spawned.values() if n == "python"))
                execs.append(len(spawned))
                blocked |= {r.hook for r in runs if r.returncode not in (0, None)}
            finally:
                kill_tagged(rig.token)
        print(  # noqa: T201 - this module is a measurement instrument
            f"HOOK-WALL shape={name} runs={args.runs} "
            f"wall_median={statistics.median(walls):.3f}s wall_max={max(walls):.3f}s "
            f"python_starts={statistics.median(pythons):g} "
            f"named_execs={statistics.median(execs):g} "
            f"hooks={len(runs)} nonzero={sorted(blocked) or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
