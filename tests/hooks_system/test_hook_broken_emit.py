# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A broken emit path fails loudly, inside its budget, and never hangs (OMN-20109).

The hook edge journals every event before the drainer publishes it. The incident
was that path failing quietly and slowly: an exclusive ``flock`` on the journal's
bound lock that another process held, taken by a detached, disowned Python whose
failure nobody could see, so the process waited forever and the next tool call
started another.

The operator ruling that governs this suite (2026-09-29): a failed emit fails the
tool call loudly with an alarm, there is no silent failure and no alternate path.
So for each broken-emit condition the hook must, inside ``BUDGET_SECONDS_BROKEN_EMIT``:

* exit non-zero, with the cause on stderr (Claude Code shows a non-zero hook's
  stderr, which is what makes it loud);
* leave no process behind, and never be killed by the harness for hanging.

Two conditions are the opposite case and pin the boundary of that rule: an
unreachable bus is not an emit failure (the edge is journal-only, so the hook
must not notice), and a journal at its bound is backpressure, evicted quickly.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    ProcessLedger,
    Rig,
    describe,
    entrypoint,
    hook_payload,
    run_hook,
    wait_for_settle,
)

# The journal bound in hook_emit_journal.DEFAULT_MAX_RECORDS. One record over it
# is the state the edge reaches when the drainer has stopped and the backlog is
# full: every append then takes the eviction branch and its lock.
JOURNAL_BOUND = 50_000

# The three entrypoints that append to the journal on the incident path.
_EMITTING_HOOKS = [
    pytest.param(
        "pre_tool_use_skill_started.sh", "PreToolUse", "Skill", id="skill-started"
    ),
    pytest.param("post_tool_use_bus_mirror.sh", "PostToolUse", "Bash", id="bus-mirror"),
    pytest.param("claude_hook_capture.sh", "PreToolUse", "Bash", id="hook-capture"),
]


def _fill_journal(journal_dir: Path, count: int) -> None:
    """Create ``count`` journal-shaped files quickly (names sort FIFO)."""
    for i in range(count):
        fd = os.open(
            journal_dir / f"{i:020d}_prefill{i:08d}.json",
            os.O_CREAT | os.O_WRONLY,
            0o644,
        )
        os.write(fd, b"{}")
        os.close(fd)


@contextmanager
def _hold_bound_lock(journal_dir: Path) -> Iterator[None]:
    """Hold the journal's eviction lock from this process, as a wedged peer would."""
    fd = os.open(journal_dir / ".bound.lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _breaks(rig: Rig, how: str) -> None:
    if how == "journal-path-is-a-file":
        # mkdir/open on the journal directory fails for every user, root included.
        (rig.journal_dir).rmdir()
        rig.journal_dir.write_text("not a directory")
    elif how == "journal-full":
        _fill_journal(rig.journal_dir, JOURNAL_BOUND + 1)
    else:  # pragma: no cover - a typo in a parametrization must be loud
        raise AssertionError(how)


def _run_and_observe(rig: Rig, hook_name: str, event: str, tool: str, **kwargs):
    hook = entrypoint(hook_name)
    payload = hook_payload(
        event,
        tool_name=tool,
        skill="onex:delegate" if tool == "Skill" else None,
    )
    with ProcessLedger(rig.token) as ledger:
        run = run_hook(
            hook,
            payload,
            rig,
            budget_seconds=budget.BUDGET_SECONDS_BROKEN_EMIT,
            **kwargs,
        )
        leftovers = wait_for_settle(rig.token, budget.SETTLE_SECONDS)
    return run, leftovers, ledger


def _assert_loud_failure(run, leftovers, rig: Rig) -> None:
    assert not run.timed_out, (
        f"the hook hung on a broken emit path and had to be killed after "
        f"{run.wall_seconds:.1f}s: {run.summary()}\nhook logs:\n{rig.log_tail()}"
    )
    assert run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert run.returncode not in (0, None), (
        "the emit path was broken and the hook exited 0: a silent failure. "
        f"{run.summary()}\nhook logs:\n{rig.log_tail()}"
    )
    assert run.stderr.strip(), "the hook failed without saying why on stderr"
    assert any(word in run.stderr.lower() for word in ("journal", "lock", "emit")), (
        f"stderr does not name the failing emit path: {run.stderr[-600:]!r}"
    )
    assert not leftovers, (
        f"the hook left {len(leftovers)} process(es) behind:\n{describe(leftovers.values())}"
    )


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_journal_that_cannot_be_written_fails_loudly(
    rig: Rig, hook_name: str, event: str, tool: str
) -> None:
    _breaks(rig, "journal-path-is-a-file")
    run, leftovers, _ledger = _run_and_observe(rig, hook_name, event, tool)
    _assert_loud_failure(run, leftovers, rig)


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_journal_lock_held_by_another_process_fails_loudly(
    rig: Rig, hook_name: str, event: str, tool: str
) -> None:
    """The incident. The journal is at its bound, so the append takes the eviction
    lock, and a peer holds it. The hook must give up and say so, not wait."""
    _breaks(rig, "journal-full")
    with _hold_bound_lock(rig.journal_dir):
        run, leftovers, _ledger = _run_and_observe(rig, hook_name, event, tool)
    _assert_loud_failure(run, leftovers, rig)


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_full_journal_is_evicted_inside_the_budget(
    rig: Rig, hook_name: str, event: str, tool: str
) -> None:
    """Backpressure is not a failure: a full journal with a free lock drops the
    oldest record and the hook succeeds, quickly, leaving nothing running."""
    _breaks(rig, "journal-full")
    run, leftovers, _ledger = _run_and_observe(rig, hook_name, event, tool)
    assert not run.timed_out, f"hung on a full journal: {run.summary()}"
    assert run.returncode == 0, (
        f"a full journal must not fail the hook: {run.summary()}"
    )
    assert run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert not leftovers, describe(leftovers.values())
    assert len(rig.journal_files()) <= JOURNAL_BOUND, "the journal grew past its bound"


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_unreachable_bus_is_invisible_to_the_hook(
    rig: Rig, hook_name: str, event: str, tool: str
) -> None:
    """The hook edge journals; the drainer publishes. A bus that swallows
    connections (192.0.2.1 is TEST-NET-1, never routed) must not slow the hook,
    fail it, or leave a process waiting on a socket."""
    run, leftovers, _ledger = _run_and_observe(
        rig,
        hook_name,
        event,
        tool,
        extra_env={
            "KAFKA_BOOTSTRAP_SERVERS": "192.0.2.1:9092",
            "KAFKA_BROKERS": "192.0.2.1:9092",
        },
    )
    assert not run.timed_out, f"hung with the bus unreachable: {run.summary()}"
    assert run.returncode == 0, f"an unreachable bus failed the hook: {run.summary()}"
    assert run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert not leftovers, (
        f"a process is still waiting on the unreachable bus:\n{describe(leftovers.values())}"
    )
