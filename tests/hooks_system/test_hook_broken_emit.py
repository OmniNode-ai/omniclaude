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
The suite states that as outcomes, not as a mechanism, so a fix may take any shape
that keeps them. For every broken-emit condition, inside
``BUDGET_SECONDS_BROKEN_EMIT``, the hook must:

* finish, and never be killed by the harness for hanging;
* leave no process behind, so nothing is left waiting on the broken path;
* never fail silently: exit 0 only when the record really landed in the journal;
  otherwise exit non-zero with the cause on stderr (Claude Code shows a non-zero
  hook's stderr, which is what makes it loud).

The conditions: the journal cannot be written (must fail loudly); the journal is
at its bound with its bound lock held by another process, the exact incident
state (the append must not queue behind that lock); the journal writer wedges
(the bounded runner must kill it and fail loudly); and three that pin the
boundary of the rule: a healthy journal must actually receive the record (the
positive control that keeps every other test here from passing because a hook
exited at its first guard), an unreachable bus is not an emit failure (the edge
is journal-only, so the hook must not notice), and a journal at its bound with a
free lock is backpressure, not a failure.
"""

from __future__ import annotations

import fcntl
import importlib.util
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.hooks_system import budget
from tests.hooks_system._harness import (
    HANG_EMIT_ENV,
    REPO_ROOT,
    HookRun,
    ProcInfo,
    Rig,
    describe,
    entrypoint,
    hook_payload,
    kill_tagged,
    make_rig,
    run_hook,
    wait_for_settle,
)

# The journal bound in hook_emit_journal.DEFAULT_MAX_RECORDS. One record over it
# is the state the edge reaches when the drainer has stopped and the backlog is
# full, which is where the incident began.
JOURNAL_BOUND = 50_000

# The emit budget the wedged-writer scenario gives the hook (seconds), so the test
# does not wait out the production default.
WEDGE_EMIT_BUDGET_S = 3

# The three entrypoints that append to the journal on the incident path.
_EMITTING_HOOKS = [
    pytest.param(
        "pre_tool_use_skill_started.sh", "PreToolUse", "Skill", id="skill-started"
    ),
    pytest.param("post_tool_use_bus_mirror.sh", "PostToolUse", "Bash", id="bus-mirror"),
    pytest.param("claude_hook_capture.sh", "PreToolUse", "Bash", id="hook-capture"),
]

_BLACKHOLE = {
    "KAFKA_BOOTSTRAP_SERVERS": "192.0.2.1:9092",
    "KAFKA_BROKERS": "192.0.2.1:9092",
}


@dataclass
class Observation:
    run: HookRun
    leftovers: dict[tuple[int, float], ProcInfo]
    rig: Rig


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


def _apply(rig: Rig, scenario: str) -> None:
    if scenario in ("healthy", "bus-unreachable"):
        return
    if scenario == "journal-path-is-a-file":
        # mkdir and open on the journal directory fail for every user, root included.
        rig.journal_dir.rmdir()
        rig.journal_dir.write_text("not a directory")
    elif scenario in ("journal-full", "journal-full-lock-held"):
        _fill_journal(rig.journal_dir, JOURNAL_BOUND + 1)
    elif scenario == "emitter-wedged":
        return
    else:  # pragma: no cover - a typo in a parametrization must be loud
        raise AssertionError(scenario)


def _observe(
    rig: Rig, hook_name: str, event: str, tool: str, scenario: str
) -> Observation:
    _apply(rig, scenario)
    hook = entrypoint(hook_name)
    payload = hook_payload(
        event, tool_name=tool, skill="onex:delegate" if tool == "Skill" else None
    )
    extra: dict[str, str] | None = None
    if scenario == "bus-unreachable":
        extra = _BLACKHOLE
    elif scenario == "emitter-wedged":
        extra = {
            HANG_EMIT_ENV: "1",
            "ONEX_HOOK_EMIT_BUDGET_S": str(WEDGE_EMIT_BUDGET_S),
        }

    def go() -> Observation:
        run = run_hook(
            hook,
            payload,
            rig,
            budget_seconds=budget.BUDGET_SECONDS_BROKEN_EMIT,
            extra_env=extra,
        )
        return Observation(run, wait_for_settle(rig.token, budget.SETTLE_SECONDS), rig)

    if scenario == "journal-full-lock-held":
        with _hold_bound_lock(rig.journal_dir):
            return go()
    return go()


@pytest.fixture(scope="module")
def observe(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Callable[..., Observation]]:
    """Run one (hook, scenario) once and share the observation between the tests
    that assert on it: building a full journal is the slow part."""
    cache: dict[tuple[str, str], Observation] = {}

    def get(hook_name: str, event: str, tool: str, scenario: str) -> Observation:
        key = (hook_name, scenario)
        if key not in cache:
            rig = make_rig(
                tmp_path_factory.mktemp(
                    f"{scenario}-{hook_name.split('.', maxsplit=1)[0]}"
                )
            )
            cache[key] = _observe(rig, hook_name, event, tool, scenario)
        return cache[key]

    try:
        yield get
    finally:
        for obs in cache.values():
            kill_tagged(obs.rig.token)


_BROKEN_SCENARIOS = [
    "journal-path-is-a-file",
    "journal-full",
    "journal-full-lock-held",
    "emitter-wedged",
]
# These can only end one way: the record cannot land, so the hook must fail.
_MUST_FAIL_SCENARIOS = ["journal-path-is-a-file", "emitter-wedged"]


def _landed(rig: Rig) -> bool:
    """Did a real record (not one of the prefill files) reach the journal?"""
    return any(
        "_prefill" not in path.name and path.name != ".bound.lock"
        for path in rig.journal_files()
    )


@pytest.mark.parametrize("scenario", _BROKEN_SCENARIOS)
@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_broken_emit_never_hangs_or_leaves_a_process(
    observe: Callable[..., Observation],
    hook_name: str,
    event: str,
    tool: str,
    scenario: str,
) -> None:
    obs = observe(hook_name, event, tool, scenario)
    assert not obs.run.timed_out, (
        f"the hook hung and was killed after {obs.run.wall_seconds:.1f}s: {obs.run.summary()}"
    )
    assert obs.run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert not obs.leftovers, (
        f"{scenario}: {len(obs.leftovers)} process(es) the hook started are still alive "
        f"{budget.SETTLE_SECONDS}s later, waiting on the broken emit path:\n"
        f"{describe(obs.leftovers.values())}\nhook logs:\n{obs.rig.log_tail()}"
    )


@pytest.mark.parametrize("scenario", _BROKEN_SCENARIOS)
@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_a_broken_emit_is_never_silent(
    observe: Callable[..., Observation],
    hook_name: str,
    event: str,
    tool: str,
    scenario: str,
) -> None:
    """Exit 0 means the record landed. Anything else exits non-zero and says why."""
    obs = observe(hook_name, event, tool, scenario)
    run = obs.run
    assert not run.timed_out, (
        f"hung, so it could not have failed loudly: {run.summary()}"
    )
    if run.returncode == 0:
        assert scenario not in _MUST_FAIL_SCENARIOS, (
            f"{scenario}: the emit path was broken and the hook exited 0, a silent failure. "
            f"{run.summary()}\nhook logs:\n{obs.rig.log_tail()}"
        )
        assert _landed(obs.rig), (
            f"{scenario}: the hook exited 0 and nothing reached the journal, so the "
            f"event was lost without a word. {run.summary()}\nhook logs:\n{obs.rig.log_tail()}"
        )
        return
    assert run.stderr.strip(), "the hook failed without saying why on stderr"
    assert any(word in run.stderr.lower() for word in ("journal", "lock", "emit")), (
        f"stderr does not name the failing emit path: {run.stderr[-600:]!r}"
    )


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_healthy_journal_receives_the_record(
    observe: Callable[..., Observation], hook_name: str, event: str, tool: str
) -> None:
    """The positive control. A hook that exits at its first guard is green in
    every other test in this file, so this one requires the record to land."""
    obs = observe(hook_name, event, tool, "healthy")
    assert obs.run.returncode == 0, obs.run.summary()
    deadline = time.monotonic() + budget.SETTLE_SECONDS
    while not obs.rig.journal_files() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert obs.rig.journal_files(), (
        f"{hook_name} ran clean and journalled nothing, so the tests that rely on it "
        f"prove nothing.\nhook logs:\n{obs.rig.log_tail()}"
    )
    assert not obs.leftovers, describe(obs.leftovers.values())


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_full_journal_with_a_free_lock_is_backpressure_not_a_failure(
    observe: Callable[..., Observation], hook_name: str, event: str, tool: str
) -> None:
    """A journal at its bound with nothing else wrong: the hook succeeds, quickly,
    leaving nothing running, and its record lands."""
    obs = observe(hook_name, event, tool, "journal-full")
    assert not obs.run.timed_out, f"hung on a full journal: {obs.run.summary()}"
    assert obs.run.returncode == 0, (
        f"a full journal must not fail the hook: {obs.run.summary()}"
    )
    assert obs.run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert not obs.leftovers, describe(obs.leftovers.values())
    assert _landed(obs.rig), "a full journal swallowed the record"
    # The bound is the drainer's job now, so the hook may overshoot it, but only by
    # the record it appended: a hook that scans or grows the journal unboundedly is
    # the incident again.
    assert len(obs.rig.journal_files()) <= JOURNAL_BOUND + 8, (
        "a single hook grew the journal far past its bound"
    )


@pytest.mark.parametrize(("hook_name", "event", "tool"), _EMITTING_HOOKS)
def test_unreachable_bus_is_invisible_to_the_hook(
    observe: Callable[..., Observation], hook_name: str, event: str, tool: str
) -> None:
    """The hook edge journals; the drainer publishes. A bus that swallows
    connections (192.0.2.1 is TEST-NET-1, never routed) must not slow the hook,
    fail it, or leave a process waiting on a socket."""
    obs = observe(hook_name, event, tool, "bus-unreachable")
    assert not obs.run.timed_out, f"hung with the bus unreachable: {obs.run.summary()}"
    assert obs.run.returncode == 0, (
        f"an unreachable bus failed the hook: {obs.run.summary()}"
    )
    assert obs.run.wall_seconds <= budget.BUDGET_SECONDS_BROKEN_EMIT
    assert not obs.leftovers, (
        f"a process is still waiting on the unreachable bus:\n{describe(obs.leftovers.values())}"
    )


def test_the_default_emit_budget_ends_before_the_harness_cancels_the_hook() -> None:
    """A budget the harness outlives is a hang with extra steps: Claude Code
    cancels a hook at 60 s and would report nothing."""
    path = REPO_ROOT / "plugins/onex/hooks/lib/hook_emit_bounded.py"
    spec = importlib.util.spec_from_file_location("hook_emit_bounded_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert 0 < module.DEFAULT_BUDGET_S <= budget.EMIT_BUDGET_CEILING_SECONDS
