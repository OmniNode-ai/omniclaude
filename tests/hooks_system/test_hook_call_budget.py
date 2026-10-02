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
    with ProcessLedger(rig) as ledger:
        runs = _run_phase(rig, ledger, "PreToolUse", tool, skill, tool_use_id)
        runs += _run_phase(rig, ledger, "PostToolUse", tool, skill, tool_use_id)
        # The detached emit children are part of the call's cost: let them finish
        # (inside the sampling window) before the count is read.
        leftovers = wait_for_settle(rig.token, budget.SETTLE_SECONDS)
    wall = time.monotonic() - t0

    print(  # noqa: T201 - the measurement, read from `pytest -s` when a ceiling moves
        f"HOOK-BUDGET tool={tool} execs={ledger.spawned} wall={wall:.2f}s hooks={len(runs)}"
    )
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
    ceiling = budget.CEILING_EXECS_PER_CALL[tool]
    assert ledger.spawned <= ceiling, (
        f"a {tool} tool call started {ledger.spawned} hook processes; the ceiling is "
        f"{ceiling} (measured: {budget.MEASURED_EXECS_PER_CALL[tool]}, "
        f"target: {budget.TARGET_EXECS_PER_CALL}; the incident snapshot counted "
        f"{budget.INCIDENT_CONCURRENT_HOOK_PROCESSES_PER_CALL} alive at once).\n"
        f"{ledger.processes()}"
    )
    assert wall <= budget.BUDGET_SECONDS_PER_TOOL_CALL, (
        f"a {tool} tool call spent {wall:.1f}s in hooks; the budget is "
        f"{budget.BUDGET_SECONDS_PER_TOOL_CALL}s"
    )


def test_skill_call_count_is_deterministic_across_five_runs(tmp_path: Path) -> None:
    """OMN-20109: the same hooks on the same tree start the same number of
    processes every time. The count used to move between 70 and 83 because a
    sampler caught a shell's short-lived forks, a writer fork and a racing
    mkdir in some runs and not in others; a flaky count is a ceiling with no
    margin that can be trusted, or a margin that hides a leak."""
    from tests.hooks_system._harness import kill_tagged, make_rig

    counts: list[int] = []
    for run in range(5):
        run_rig = make_rig(tmp_path / f"run{run}")
        try:
            with ProcessLedger(run_rig) as ledger:
                _run_phase(run_rig, ledger, "PreToolUse", "Skill", "onex:delegate", "t")
                _run_phase(
                    run_rig, ledger, "PostToolUse", "Skill", "onex:delegate", "t"
                )
                wait_for_settle(run_rig.token, budget.SETTLE_SECONDS)
            counts.append(ledger.spawned)
        finally:
            kill_tagged(run_rig.token)
    assert len(set(counts)) == 1, f"the Skill call count moved between runs: {counts}"
    assert counts[0] == budget.MEASURED_EXECS_PER_CALL["Skill"], counts


def test_budget_record_only_ratchets_down() -> None:
    """The ceiling starts at the measurement and may only tighten toward the
    target. Raising it past the measurement is how a leak gets a permit."""
    assert set(budget.CEILING_EXECS_PER_CALL) == set(budget.MEASURED_EXECS_PER_CALL)
    for tool, ceiling in budget.CEILING_EXECS_PER_CALL.items():
        measured = budget.MEASURED_EXECS_PER_CALL[tool]
        # A tool call already under the target (Read, after OMN-20114) keeps
        # the same headroom rule; the target is a floor for nothing.
        # Headroom over the measurement is at most 15 percent.
        assert measured <= ceiling <= measured * 1.15, (tool, measured, ceiling)
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


@pytest.mark.parametrize("shape", sorted(budget.CEILING_PYTHON_STARTS_PER_CALL))
def test_interpreter_starts_per_call_stay_under_the_ceiling(shape: str) -> None:
    """OMN-20118: interpreter starts are what a tool call's hook wall time is
    made of, so they have a ceiling of their own, and it only moves down."""
    from tests.hooks_system import wall

    ceiling = budget.CEILING_PYTHON_STARTS_PER_CALL[shape]
    assert ceiling <= budget.PYTHON_STARTS_BEFORE_OMN_20118[shape]
    _name, tool, skill, command = next(s for s in wall.SHAPES if s[0] == shape)
    _walls, pythons, _execs, _nonzero, _slowest = wall._measure_batch(
        tool, skill, command, 1
    )
    print(f"HOOK-PYTHONS shape={shape} starts={pythons[0]}")  # noqa: T201
    assert pythons[0] <= ceiling, (
        f"a {shape} tool call started {pythons[0]} Python interpreters; the "
        f"ceiling is {ceiling} (before OMN-20118: "
        f"{budget.PYTHON_STARTS_BEFORE_OMN_20118[shape]})"
    )
