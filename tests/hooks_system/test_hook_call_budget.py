# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""One tool call has a process and wall-time budget (OMN-20109).

The 2026-09-29 incident: about 18 hook processes per tool call, 60 to 175 s of
hook time per call under load, ten thousand hung processes in the end. This test
replays the hook side of ONE tool call the way Claude Code does (every PreToolUse
hook registered for the tool starts together and is waited on, then every
PostToolUse hook), counts the distinct processes that call started and the wall
time it took, and fails above the budget recorded in ``budget.py``.

The hooks come from ``hooks.json``, so registering one more hook raises the count
and can fail this test: that is the point. A hook is not free.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    ProcessLedger,
    RegisteredHook,
    Rig,
    describe,
    finish_hook,
    hook_payload,
    registered_hooks,
    start_hook,
    wait_for_settle,
)

_TOOL_CALLS = [
    pytest.param("Bash", None, id="bash-call"),
    pytest.param("Skill", "onex:delegate", id="skill-call"),
    pytest.param("Read", None, id="read-call"),
]


def _run_phase(
    rig: Rig,
    ledger: ProcessLedger,
    event: str,
    tool: str,
    skill: str | None,
    tool_use_id: str,
) -> list:
    hooks: list[RegisteredHook] = registered_hooks(event, tool)
    started = []
    for hook in hooks:
        payload = hook_payload(
            event, tool_name=tool, skill=skill, tool_use_id=tool_use_id
        )
        proc, t0 = start_hook(hook, payload, rig)
        ledger.add_root(proc.pid)
        started.append((hook, proc, t0))
    return [
        finish_hook(hook.name, proc, t0, budget.BUDGET_SECONDS_PER_HOOK)
        for hook, proc, t0 in started
    ]


@pytest.mark.parametrize(("tool", "skill"), _TOOL_CALLS)
def test_one_tool_call_stays_inside_the_process_and_time_budget(
    rig: Rig, tool: str, skill: str | None, record_property: pytest.RecordProperty
) -> None:
    tool_use_id = f"toolu_budget_{tool.lower()}"
    t0 = time.monotonic()
    with ProcessLedger(rig.token) as ledger:
        runs = _run_phase(rig, ledger, "PreToolUse", tool, skill, tool_use_id)
        runs += _run_phase(rig, ledger, "PostToolUse", tool, skill, tool_use_id)
        # The detached emit children are part of the call's cost: let them finish
        # (inside the sampling window) before the count is read.
        leftovers = wait_for_settle(rig.token, budget.SETTLE_SECONDS)
    wall = time.monotonic() - t0

    record_property("processes_spawned", ledger.spawned)
    record_property("wall_seconds", round(wall, 3))
    record_property("hooks_run", len(runs))

    timed_out = [r for r in runs if r.timed_out]
    assert not timed_out, "hooks overran their budget:\n" + "\n".join(
        r.summary() for r in timed_out
    )
    assert not leftovers, (
        f"{len(leftovers)} process(es) still running {budget.SETTLE_SECONDS}s after the "
        f"call:\n{describe(leftovers.values())}"
    )
    assert ledger.spawned <= budget.CEILING_PROCESSES_PER_TOOL_CALL, (
        f"a {tool} tool call started {ledger.spawned} hook processes; the ceiling is "
        f"{budget.CEILING_PROCESSES_PER_TOOL_CALL} (measured at the incident: "
        f"{budget.MEASURED_PROCESSES_PER_TOOL_CALL}, target: "
        f"{budget.TARGET_PROCESSES_PER_TOOL_CALL}).\n{describe(ledger.seen.values())}"
    )
    assert wall <= budget.BUDGET_SECONDS_PER_TOOL_CALL, (
        f"a {tool} tool call spent {wall:.1f}s in hooks; the budget is "
        f"{budget.BUDGET_SECONDS_PER_TOOL_CALL}s"
    )


def test_budget_record_only_ratchets_down() -> None:
    """The ceiling starts at the measurement and may only tighten toward the
    target. Raising it past the measurement is how a leak gets a permit."""
    assert (
        budget.TARGET_PROCESSES_PER_TOOL_CALL
        < budget.CEILING_PROCESSES_PER_TOOL_CALL
        <= budget.MEASURED_PROCESSES_PER_TOOL_CALL
    )
    assert budget.BUDGET_SECONDS_PER_TOOL_CALL < 60, "the harness cancels a hook at 60s"
    assert budget.BUDGET_SECONDS_PER_HOOK_UNDER_CONCURRENCY < 60


def test_every_registered_hook_exists_and_is_executable() -> None:
    """Claude Code execs the registered command directly. A missing file or a
    lost exec bit is a hook that never runs, and nothing reports it."""
    problems: list[str] = []
    for event in ("PreToolUse", "PostToolUse"):
        for hook in registered_hooks(event):
            script = Path(hook.argv[0])
            if not script.is_file():
                problems.append(f"{event}: {script} does not exist")
            elif not script.stat().st_mode & 0o111:
                problems.append(f"{event}: {script} is not executable")
    assert not problems, "\n".join(problems)
