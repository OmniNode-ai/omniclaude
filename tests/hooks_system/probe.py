# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Print what each registered hook costs for one tool call (OMN-20109).

``uv run python -m tests.hooks_system.probe`` runs, per call shape, every hook
registered for it, one at a time, and prints its exit code, wall time, the
distinct processes it started, and the journal records it wrote. It is the
instrument the budget in ``budget.py`` was set with, and the first thing to run
when a budget test goes red: it says WHICH hook is the cost.

It also answers the question a green run cannot: did the hook do anything at
all. A hook that exits at its first guard costs nothing and is green in every
other test in this directory, so the ``records`` column is the positive control.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    ProcessLedger,
    describe,
    hook_payload,
    kill_tagged,
    make_rig,
    registered_hooks,
    run_hook,
    wait_for_settle,
)

_SHAPES = [
    ("PreToolUse", "Bash"),
    ("PostToolUse", "Bash"),
    ("PreToolUse", "Skill"),
    ("PostToolUse", "Read"),
]


def main(argv: list[str] | None = None) -> int:
    verbose = "-v" in (argv if argv is not None else sys.argv[1:])
    total = 0
    for event, tool in _SHAPES:
        print(f"== {event} {tool}")
        shape_total = 0
        for hook in registered_hooks(event, tool):
            rig = make_rig(Path(tempfile.mkdtemp(prefix="hookprobe-")))
            try:
                payload = hook_payload(
                    event,
                    tool_name=tool,
                    skill="onex:delegate" if tool == "Skill" else None,
                )
                with ProcessLedger(rig) as ledger:
                    run = run_hook(
                        hook,
                        payload,
                        rig,
                        budget_seconds=budget.BUDGET_SECONDS_PER_HOOK,
                    )
                    ledger.add_root(run.pid)
                    left = wait_for_settle(rig.token, budget.SETTLE_SECONDS)
                shape_total += ledger.spawned
                print(
                    f"  {hook.name:<52} rc={run.returncode} wall={run.wall_seconds:5.2f}s "
                    f"procs={ledger.spawned:<3} records={len(rig.journal_files())} "
                    f"left={len(left)}"
                )
                if left:
                    print(describe(left.values()))
                if verbose:
                    print(ledger.processes())
            finally:
                kill_tagged(rig.token)
        print(f"  -- shape total procs>={shape_total}")
        total += shape_total
    print(f"TOTAL over all shapes: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
