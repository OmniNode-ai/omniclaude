# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Measure the hook wall time and interpreter starts of one tool call (OMN-20109).

``uv run python -m tests.hooks_system.wall [--runs N] [--parallel K]`` replays,
per call shape, the hook side of one tool call the way Claude Code does it
(every PreToolUse hook registered for the tool starts together and is waited
on, then every PostToolUse hook), and prints per shape the median and worst
wall time, the CPU seconds the hooks used, the Python interpreter starts, and
the exact count of PATH-resolved commands the hooks ran.

It runs WITHOUT the process sampler of ``ProcessLedger``: the sampler is a
thread walking the process table every few milliseconds, which is load on the
thing being timed. The counts here are therefore the exact spawn-log counts
(every shimmed command and every interpreter start through
``PLUGIN_PYTHON_BIN``), not the sampled union the budget test uses.

``--parallel K`` runs K calls of the shape at once, the shape of several lanes
calling tools together on one host: on an idle host the wall time of one call
hides the interpreter starts behind the parallelism of its hooks, and under
contention it does not. ``cpu`` is the user plus system CPU seconds of every
process the calls' hooks started and waited for, per call.

Shapes:

* ``bash``: a plain command that trips no guard pre-filter.
* ``bash-guarded``: one command that trips every Bash guard's pre-filter and is
  allowed by every guard, so each guard pays for its decision core.
* ``skill`` and ``read``: as in the budget test.
"""

from __future__ import annotations

import argparse
import resource
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    HookRun,
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
) -> tuple[float, list[HookRun]]:
    tool_use_id = f"toolu_wall_{time.monotonic_ns()}"
    t0 = time.monotonic()
    runs: list[HookRun] = []
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
    return time.monotonic() - t0, runs


def _cpu_children() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def _measure_batch(
    tool: str, skill: str | None, command: str, parallel: int
) -> tuple[list[float], list[int], list[int], set[str], dict[str, float]]:
    rigs = [
        make_rig(Path(tempfile.mkdtemp(prefix="hookwall-"))) for _ in range(parallel)
    ]
    try:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            results = list(pool.map(lambda r: _one_call(r, tool, skill, command), rigs))
        for rig in rigs:
            wait_for_settle(rig.token, budget.SETTLE_SECONDS)
        walls = [wall for wall, _runs in results]
        pythons = [
            sum(1 for n in rig.shim_pids().values() if n == "python") for rig in rigs
        ]
        execs = [len(rig.shim_pids()) for rig in rigs]
        nonzero = {
            r.hook
            for _w, runs in results
            for r in runs
            if r.returncode not in (0, None)
        }
        slowest: dict[str, float] = {}
        for _w, runs in results:
            for r in runs:
                slowest[r.hook] = max(slowest.get(r.hook, 0.0), r.wall_seconds)
        return walls, pythons, execs, nonzero, slowest
    finally:
        for rig in rigs:
            kill_tagged(rig.token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tests.hooks_system.wall")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--shape", action="append", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    for name, tool, skill, command in SHAPES:
        if args.shape and name not in args.shape:
            continue
        walls: list[float] = []
        pythons: list[int] = []
        execs: list[int] = []
        cpus: list[float] = []
        blocked: set[str] = set()
        slowest: dict[str, float] = {}
        for _ in range(args.runs):
            cpu0 = _cpu_children()
            w, p, e, nz, sl = _measure_batch(tool, skill, command, args.parallel)
            cpus.append((_cpu_children() - cpu0) / args.parallel)
            walls += w
            pythons += p
            execs += e
            blocked |= nz
            for hook, seconds in sl.items():
                slowest[hook] = max(slowest.get(hook, 0.0), seconds)
        print(  # noqa: T201 - this module is a measurement instrument
            f"HOOK-WALL shape={name} runs={args.runs} parallel={args.parallel} "
            f"wall_median={statistics.median(walls):.3f}s wall_max={max(walls):.3f}s "
            f"cpu_per_call={statistics.median(cpus):.3f}s "
            f"python_starts={statistics.median(pythons):g} "
            f"named_execs={statistics.median(execs):g} "
            f"nonzero={sorted(blocked) or '-'}"
        )
        if args.verbose:
            for hook, seconds in sorted(slowest.items(), key=lambda kv: -kv[1]):
                print(f"    {hook:<52} worst={seconds:.3f}s")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
