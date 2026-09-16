# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the singleton hook-emit drainer (OMN-17224).

The drainer is the half that is allowed to be slow, so what is tested here
is not speed but the three guarantees that make moving the publish off the
hook path safe:

* **Singleton** -- N concurrent drainer starts yield at most one publisher
  (AC2/AC3). This is the direct inverse of the observed defect, where 14
  publishers ran at once.
* **At-least-once** -- a record is acked only after a confirmed publish, so
  a drainer killed mid-flight replays instead of dropping (AC5).
* **No poison pill** -- one unpublishable record must not wedge the queue
  head forever.

A fake emitter stands in for ``HandlerEventEmitEffect`` so these run without
a broker and without paying the ~30s import the drainer exists to amortize.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_emit_drainer as drainer  # noqa: E402
import hook_emit_journal as journal  # noqa: E402


class FakeEmitter:
    """Stands in for the real handler. Records what it was asked to publish."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.published: list[str] = []
        self._fail_after = fail_after

    def publish(self, record: journal.JournalRecord) -> bool:
        if self._fail_after is not None and len(self.published) >= self._fail_after:
            return False
        self.published.append(record.event_id)
        return True


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    d = tmp_path / "journal"
    d.mkdir()
    return d


def _seed(jdir: Path, n: int) -> None:
    for i in range(n):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)


# --------------------------------------------------------------------------
# Draining
# --------------------------------------------------------------------------


def test_drain_publishes_and_acks_everything(jdir: Path) -> None:
    _seed(jdir, 5)
    emitter = FakeEmitter()
    published, failed = drainer.drain_once(jdir, emitter)  # type: ignore[arg-type]
    assert (published, failed) == (5, 0)
    assert journal.list_pending(jdir) == [], "acked records must be removed"


def test_drain_preserves_fifo_order(jdir: Path) -> None:
    _seed(jdir, 10)
    expected = [e.record.event_id for e in journal.list_pending(jdir)]
    emitter = FakeEmitter()
    drainer.drain_once(jdir, emitter)  # type: ignore[arg-type]
    assert emitter.published == expected


def test_drain_on_empty_journal_is_a_noop(jdir: Path) -> None:
    assert drainer.drain_once(jdir, FakeEmitter()) == (0, 0)  # type: ignore[arg-type]


def test_semantic_journal_record_uses_no_topic_override() -> None:
    """The resolver must receive the semantic key, never a topic override."""

    class Request:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class Handler:
        def handle(self, request: Request) -> SimpleNamespace:
            assert request.kwargs["event_type"] == "tool.executed"
            assert request.kwargs["topic"] is None
            return SimpleNamespace(published=True)

    emitter = drainer._Emitter()
    emitter._handler = Handler()
    emitter._request_cls = Request
    record = journal.JournalRecord(
        event_id="semantic-record",
        event_type="tool.executed",
        payload={"tool_name": "Bash", "session_id": "s-1"},
        correlation_id="s-1",
        queued_at=journal.datetime.now(journal.UTC),
    )
    assert emitter.publish(record) is True


def test_known_legacy_topic_is_migrated_atomically_before_publish(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = journal.append(
        jdir,
        event_type="onex.evt.omniclaude.tool-executed.v1",
        payload={"tool_name": "Bash", "session_id": "s-1"},
        correlation_id="s-1",
    )
    assert outcome.path is not None
    original = journal.list_pending(jdir)[0].record
    monkeypatch.setattr(
        drainer,
        "_legacy_topic_to_semantic_event",
        lambda: {"onex.evt.omniclaude.tool-executed.v1": "tool.executed"},
    )

    assert drainer.migrate_legacy_journal(jdir) == (1, 0)
    migrated = journal.list_pending(jdir)
    assert len(migrated) == 1
    assert migrated[0].record.event_type == "tool.executed"
    assert migrated[0].record.payload == original.payload
    assert migrated[0].record.correlation_id == original.correlation_id
    assert migrated[0].record.event_id == original.event_id
    assert migrated[0].record.queued_at == original.queued_at
    assert drainer.migrate_legacy_journal(jdir) == (0, 0)


def test_unknown_legacy_topic_is_quarantined_byte_for_byte(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = journal.append(
        jdir,
        event_type="onex.evt.omniclaude.retired-event.v1",
        payload={"opaque": "retain-me"},
        correlation_id="s-1",
    )
    assert outcome.path is not None
    original = outcome.path.read_bytes()
    monkeypatch.setattr(drainer, "_legacy_topic_to_semantic_event", dict)

    assert drainer.migrate_legacy_journal(jdir) == (0, 1)
    assert journal.list_pending(jdir) == []
    quarantined = list((jdir / "quarantine").glob("*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original


def test_drain_respects_batch_limit(jdir: Path) -> None:
    _seed(jdir, 20)
    published, _ = drainer.drain_once(jdir, FakeEmitter(), batch_limit=6)  # type: ignore[arg-type]
    assert published == 6
    assert len(journal.list_pending(jdir)) == 14


# --------------------------------------------------------------------------
# AC5: zero loss
# --------------------------------------------------------------------------


def test_failed_publish_leaves_record_queued(jdir: Path) -> None:
    """A dead broker must queue, never drop."""
    _seed(jdir, 5)
    emitter = FakeEmitter(fail_after=0)
    published, failed = drainer.drain_once(jdir, emitter)  # type: ignore[arg-type]
    assert published == 0 and failed == 5
    assert len(journal.list_pending(jdir)) == 5, "nothing may be lost on failure"


def test_partial_failure_acks_only_confirmed_publishes(jdir: Path) -> None:
    _seed(jdir, 10)
    emitter = FakeEmitter(fail_after=4)
    published, _ = drainer.drain_once(jdir, emitter)  # type: ignore[arg-type]
    assert published == 4
    assert len(journal.list_pending(jdir)) == 6, "unconfirmed records must survive"


def test_restart_after_failure_publishes_the_remainder(jdir: Path) -> None:
    """AC5 end to end: fail, restart, lose nothing."""
    _seed(jdir, 10)
    ids = [e.record.event_id for e in journal.list_pending(jdir)]

    first = FakeEmitter(fail_after=4)
    drainer.drain_once(jdir, first)  # type: ignore[arg-type]

    second = FakeEmitter()  # broker back up
    drainer.drain_once(jdir, second)  # type: ignore[arg-type]

    assert first.published + second.published == ids, (
        "every event, exactly once, in order"
    )
    assert journal.list_pending(jdir) == []


def test_poison_record_does_not_block_the_queue(jdir: Path) -> None:
    """An unpublishable record is acked so the head cannot wedge forever."""
    _seed(jdir, 3)

    class PoisonEmitter:
        def __init__(self) -> None:
            self.published: list[str] = []

        def publish(self, record: journal.JournalRecord) -> bool:
            # Mirrors the real emitter: request construction failed, so the
            # record can never be published and is acked rather than retried.
            if record.payload.get("i") == 0:
                return True
            self.published.append(record.event_id)
            return True

    drainer.drain_once(jdir, PoisonEmitter())  # type: ignore[arg-type]
    assert journal.list_pending(jdir) == []


# --------------------------------------------------------------------------
# AC2/AC3: at most one publisher
# --------------------------------------------------------------------------


def test_second_drainer_exits_immediately(tmp_path: Path, jdir: Path) -> None:
    lock_path = tmp_path / "drainer.lock"
    held = journal.SingletonLock(lock_path)
    assert held.acquire() is True
    try:
        rc = drainer.run(
            jdir, lock_path, poll_seconds=0.1, idle_poll_seconds=0.1, once=True
        )
        assert rc == 0, "a second drainer must exit cleanly, not error"
    finally:
        held.release()


def test_concurrent_drainer_starts_yield_one_publisher(
    tmp_path: Path, jdir: Path
) -> None:
    """AC2: the inverse of the observed 14-concurrent-emitter defect."""
    _seed(jdir, 5)
    lock_path = tmp_path / "drainer.lock"
    script = _LIB_DIR / "hook_emit_drainer.py"

    code = (
        "import sys, time; "
        f"sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import hook_emit_journal as j; "
        f"lk = j.SingletonLock({str(lock_path)!r}); "
        "ok = lk.acquire(); "
        "print('HOLDER' if ok else 'DECLINED', flush=True); "
        "time.sleep(8 if ok else 0)"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
        )
        for _ in range(8)
    ]
    try:
        time.sleep(2)
        verdicts = []
        for p in procs:
            assert p.stdout is not None
            verdicts.append(p.stdout.readline().strip())
        assert verdicts.count("HOLDER") == 1, (
            f"expected exactly one publisher, got {verdicts.count('HOLDER')}: {verdicts}"
        )
        assert verdicts.count("DECLINED") == 7
    finally:
        for p in procs:
            p.kill()
            p.wait(timeout=10)
    assert str(script)  # drainer entrypoint exists for the live proof


def test_drainer_lock_frees_after_holder_is_killed(tmp_path: Path, jdir: Path) -> None:
    """launchd restarts a killed drainer; the lock must not outlive it."""
    lock_path = tmp_path / "drainer.lock"
    code = (
        "import sys, time; "
        f"sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import hook_emit_journal as j; "
        f"lk = j.SingletonLock({str(lock_path)!r}); "
        "print(lk.acquire(), flush=True); time.sleep(30)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "True"
    proc.kill()
    proc.wait(timeout=10)

    rc = drainer.run(
        jdir, lock_path, poll_seconds=0.1, idle_poll_seconds=0.1, once=True
    )
    assert rc == 0, "restarted drainer must be able to take the freed lock"


# ---------------------------------------------------------------------------
# Declared lane (OMN-17224 follow-on; contract from OMN-17204)
# ---------------------------------------------------------------------------
# OMN-17224 moved the publish off the shell hook path and into this drainer.
# OMN-17204 declared the hook edge's lane and made every *_bus_mirror.sh apply
# it -- but those scripts no longer publish anything. They now only run
# hook_emit_append.py, which touches no broker at all. The process that DOES
# publish is this drainer, launched by launchd with an environment of exactly
# {OMNI_HOME, ONEX_STATE_DIR, HOME}.
#
# Proven on the operator Mac 2026-08-30, running the drainer under that exact
# environment: `publish raised ... 'KAFKA_BOOTSTRAP_SERVERS'` and the record
# stayed queued. The two tickets composed into a publisher that obeys no lane
# and, under launchd, cannot publish at all.
#
# These tests pin the composition: the drainer resolves its broker from the
# declared contract, and a disagreeing ambient env does not win.


@pytest.fixture
def _lane_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic client store, so these tests are about the LANE.

    The shipped contract's declared lane is SASL (OMN-17284), so
    ``apply_declared_lane`` resolves a credential as well as an address. These
    two tests are about address resolution and precedence, and they must give
    the same verdict on a developer laptop, on the lab host and on a CI runner.

    CORRECTED by OMN-18120, and the correction is the point of the fixture
    rather than an incidental edit. This wrote a synthetic OPERATOR ENV FILE,
    which stopped being the dev lane's declared credential surface when that
    lane moved to ``sasl_credential_source: onex_lane_store``. Left as it was,
    both tests read the developer's real ``~/.onex`` -- green on a machine that
    holds a dev-lane identity, red on a CI runner that does not, which is
    exactly the host-dependent verdict the original fixture was written to
    prevent. So it now writes the synthetic surface the lane actually declares,
    and the tests inject it.

    The credential-absent path has its own dedicated coverage in
    ``tests/hooks/test_omn17284_hook_edge_declared_transport.py`` and
    ``tests/hooks/test_omn18120_hook_edge_credential_source.py``.
    """
    # Pointed at a file that does not exist, so a regression that reinstated a
    # fallback to the env file would fail here rather than pass quietly.
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(tmp_path / "absent.env"))

    onex_home = tmp_path / ".onex"
    onex_home.mkdir()
    (onex_home / "config.yaml").write_text(
        "lanes:\n"
        "  dev:\n"
        "    sasl_username: 'synthetic-lane-principal'\n"
        "    sasl_password_ref: 'dev-lane-sasl'\n",
        encoding="utf-8",
    )
    credentials = onex_home / "credentials.json"
    credentials.write_text(
        json.dumps({"dev-lane-sasl": "synthetic-not-a-real-secret"}), encoding="utf-8"
    )
    credentials.chmod(0o600)
    return onex_home


def test_drainer_applies_declared_lane_when_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    _lane_credential: Path,
) -> None:
    """launchd hands the drainer no KAFKA_BOOTSTRAP_SERVERS. The contract must."""
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("KAFKA_BROKERS", raising=False)
    monkeypatch.delenv("ONEX_HOOK_EDGE_LANE", raising=False)

    lane = drainer.apply_declared_lane(onex_home=_lane_credential)

    contract_path = (
        _REPO_ROOT / "plugins" / "onex" / "hooks" / "contracts" / "hook_edge_lane.yaml"
    )
    import hook_edge_lane  # noqa: PLC0415 - test-local, never on the hook path

    expected = hook_edge_lane.load_contract(contract_path).bootstrap_servers

    assert lane == expected
    assert os.environ["KAFKA_BOOTSTRAP_SERVERS"] == expected
    assert os.environ["KAFKA_BROKERS"] == expected


def test_declared_lane_beats_a_disagreeing_ambient_env(
    monkeypatch: pytest.MonkeyPatch,
    _lane_credential: Path,
) -> None:
    """An env var naming another lane is a finding, never an input (OMN-17204)."""
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "other-lane.invalid:9999")
    monkeypatch.setenv("KAFKA_BROKERS", "other-lane.invalid:9999")

    lane = drainer.apply_declared_lane(onex_home=_lane_credential)

    assert lane is not None
    assert lane != "other-lane.invalid:9999"
    assert os.environ["KAFKA_BOOTSTRAP_SERVERS"] == lane
    assert os.environ["KAFKA_BROKERS"] == lane


def test_unreadable_contract_leaves_env_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing contract degrades to the ambient env, loudly, not to a guess.

    The drainer is a KeepAlive agent: exiting here would spin launchd's restart
    loop and recreate the CPU burn this ticket removed. Leaving the env alone
    makes the next publish raise a named KeyError and back off instead.
    """
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "other-lane.invalid:9999")

    assert drainer.apply_declared_lane(contract_path=tmp_path / "absent.yaml") is None
    assert os.environ["KAFKA_BOOTSTRAP_SERVERS"] == "other-lane.invalid:9999"
