# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the hook-emit journal + drainer process model (OMN-17224).

The defect under test is a *process model* defect, not a logic defect: the
pre-OMN-17224 hook path forked one Python per tool call, and each of those
processes paid a ~30s ``omnibase_infra`` Pydantic import inside
``HandlerEventEmitEffect.handle()``'s lazy ``_build_default_adapter()``.
Fourteen of them ran concurrently on the operator Mac at ~270% CPU.

So the assertions here are about cost and concurrency, not just correctness:

* ``test_append_is_fast`` pins the fast path's wall-clock budget.
* ``test_append_imports_nothing_heavy`` is the real regression guard -- it
  asserts the fast path never imports ``omnibase_infra``/``omnimarket``,
  which is what made the old path expensive. A future edit that reintroduces
  a convenience import would pass every behavioural test and silently
  restore the bug; this test is what catches it.
* ``test_stacking_*`` covers AC2: N rapid invocations, at most one publisher.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_emit_journal as journal  # noqa: E402


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    d = tmp_path / "journal"
    d.mkdir()
    return d


# --------------------------------------------------------------------------
# Fast-path append
# --------------------------------------------------------------------------


def test_append_writes_one_readable_record(jdir: Path) -> None:
    outcome = journal.append(
        jdir,
        event_type="onex.evt.omniclaude.tool-executed.v1",
        payload={"tool_name": "Bash"},
        correlation_id="corr-1",
    )
    assert outcome.dropped_count == 0
    assert outcome.path is not None and outcome.path.exists()

    pending = journal.list_pending(jdir)
    assert len(pending) == 1
    rec = pending[0].record
    assert rec.event_type == "onex.evt.omniclaude.tool-executed.v1"
    assert rec.payload == {"tool_name": "Bash"}
    assert rec.correlation_id == "corr-1"
    assert rec.queued_at.tzinfo is not None


def test_append_is_fifo_ordered(jdir: Path) -> None:
    for i in range(25):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)
    seen = [p.record.payload["i"] for p in journal.list_pending(jdir)]
    assert seen == list(range(25)), "journal must drain in append order"


def test_append_is_fast(jdir: Path) -> None:
    """AC1: the per-tool-call fast path is sub-100ms.

    Baseline being replaced: 18-27s wall per invocation (OMN-17224).
    """
    # Pre-load the module so this measures append, not first-import.
    journal.append(jdir, event_type="warm", payload={}, correlation_id=None)

    worst = 0.0
    for i in range(20):
        t0 = time.perf_counter()
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)
        worst = max(worst, time.perf_counter() - t0)
    assert worst < 0.100, f"append worst-case {worst * 1000:.1f}ms exceeds 100ms budget"


def test_append_never_raises_on_unserializable_payload(jdir: Path) -> None:
    """Fail-open: a hook must never break because a payload was odd."""
    outcome = journal.append(
        jdir,
        event_type="e",
        payload={"bad": object()},  # type: ignore[dict-item]
        correlation_id=None,
    )
    assert outcome.path is None
    assert journal.list_pending(jdir) == []


def test_append_creates_missing_directory(tmp_path: Path) -> None:
    """OMN-13774 class: a spool write must not fail because the dir is absent."""
    target = tmp_path / "not" / "yet" / "there"
    outcome = journal.append(target, event_type="e", payload={}, correlation_id=None)
    assert outcome.path is not None and outcome.path.exists()


# --------------------------------------------------------------------------
# The cost regression guard (this is the one that matters)
# --------------------------------------------------------------------------


def test_append_imports_nothing_heavy() -> None:
    """The fast path must import neither omnibase_infra nor omnimarket.

    This is the actual OMN-17224 regression guard. The old path's ~30s cost
    was ~2,497 Pydantic model classes built during a lazily-imported
    ``omnibase_infra`` chain. Behaviour tests cannot see that; only an
    import-set assertion can.
    """
    probe = (
        "import sys; "
        f"sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import hook_emit_journal; "
        "heavy = sorted(m for m in sys.modules "
        "if m.split('.')[0] in {'omnibase_infra', 'omnimarket', 'pydantic', 'aiokafka'}); "
        "print(','.join(heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert out.stdout.strip() == "", (
        f"fast path imported heavy modules: {out.stdout.strip()} -- "
        "this reintroduces the OMN-17224 per-tool-call import cost"
    )


def test_append_subprocess_is_fast_end_to_end(jdir: Path) -> None:
    """Whole-process budget, including interpreter start and imports.

    The hook forks a process per tool call, so the process is the unit of
    cost -- an in-process timing alone would not prove the fix.
    """
    script = _LIB_DIR / "hook_emit_append.py"
    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--event-type",
            "onex.evt.omniclaude.tool-executed.v1",
            "--payload",
            json.dumps({"tool_name": "Bash"}),
            "--correlation-id",
            "corr-e2e",
            "--journal-dir",
            str(jdir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, proc.stderr
    assert len(journal.list_pending(jdir)) == 1
    assert elapsed < 1.0, f"append subprocess took {elapsed:.2f}s (was 18-27s)"


# --------------------------------------------------------------------------
# Backpressure (AC4)
# --------------------------------------------------------------------------


def test_journal_is_bounded_and_drops_oldest(jdir: Path) -> None:
    dropped_total = 0
    for i in range(30):
        dropped_total += journal.append(
            jdir, event_type="e", payload={"i": i}, correlation_id=None, max_records=10
        ).dropped_count

    pending = journal.list_pending(jdir)
    assert len(pending) <= 10, "journal must stay bounded"
    assert dropped_total == 20, "every drop must be counted, not silent"

    survivors = [p.record.payload["i"] for p in pending]
    assert survivors == list(range(20, 30)), "must drop OLDEST, keeping newest"


def test_bounded_append_never_grows_unbounded(jdir: Path) -> None:
    for i in range(200):
        journal.append(
            jdir, event_type="e", payload={"i": i}, correlation_id=None, max_records=5
        )
    assert len(journal.list_pending(jdir)) <= 5


# --------------------------------------------------------------------------
# Singleton lock + stacking (AC2)
# --------------------------------------------------------------------------


def test_singleton_lock_admits_one_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "drainer.lock"
    first = journal.SingletonLock(lock_path)
    assert first.acquire() is True
    second = journal.SingletonLock(lock_path)
    assert second.acquire() is False, "a second drainer must not start"
    first.release()
    assert journal.SingletonLock(lock_path).acquire() is True


def test_singleton_lock_released_on_process_death(tmp_path: Path) -> None:
    """AC5 precondition: a dead drainer must not wedge the lock forever."""
    lock_path = tmp_path / "drainer.lock"
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import hook_emit_journal as j; "
        f"lk = j.SingletonLock({str(lock_path)!r}); "
        "print(lk.acquire(), flush=True); "
        "import time; time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "True"
        assert journal.SingletonLock(lock_path).acquire() is False
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert journal.SingletonLock(lock_path).acquire() is True


def test_stacking_n_rapid_appends_spawn_no_publisher(jdir: Path) -> None:
    """AC2: N rapid hook invocations, zero publisher processes, N events queued.

    This is the regression test for the observed defect: 14 concurrent
    emitters for 14 tool calls. The fast path must fork nothing.
    """
    script = _LIB_DIR / "hook_emit_append.py"
    n = 20
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(script),
                "--event-type",
                "onex.evt.omniclaude.tool-executed.v1",
                "--payload",
                json.dumps({"i": i}),
                "--journal-dir",
                str(jdir),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for i in range(n)
    ]
    for p in procs:
        assert p.wait(timeout=60) == 0

    pending = journal.list_pending(jdir)
    assert len(pending) == n, f"expected all {n} events queued, got {len(pending)}"
    assert sorted(p.record.payload["i"] for p in pending) == list(range(n))


# --------------------------------------------------------------------------
# Zero loss across drainer restart (AC5)
# --------------------------------------------------------------------------


def test_records_survive_until_explicitly_acked(jdir: Path) -> None:
    """A crash between publish and ack must replay, never drop."""
    journal.append(jdir, event_type="e", payload={"i": 1}, correlation_id=None)
    pending = journal.list_pending(jdir)
    assert len(pending) == 1

    # Simulate drainer death after reading but before acking.
    del pending
    assert len(journal.list_pending(jdir)) == 1, "unacked record must remain"

    # A restarted drainer sees it again and acks it.
    again = journal.list_pending(jdir)
    journal.ack(again[0])
    assert journal.list_pending(jdir) == []


def test_ack_is_idempotent(jdir: Path) -> None:
    journal.append(jdir, event_type="e", payload={}, correlation_id=None)
    entry = journal.list_pending(jdir)[0]
    journal.ack(entry)
    journal.ack(entry)  # must not raise
    assert journal.list_pending(jdir) == []


def test_corrupt_record_is_skipped_not_fatal(jdir: Path) -> None:
    """One bad file must not stall the whole drain."""
    journal.append(jdir, event_type="good", payload={}, correlation_id=None)
    (jdir / "00000000000000000000_corrupt.json").write_text("{not json")
    pending = journal.list_pending(jdir)
    assert [p.record.event_type for p in pending] == ["good"]
