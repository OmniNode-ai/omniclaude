# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook-emit drainer reuses one Kafka bus for the life of the process (OMN-19518).

The defect, measured in the drainer log for 2026-09-25 00:00Z to 01:00Z: 1,274
events published, 1,292 bus starts and 2,584 SCRAM authentications -- a new
producer and two logins for every event. The drainer handed each record to
``HandlerEventEmitEffect.handle()`` with no publish adapter, so the handler
built a fresh ``KafkaEventPublisher`` per call, and that publisher starts and
closes an ``EventBusKafka`` per record.

What each test pins
-------------------
* AC1 -- N records through the real drainer emitter and the real emit handler
  start the bus once. The only fake is ``EventBusKafka`` itself, patched at the
  symbol the publisher imports, so the test exercises the drainer's actual
  wiring rather than a stand-in for it.
* AC2 -- a failure on a reused bus is retried once on a fresh bus; a failure on
  a fresh bus is reported and the next publish starts a new one; a cancelled
  publish (the handler's timeout) discards the bus; shutdown closes it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_emit_drainer as drainer  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

event_bus_kafka = pytest.importorskip("omnibase_infra.event_bus.event_bus_kafka")
pytest.importorskip(
    "omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect"
)


class FakeBus:
    """Stands in for ``EventBusKafka``: counts lifecycle calls, fails on demand."""

    starts: ClassVar[int] = 0
    closes: ClassVar[int] = 0
    publishes: ClassVar[list[str]] = []
    # Each entry is consumed by one publish call: None succeeds, an exception
    # instance is raised. An empty plan means every publish succeeds.
    plan: ClassVar[list[BaseException | None]] = []

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.started = False

    @classmethod
    def reset(cls) -> None:
        cls.starts = 0
        cls.closes = 0
        cls.publishes = []
        cls.plan = []

    async def start(self) -> None:
        FakeBus.starts += 1
        self.started = True

    async def publish(self, *, topic: str, **_: Any) -> None:
        assert self.started, "publish on a bus that was never started"
        if FakeBus.plan:
            outcome = FakeBus.plan.pop(0)
            if outcome is not None:
                raise outcome
        FakeBus.publishes.append(topic)

    async def close(self) -> None:
        FakeBus.closes += 1
        self.started = False


@pytest.fixture
def fake_bus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> type[FakeBus]:
    FakeBus.reset()
    monkeypatch.setattr(event_bus_kafka, "EventBusKafka", FakeBus)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "fake-broker:9092")
    monkeypatch.setenv("ONEX_EMIT_EFFECT_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.delenv("ONEX_EMIT_EFFECT_SPOOL_ONLY", raising=False)
    return FakeBus


def _record(i: int) -> journal.JournalRecord:
    return journal.JournalRecord(
        event_id=f"record-{i}",
        event_type="tool.executed",
        payload={
            "session_id": "9787a4a3-ec49-4819-8bdc-5044efb94550",
            "tool_name": "Bash",
            "duration_ms": i,
            "interrupted": False,
            "hook_source": "post_tool_use",
            "working_directory": "workspace",
        },
        correlation_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
        queued_at=journal.datetime.now(journal.UTC),
    )


def test_many_records_start_the_bus_once(fake_bus: type[FakeBus]) -> None:
    emitter = drainer._Emitter()
    try:
        results = [emitter.publish(_record(i)) for i in range(5)]
        assert results == [True] * 5
        assert fake_bus.publishes, "nothing reached the bus"
        assert fake_bus.starts == 1, (
            f"{fake_bus.starts} bus starts for 5 records: a producer and a SCRAM "
            "login per event is the defect"
        )
        assert fake_bus.closes == 0, "the bus must outlive each record"
    finally:
        emitter.close()


def test_a_failure_on_a_reused_bus_is_retried_once_on_a_fresh_bus(
    fake_bus: type[FakeBus],
) -> None:
    emitter = drainer._Emitter()
    try:
        assert emitter.publish(_record(0)) is True
        fake_bus.plan = [ConnectionError("broker dropped the idle connection")]
        assert emitter.publish(_record(1)) is True, (
            "a stale reused connection must not cost the record a 30s backoff"
        )
        assert fake_bus.starts == 2
    finally:
        emitter.close()


def test_a_failure_on_a_fresh_bus_is_reported_and_the_next_publish_rebuilds(
    fake_bus: type[FakeBus],
) -> None:
    emitter = drainer._Emitter()
    try:
        fake_bus.plan = [ConnectionError("broker unreachable")]
        assert emitter.publish(_record(0)) is False, "a real failure must surface"
        starts_after_failure = fake_bus.starts
        assert emitter.publish(_record(1)) is True
        assert fake_bus.starts == starts_after_failure + 1, (
            "a bus that failed must be discarded, never reused"
        )
    finally:
        emitter.close()


def test_shutdown_closes_the_bus(fake_bus: type[FakeBus]) -> None:
    emitter = drainer._Emitter()
    assert emitter.publish(_record(0)) is True
    emitter.close()
    assert fake_bus.closes == fake_bus.starts == 1


def test_spool_only_opt_out_still_publishes_nothing(
    fake_bus: type[FakeBus], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler's declared opt-out keeps working when the drainer injects a bus."""
    monkeypatch.setenv("ONEX_EMIT_EFFECT_SPOOL_ONLY", "1")
    emitter = drainer._Emitter()
    try:
        assert emitter.publish(_record(0)) is False
        assert fake_bus.starts == 0
    finally:
        emitter.close()


def test_a_cancelled_publish_discards_the_bus() -> None:
    """The handler's timeout cancels the publish; the bus it was on is suspect."""
    import hook_emit_bus

    class HangingBus(FakeBus):
        async def publish(self, *, topic: str, **_: Any) -> None:
            await asyncio.sleep(60)

    FakeBus.reset()
    buses: list[FakeBus] = []

    def factory() -> FakeBus:
        bus = HangingBus() if not buses else FakeBus()
        buses.append(bus)
        return bus

    async def scenario() -> None:
        proxy = hook_emit_bus.PersistentBus(factory)
        await proxy.start()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(proxy.publish(topic="t", key=None), timeout=0.05)
        for _ in range(3):  # let the scheduled close of the discarded bus run
            await asyncio.sleep(0)
        await proxy.start()
        await proxy.publish(topic="t", key=None)
        await proxy.shutdown()

    asyncio.run(scenario())
    assert len(buses) == 2, "the cancelled bus was reused"
    assert FakeBus.starts == 2
    assert FakeBus.closes == 2, "the discarded bus and the live one are both closed"
    assert FakeBus.publishes == ["t"]
