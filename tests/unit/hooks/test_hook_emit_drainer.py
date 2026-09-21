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


def test_a_machine_with_no_stored_identity_writes_nothing_and_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The live 2026-09-15 failure, pinned (OMN-18120).

    The dev lane declares SASL and resolves its credential from the ~/.onex
    client store. On a machine holding no identity for that lane the resolver
    refuses, and the question this test answers is what the drainer does next:
    it must write NOTHING. launchd hands this process an environment of
    ``{OMNI_HOME, ONEX_STATE_DIR, HOME}`` with no broker address in it, so a
    half-applied lane -- an address written, a credential missing -- would
    produce an anonymous connect against an auth-required listener.

    Returning ``None`` with the environment untouched is what makes the next
    publish raise a named ``KeyError: 'KAFKA_BOOTSTRAP_SERVERS'`` and back off,
    which is the loud, diagnosable failure the live drainer actually showed for
    22 hours, rather than a client quietly dialling as nobody.
    """
    for name in ("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BROKERS", "ONEX_HOOK_EDGE_LANE"):
        monkeypatch.delenv(name, raising=False)
    # The legacy surface is present and complete. A regression that reinstated a
    # fallback to it would resolve here, so this is the negative control for
    # "the resolver reads the DECLARED surface and only that one".
    env_file = tmp_path / "operator.env"
    env_file.write_text(
        "DEV_KAFKA_SASL_USERNAME=synthetic-lane-principal\n"
        "DEV_KAFKA_SASL_PASSWORD=synthetic-not-a-real-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(env_file))

    assert drainer.apply_declared_lane(onex_home=tmp_path / "no-such-onex") is None

    for name in ("KAFKA_BOOTSTRAP_SERVERS", "KAFKA_BROKERS", "ONEX_HOOK_EDGE_LANE"):
        assert name not in os.environ, (
            f"{name} was written although the declared lane could not be "
            "resolved; a half-applied lane is how an anonymous client reaches "
            "an auth-required broker"
        )


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


# ---------------------------------------------------------------------------
# OMN-19074: the journal's own dead-letter.
#
# `test_poison_record_does_not_block_the_queue` above covers the case the
# emitter can recognise -- a MALFORMED record, which `_Emitter.publish` acks
# deliberately because it can never be published. These cover the case it
# cannot: a well-formed record the BROKER refuses. That one returned False
# forever, `drain_once` stopped on it every cycle, and the edge delivered
# nothing until a person moved the file. It happened four times, most recently
# on 2026-09-21 when four records held roughly four thousand for 105 minutes.
# ---------------------------------------------------------------------------


class RefusingEmitter:
    """Refuses one event type the way a broker ACL refuses a topic.

    Well-formed, resolvable, and permanently unpublishable. The emitter cannot
    tell that from a transient failure, which is the whole difficulty: on the
    live path the transport masked the refusal as a TimeoutError for three days
    (OMN-19073), so nothing keyed on an exception type would have helped.
    """

    def __init__(self, refused_event_type: str) -> None:
        self.published: list[str] = []
        self.attempts: list[str] = []
        self._refused = refused_event_type

    def publish(self, record: journal.JournalRecord) -> bool:
        self.attempts.append(record.event_id)
        if record.event_type == self._refused:
            return False
        self.published.append(record.event_id)
        return True


class DeadBrokerEmitter:
    """Every publish fails. Stands in for an unreachable broker."""

    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, record: journal.JournalRecord) -> bool:
        return False


def _drain_n_cycles(
    jdir: Path,
    emitter: object,
    cycles: int,
    counts: dict[str, int] | None = None,
) -> dict[str, int]:
    """Run N cycles sharing one failure map, as `run()` does.

    The map is threaded through and returned so a test can continue a run
    rather than restart it. That is not a convenience: a fresh map per call
    resets every count, which is the same bug as owning the map inside
    `drain_once`, and a test carrying it would silently never reach the
    threshold.

    Cycle COUNT, never wall clock: the threshold is a count, and a test that
    slept for the real 30s backoff would take two and a half minutes to assert
    one thing (OMN-19074 AC9).
    """
    counts = {} if counts is None else counts
    for _ in range(cycles):
        _drain_once_compat(jdir, emitter, counts)
    return counts


def _drain_once_compat(
    jdir: Path, emitter: object, counts: dict[str, int]
) -> tuple[int, int]:
    """Call `drain_once`, tolerating a build that has no `failure_counts` yet.

    This exists so the RED run of these tests fails on BEHAVIOUR rather than
    on a TypeError. Against the pre-OMN-19074 drainer the parameter does not
    exist, and a test that simply exploded on the signature would prove only
    that a keyword argument is new -- not that one refused record holds the
    whole queue, which is the defect. With this shim the pre-change build runs
    its real drain loop for every cycle the test asks for, and the assertion
    that the authorized records eventually publish is what fails.
    """
    try:
        return drainer.drain_once(jdir, emitter, failure_counts=counts)
    except TypeError:
        return drainer.drain_once(jdir, emitter)


def test_a_refused_record_does_not_hold_the_queue_forever(jdir: Path) -> None:
    """OMN-19074 AC1, the defect itself: one refused class holds everything.

    Deliberately references no threshold constant, so that against the
    pre-OMN-19074 drainer it fails on BEHAVIOUR rather than on a missing
    attribute. However many cycles run, the authorized records never publish.
    That is exactly what 105 minutes of dead hook capture looked like from
    the outside on 2026-09-21.
    """
    journal.append(
        jdir, event_type="denied.class", payload={"i": 0}, correlation_id=None
    )
    for i in range(1, 4):
        journal.append(
            jdir, event_type="ok.class", payload={"i": i}, correlation_id=None
        )

    emitter = RefusingEmitter("denied.class")
    _drain_n_cycles(jdir, emitter, 20)

    assert len(emitter.published) == 3, (
        f"the three authorized records behind the refused one never "
        f"published across 20 cycles: {emitter.published}"
    )
    assert journal.list_pending(jdir) == [], "the journal did not drain"


def test_ordering_holds_until_the_threshold_is_reached(jdir: Path) -> None:
    """OMN-19074 AC4 and AC9: nothing overtakes a record still under the bound.

    The dead-letter is a last resort, not a first one. Below the threshold the
    refused record is still treated as owed, so the queue behind it waits.
    """
    journal.append(
        jdir, event_type="denied.class", payload={"i": 0}, correlation_id=None
    )
    for i in range(1, 4):
        journal.append(
            jdir, event_type="ok.class", payload={"i": i}, correlation_id=None
        )

    emitter = RefusingEmitter("denied.class")
    _drain_n_cycles(jdir, emitter, drainer.DEFAULT_QUARANTINE_AFTER_FAILURES - 1)

    assert emitter.published == [], (
        "an authorized record published while a refused record was still "
        "ahead of it and under the threshold -- ordering was abandoned early"
    )
    assert len(journal.list_pending(jdir)) == 4


def test_the_refused_record_is_moved_to_quarantine_with_a_reason(jdir: Path) -> None:
    """OMN-19074 AC7: moved, never deleted, and the reason says why."""
    journal.append(
        jdir, event_type="denied.class", payload={"k": "v"}, correlation_id=None
    )
    journal.append(jdir, event_type="ok.class", payload={}, correlation_id=None)
    original = json.loads(journal.list_pending(jdir)[0].path.read_text())

    _drain_n_cycles(
        jdir,
        RefusingEmitter("denied.class"),
        drainer.DEFAULT_QUARANTINE_AFTER_FAILURES + 1,
    )

    qdir = jdir / "quarantine"
    records = [p for p in qdir.glob("*.json") if not p.name.endswith(".reason.json")]
    assert len(records) == 1, (
        f"expected exactly one dead-lettered record, got {records}"
    )

    assert json.loads(records[0].read_text()) == original, (
        "the dead-lettered record must be byte-for-byte what was queued; a "
        "rewritten record cannot be replayed as the thing that was refused"
    )

    reason = json.loads((qdir / f"{records[0].stem}.reason.json").read_text())
    assert reason["reason_code"] == "publish_failed_repeatedly"
    assert reason["event_type"] == "denied.class"
    assert reason["consecutive_failures"] >= drainer.DEFAULT_QUARANTINE_AFTER_FAILURES


def test_an_unreachable_broker_dead_letters_nothing(jdir: Path) -> None:
    """OMN-19074 AC8, the negative control, and the one that matters most.

    A failure count alone cannot tell a refused record from a dead broker:
    both produce an unbounded run of failures at the head. Under a count-only
    rule a long outage would dead-letter the entire backlog one record at a
    time -- strictly worse than the stall this change exists to end, because a
    stall is recoverable and mass dead-lettering buries the evidence.

    The stand-down probe is what prevents it, so this test is the reason the
    probe exists rather than a formality.
    """
    for i in range(5):
        journal.append(
            jdir, event_type="ok.class", payload={"i": i}, correlation_id=None
        )
    before = {p.path.name for p in journal.list_pending(jdir)}

    _drain_n_cycles(
        jdir, DeadBrokerEmitter(), drainer.DEFAULT_QUARANTINE_AFTER_FAILURES * 3
    )

    assert {p.path.name for p in journal.list_pending(jdir)} == before, (
        "records were dead-lettered during a broker outage; the stand-down "
        "probe did not fire, and a recoverable stall became data in a "
        "dead-letter directory"
    )
    assert not (jdir / "quarantine").exists() or not list(
        (jdir / "quarantine").glob("*.json")
    )


def test_a_transient_failure_still_halts_the_drain(jdir: Path) -> None:
    """OMN-19074 AC4: ordinary ordering is untouched.

    One failure is not a dead-letter candidate. The record is still owed, so
    nothing behind it may overtake it.
    """
    for i in range(4):
        journal.append(
            jdir, event_type="ok.class", payload={"i": i}, correlation_id=None
        )

    emitter = FakeEmitter(fail_after=1)
    published, failed = _drain_once_compat(jdir, emitter, {})

    assert published == 1
    assert failed == 3
    assert len(journal.list_pending(jdir)) == 3, (
        "a single transient failure skipped a record instead of halting the "
        "drain, which reorders the stream"
    )


def test_a_dead_lettered_record_replays_when_moved_back(jdir: Path) -> None:
    """OMN-19074 AC10: the dead-letter is replayable by the move that filled it.

    This is not a hypothetical. On 2026-09-21 the four quarantined
    `team.task.assigned` records were replayed exactly this way once their
    grant landed, taking the topic's high watermark from 0 to 4 with no
    duplication.
    """
    journal.append(
        jdir, event_type="denied.class", payload={"i": 0}, correlation_id=None
    )
    journal.append(jdir, event_type="ok.class", payload={"i": 1}, correlation_id=None)
    _drain_n_cycles(
        jdir,
        RefusingEmitter("denied.class"),
        drainer.DEFAULT_QUARANTINE_AFTER_FAILURES + 1,
    )

    qdir = jdir / "quarantine"
    dead = next(p for p in qdir.glob("*.json") if not p.name.endswith(".reason.json"))

    # The grant lands: move it back, exactly as an operator would.
    dead.replace(jdir / dead.name)

    emitter = FakeEmitter()
    _drain_once_compat(jdir, emitter, {})

    assert len(emitter.published) == 1, "the replayed record did not publish"
    assert journal.list_pending(jdir) == []


def test_the_dead_letter_reason_warns_that_replay_reorders(jdir: Path) -> None:
    """OMN-19118 AC1: the durable artifact says what replay costs.

    The dead-letter instructs a replay. By the time it is written the
    stand-down probe has already published the record that sat BEHIND the head,
    so those two have gone out in the opposite order from the journal, and
    moving the head back later re-introduces it into a stream that has moved
    past it.

    Asserted on the SIDECAR rather than on a log line on purpose: the log
    scrolls away and the sidecar is what an operator finds beside the file
    weeks later, when they provision the grant. An instruction that is complete
    only in a log the reader does not have is not complete.

    Found in countersign of omniclaude#2303, not by the author.
    """
    journal.append(
        jdir, event_type="denied.class", payload={"i": 0}, correlation_id=None
    )
    journal.append(jdir, event_type="ok.class", payload={}, correlation_id=None)

    _drain_n_cycles(
        jdir,
        RefusingEmitter("denied.class"),
        drainer.DEFAULT_QUARANTINE_AFTER_FAILURES + 1,
    )

    qdir = jdir / "quarantine"
    record = next(p for p in qdir.glob("*.json") if not p.name.endswith(".reason.json"))
    detail = json.loads((qdir / f"{record.stem}.reason.json").read_text())["detail"]

    assert "REPLAY DOES NOT PRESERVE ORDER" in detail, (
        "the sidecar instructs a replay without saying that replay reorders; "
        "an operator following it is making an ordering decision they were "
        f"never told they were making. Got: {detail}"
    )
    # AC3: the caveat may not be bought by deleting the instruction.
    assert "provision the grant" in detail and "move this file back" in detail, (
        "the replay instruction must survive the caveat -- removing it would "
        "satisfy the assertion above trivially and make the dead-letter useless"
    )


def test_the_dead_letter_log_line_carries_the_same_caveat() -> None:
    """OMN-19118 AC2: the log reader is not given a different instruction.

    Two surfaces tell an operator to replay. If only one of them names the
    cost, which one they read decides what they know, and that is exactly the
    kind of split that makes an instruction unreliable.

    Asserted against the source of the call rather than by capturing logging,
    because the point is that the two strings agree, not that one was emitted.
    """
    source = (_LIB_DIR / "hook_emit_drainer.py").read_text(encoding="utf-8")
    _, _, after_instruction = source.partition("provision the grant and move it back")
    assert "REPLAY DOES NOT PRESERVE ORDER" in after_instruction[:400], (
        "the log line instructs a replay without the ordering caveat the "
        "sidecar carries, so what an operator knows depends on which surface "
        "they happened to read"
    )
