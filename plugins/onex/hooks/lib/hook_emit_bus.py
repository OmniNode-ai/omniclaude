# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""One Kafka bus for the life of the hook-emit drainer (OMN-19518).

WHY THIS EXISTS. ``KafkaEventPublisher._publish_once`` (omnimarket
``node_event_emit_effect``) builds, starts and closes a bus per record: on
2026-09-25 00:00Z to 01:00Z that was 1,274 events, 1,292 bus starts and 2,584
SCRAM authentications, and the SASL handshake timeouts came from the churn.

HOW. The publisher takes a ``bus_factory``; the drainer hands it one that
always returns this proxy, which owns one real bus. ``start()`` builds it only
when there is none, ``publish()`` forwards to it, ``close()`` (called after
every record) does nothing, and ``shutdown()`` closes it when the drainer exits.

ERROR HANDLING. A bus that has failed is never trusted again. Any exception,
or a cancellation (the handler's per-publish timeout), discards the real bus,
closed in the background so a hanging close cannot stall the drain. A failure
on a bus REUSED from an earlier record (most likely an idle connection the
broker closed) is retried once on a fresh bus inside the same call; a failure
on a bus started for this call is reported and the drainer's backoff applies.
The exception is a payload over ``max_request_size`` (OMN-19513): the client
refuses it before sending, so the bus is kept and nothing is retried. On
2026-10-16 one 1.58 MB spooled hook event, retried behind every record, cost
each record two bus starts and cut publishing from about 6 to 1 per second.
At-least-once; the content event id is the idempotency key. Stdlib only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("hook_emit_drainer")


def _is_payload_too_large(exc: BaseException | None) -> bool:
    """aiokafka's size refusal, raised directly or as the transport's cause."""
    for _ in range(8):  # bounded: a cause chain can cycle
        if exc is None or type(exc).__name__ == "MessageSizeTooLargeError":
            return exc is not None
        exc = exc.__cause__
    return False


class PersistentBus:
    """A bus proxy that starts its real bus once and reuses it across records."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._bus: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started_in_this_call = False
        self._pending_closes: set[asyncio.Task[None]] = set()
        self.starts = 0

    async def start(self) -> None:
        """Start the real bus if there is none; otherwise reuse it."""
        self._started_in_this_call = await self._acquire_fresh() is not None

    async def _acquire_fresh(self) -> Any | None:
        """Return a bus started by this call, or ``None`` when one is reused."""
        self._loop = asyncio.get_running_loop()
        if self._bus is not None:
            return None
        bus = self._factory()
        try:
            await bus.start()
        except BaseException:
            self._close_in_background(bus)
            raise
        self._bus = bus
        self.starts += 1
        logger.info(
            "persistent emit bus started (start #%d for this process)", self.starts
        )
        return bus

    async def _live_bus(self) -> tuple[Any, bool]:
        """The bus to publish on, and whether it was started for this call."""
        fresh = self._started_in_this_call
        self._started_in_this_call = False
        started = await self._acquire_fresh()
        if started is not None:
            return started, True
        return self._bus, fresh

    async def publish(self, **kwargs: Any) -> None:
        """Publish on the live bus; on a reused bus, retry once on a fresh one."""
        bus, fresh = await self._live_bus()
        try:
            await bus.publish(**kwargs)
            return
        except asyncio.CancelledError:
            self._discard(bus)
            raise
        except Exception as exc:
            if _is_payload_too_large(exc):
                raise
            self._discard(bus)
            if fresh:
                raise
            logger.warning(
                "publish failed on a reused emit bus (%s: %s); retrying once "
                "on a fresh bus",
                type(exc).__name__,
                exc,
            )
        retry_bus, _ = await self._live_bus()
        try:
            await retry_bus.publish(**kwargs)
        except BaseException:
            self._discard(retry_bus)
            raise

    async def close(self) -> None:
        """Called by the publisher after every record: the bus outlives it."""
        return

    async def shutdown(self) -> None:
        """Close the real bus. Called once, when the drainer exits."""
        bus, self._bus = self._bus, None
        if bus is not None:
            await _close_quietly(bus)
        if self._pending_closes:
            await asyncio.gather(*self._pending_closes, return_exceptions=True)

    def shutdown_blocking(self, timeout: float = 5.0) -> None:
        """Run :meth:`shutdown` on the loop the bus lives on, from another thread."""
        loop = self._loop
        if loop is None or loop.is_closed() or self._bus is None:
            return
        future = asyncio.run_coroutine_threadsafe(self.shutdown(), loop)
        future.result(timeout=timeout)

    def _discard(self, bus: Any) -> None:
        if self._bus is bus:
            self._bus = None
        self._close_in_background(bus)

    def _close_in_background(self, bus: Any) -> None:
        task = asyncio.get_running_loop().create_task(_close_quietly(bus))
        self._pending_closes.add(task)
        task.add_done_callback(self._pending_closes.discard)


async def _close_quietly(bus: Any) -> None:
    try:
        await bus.close()
    except Exception as exc:  # noqa: BLE001 -- a failed close must not mask the cause
        logger.debug("closing a discarded emit bus raised: %s", exc)
