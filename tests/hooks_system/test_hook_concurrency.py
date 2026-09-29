# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Forty hook invocations at once finish, and leave nothing behind (OMN-20109).

The incident was a pile-up: every tool call forks hooks, every hook forks a
detached Python, and once one of them blocked (an exclusive lock nobody
released) each later call added another that could never finish. This test
starts ``CONCURRENT_INVOCATIONS`` real hook entrypoints at the same instant (the
shape of several lanes calling tools together) and requires, for every one, an
exit inside its budget, and, for the set, that no process the hooks started is
still alive once they have all settled.
"""

from __future__ import annotations

import itertools

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    ProcessLedger,
    Rig,
    describe,
    finish_hook,
    hook_payload,
    registered_hooks,
    start_hook,
    wait_for_settle,
)

# The events and tools of the incident: PreToolUse and PostToolUse on Bash, a
# Skill start (the class that hung), and a PostToolUse on an unmatched tool.
_CALL_SHAPES = [
    ("PreToolUse", "Bash"),
    ("PreToolUse", "Skill"),
    ("PostToolUse", "Bash"),
    ("PostToolUse", "Read"),
]


def _invocations(count: int):
    pool = []
    for event, tool in _CALL_SHAPES:
        for hook in registered_hooks(event, tool):
            pool.append((event, tool, hook))
    assert pool, "hooks.json registers no hook for the call shapes under test"
    return list(itertools.islice(itertools.cycle(pool), count))


def test_parallel_hooks_finish_in_budget_and_leave_no_process(rig: Rig) -> None:
    invocations = _invocations(budget.CONCURRENT_INVOCATIONS)
    assert len(invocations) == budget.CONCURRENT_INVOCATIONS

    with ProcessLedger(rig.token) as ledger:
        started = []
        for n, (event, tool, hook) in enumerate(invocations):
            payload = hook_payload(
                event,
                tool_name=tool,
                skill="onex:delegate" if tool == "Skill" else None,
                tool_use_id=f"toolu_conc_{n:03d}",
            )
            proc, t0 = start_hook(hook, payload, rig)
            ledger.add_root(proc.pid)
            started.append((hook, proc, t0))
        runs = [
            finish_hook(
                hook.name, proc, t0, budget.BUDGET_SECONDS_PER_HOOK_UNDER_CONCURRENCY
            )
            for hook, proc, t0 in started
        ]
        leftovers = wait_for_settle(rig.token, budget.SETTLE_SECONDS)

    timed_out = [r for r in runs if r.timed_out]
    assert not timed_out, (
        f"{len(timed_out)} hook(s) hung past their budget:\n"
        + "\n".join(r.summary() for r in timed_out)
    )

    failed = [r for r in runs if r.returncode != 0]
    assert not failed, (
        "a harmless payload made hook(s) exit non-zero:\n"
        + "\n".join(r.summary() for r in failed)
        + f"\nhook logs:\n{rig.log_tail()}"
    )

    assert not leftovers, (
        f"{len(leftovers)} process(es) the hooks started are still alive "
        f"{budget.SETTLE_SECONDS}s after the last hook exited:\n{describe(leftovers.values())}"
    )

    ceiling = budget.CONCURRENT_INVOCATIONS * budget.CEILING_PROCESSES_PER_TOOL_CALL
    assert ledger.peak_tagged <= ceiling, (
        f"{ledger.peak_tagged} hook processes alive at once for "
        f"{budget.CONCURRENT_INVOCATIONS} invocations; ceiling {ceiling}"
    )


def test_a_second_wave_after_the_first_finds_the_host_clean(rig: Rig) -> None:
    """Two waves back to back. A hook that leaves one process per call behind
    makes the second wave start with the first wave's leftovers; the count of
    tagged processes must return to zero between them."""
    for wave in range(2):
        with ProcessLedger(rig.token) as ledger:
            started = []
            for n, (event, tool, hook) in enumerate(_invocations(10)):
                payload = hook_payload(
                    event, tool_name=tool, tool_use_id=f"toolu_w{wave}_{n}"
                )
                proc, t0 = start_hook(hook, payload, rig)
                ledger.add_root(proc.pid)
                started.append((hook, proc, t0))
            runs = [
                finish_hook(
                    hook.name,
                    proc,
                    t0,
                    budget.BUDGET_SECONDS_PER_HOOK_UNDER_CONCURRENCY,
                )
                for hook, proc, t0 in started
            ]
            leftovers = wait_for_settle(rig.token, budget.SETTLE_SECONDS)
        assert not [r for r in runs if r.timed_out], f"wave {wave}: a hook hung"
        assert not leftovers, (
            f"wave {wave} left processes:\n{describe(leftovers.values())}"
        )
