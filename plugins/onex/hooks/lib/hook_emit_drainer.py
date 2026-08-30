#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Singleton drainer for the hook-emit journal (OMN-17224): the slow half.

One long-lived process replaces N-per-tool-call throwaway processes. It pays
the ~30s ``omnibase_infra`` Pydantic import **once** at startup, then
publishes journalled events through the existing
``HandlerEventEmitEffect`` -- so topic fan-out, enrichment, partition keys
and the node's own spool all behave exactly as before. This changes the
process model, not the emit semantics.

Why not a Plugin* daemon class
------------------------------
``omnibase_infra.validators.no_plugin_daemon_classes`` (pre-commit + CI)
forbids ``Plugin*`` classes owning daemon/worker/runtime lifecycles, and
CLAUDE.md rule 7a allows exactly three primitives. This module defines no
such class: it is a plain script whose resident lifecycle is owned by
launchd (``scripts/launchd/ai.omninode.hook-emit-drainer.plist``, KeepAlive),
following the OMN-17173 precedent for durable local processes on this Mac.
The emit logic it calls still lives behind the node/handler boundary.

Delivery semantics
------------------
At-least-once. A journal record is acked (unlinked) only after
``handle()`` reports a confirmed publish. Kill the drainer mid-publish and
the record replays on restart -- duplicates are acceptable on a telemetry
stream, silent loss is not (AC5).

Backpressure: when the broker is unreachable the drainer backs off and
leaves records queued. The journal's own bound
(``hook_emit_journal.DEFAULT_MAX_RECORDS``) is what stops unbounded growth,
dropping oldest and counting the drops.

Which broker
------------
The declared one, from ``hooks/contracts/hook_edge_lane.yaml`` (OMN-17204),
resolved by :func:`apply_declared_lane` before the first publish.

This is load-bearing rather than tidy. OMN-17204 made every
``*_bus_mirror.sh`` apply that contract; this ticket then moved the publish
out of those scripts and into this process, so from that moment the
lane-governed files were the only ones on the edge that no longer published
anything. launchd starts this drainer with an environment of exactly
``{OMNI_HOME, ONEX_STATE_DIR, HOME}`` -- no ``KAFKA_BOOTSTRAP_SERVERS`` at
all -- and ``ModelKafkaEventBusConfig`` has no default for it, so under the
shipped plist every publish raised ``KeyError: 'KAFKA_BOOTSTRAP_SERVERS'``
and every record stayed queued (proven on the operator Mac 2026-08-30).
``validate_hook_edge_lane.py`` now reads this file, so the publisher cannot
leave the declared lane again without failing a merge gate.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_journal as journal  # noqa: E402

logger = logging.getLogger("hook_emit_drainer")

DEFAULT_POLL_SECONDS = 2.0
DEFAULT_IDLE_POLL_SECONDS = 10.0
DEFAULT_ERROR_BACKOFF_SECONDS = 30.0
DEFAULT_BATCH_LIMIT = 200

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    logger.info("received signal %s; finishing current batch then exiting", signum)


def apply_declared_lane(*, contract_path: Path | None = None) -> str | None:
    """Point this process at the contract-declared bus lane. Returns the broker.

    Sets ``KAFKA_BOOTSTRAP_SERVERS`` (what ``ModelKafkaEventBusConfig`` reads),
    ``KAFKA_BROKERS`` (the legacy alias ``common.sh`` keeps in lock-step) and
    ``ONEX_HOOK_EDGE_LANE`` (the lane NAME, so a log line can say which lane it
    meant instead of making a reader re-derive it from a host:port).

    The contract wins over an ambient value, in both directions: an unset var
    is filled in, and a var naming a different lane is overwritten. That is the
    OMN-17204 rule -- an env var that disagrees is a finding, never an input --
    applied to the process that actually publishes.

    Returns ``None`` and leaves the environment untouched when the contract
    cannot be read. Deliberately not fatal: this is a launchd ``KeepAlive``
    agent, so exiting here would spin the restart loop and recreate the CPU
    burn OMN-17224 removed. Degrading to the ambient env means the next publish
    raises a named error and the drainer backs off -- loud, bounded, and with
    every record still on disk.
    """
    path = contract_path or (
        Path(__file__).resolve().parent.parent / "contracts" / "hook_edge_lane.yaml"
    )
    try:
        import hook_edge_lane

        contract = hook_edge_lane.load_contract(path)
        brokers = hook_edge_lane.resolve_bootstrap_servers(contract)
    except Exception as exc:  # noqa: BLE001 -- degrade, do not kill the daemon
        logger.error(
            "could not resolve the declared hook-edge lane from %s: %s; "
            "falling back to the ambient environment",
            path,
            exc,
        )
        return None

    previous = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if previous and previous != brokers:
        logger.warning(
            "ambient KAFKA_BOOTSTRAP_SERVERS=%s disagrees with declared lane "
            "%s (%s); the contract wins",
            previous,
            contract.lane,
            brokers,
        )
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = brokers
    os.environ["KAFKA_BROKERS"] = brokers
    os.environ["ONEX_HOOK_EDGE_LANE"] = contract.lane
    logger.info("publishing to declared lane %s (%s)", contract.lane, brokers)
    return brokers


class _Emitter:
    """Lazily-built, reused handler.

    The whole point of this class is that ``_load()`` runs at most once per
    process. Constructing it eagerly at import time would make a
    ``--help`` or a misconfigured start pay the 30s cost for nothing.
    """

    def __init__(self) -> None:
        self._handler: Any | None = None
        self._request_cls: Any | None = None

    def _load(self) -> bool:
        if self._handler is not None:
            return True
        t0 = time.perf_counter()
        try:
            from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
                HandlerEventEmitEffect,
            )
            from omnimarket.nodes.node_event_emit_effect.models.model_emit_request import (
                ModelEmitRequest,
            )
        except Exception as exc:  # noqa: BLE001 -- degrade, do not crash the daemon
            logger.error("emit handler import failed: %s", exc)
            return False
        self._handler = HandlerEventEmitEffect()
        self._request_cls = ModelEmitRequest
        logger.info(
            "emit handler loaded in %.1fs (paid once for this process, "
            "not once per tool call)",
            time.perf_counter() - t0,
        )
        return True

    def publish(self, record: journal.JournalRecord) -> bool:
        """Publish one journalled event. Returns True only on a confirmed ack."""
        if not self._load():
            return False
        assert self._handler is not None and self._request_cls is not None
        try:
            request = self._request_cls(
                event_type=record.event_type,
                topic=record.event_type,
                payload=record.payload,
                correlation_id=record.correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            # A malformed record can never be published; acking it is correct,
            # otherwise it blocks the queue head forever (a poison pill).
            logger.warning(
                "dropping unpublishable record %s (%s): %s",
                record.event_id,
                record.event_type,
                exc,
            )
            return True
        try:
            result = self._handler.handle(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("publish raised for %s: %s", record.event_id, exc)
            return False
        return bool(result.published)


def drain_once(
    journal_dir: Path, emitter: _Emitter, *, batch_limit: int = DEFAULT_BATCH_LIMIT
) -> tuple[int, int]:
    """Drain up to ``batch_limit`` records. Returns (published, failed).

    Stops at the first failure so ordering is preserved and a dead broker
    does not burn the whole backlog against a wall.
    """
    pending = journal.list_pending(journal_dir)[:batch_limit]
    published = 0
    for entry in pending:
        if _shutdown:
            break
        if emitter.publish(entry.record):
            journal.ack(entry)
            published += 1
        else:
            return published, len(pending) - published
    return published, 0


def run(
    journal_dir: Path,
    lock_path: Path,
    *,
    poll_seconds: float,
    idle_poll_seconds: float,
    once: bool,
) -> int:
    lock = journal.SingletonLock(lock_path)
    if not lock.acquire():
        logger.info("another drainer holds %s; exiting", lock_path)
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Before the first publish, never after: the emitter reads the broker out
    # of the environment when it builds its adapter.
    apply_declared_lane()

    emitter = _Emitter()
    logger.info("draining %s (pid %s)", journal_dir, os.getpid())
    try:
        while True:
            published, failed = drain_once(journal_dir, emitter)
            if published:
                logger.info("published %d event(s)", published)
            if once:
                return 0
            if _shutdown:
                return 0
            if failed:
                logger.warning(
                    "%d event(s) still queued; backing off %.0fs",
                    failed,
                    DEFAULT_ERROR_BACKOFF_SECONDS,
                )
                time.sleep(DEFAULT_ERROR_BACKOFF_SECONDS)
            else:
                time.sleep(poll_seconds if published else idle_poll_seconds)
    finally:
        lock.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal-dir", default=None)
    parser.add_argument("--lock-path", default=None)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--idle-poll-seconds", type=float, default=DEFAULT_IDLE_POLL_SECONDS
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain one batch and exit (used by tests and manual flushes).",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    journal_dir = (
        Path(args.journal_dir) if args.journal_dir else journal.default_journal_dir()
    )
    lock_path = (
        Path(args.lock_path)
        if args.lock_path
        else (
            journal_dir.parent / "hook_emit_drainer.lock"
            if args.journal_dir
            else journal.default_lock_path()
        )
    )
    try:
        return run(
            journal_dir,
            lock_path,
            poll_seconds=args.poll_seconds,
            idle_poll_seconds=args.idle_poll_seconds,
            once=args.once,
        )
    except Exception as exc:  # noqa: BLE001 -- a daemon must not die on a stray error
        logger.error("drainer exiting on unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
