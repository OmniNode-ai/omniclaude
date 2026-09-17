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

Where a published hook event ENDS UP: two planes, two ledgers (OMN-18120 AC5)
--------------------------------------------------------------------------
Three separate lanes read `public.hook_events` as empty on a compose
lane and concluded the bare-canonical hook wire had no consumer anywhere, and
that the repair was to declare a `hook-ledger` writer service in the compose
file. Both halves are wrong, and the second would have made things worse. The
split is written here, beside the publisher, because this is the file a lane
asking "where did my hook event go" opens first.

    PLANE           WIRE                       LEDGER TABLE
    compose / L1    bare canonical topics      omninode_internal.work_events
                    (`onex.evt.omniclaude.*`)  written by node_projection_work_events
    cloud           the same topics, carrying  public.hook_events
                    a tenant prefix applied    written by the k3s
                    at runtime                 node_projection_hook_ledger

* `work_events` IS the compose plane's hook ledger. It held 71,176 rows over
  exactly the four bare-canonical hook classes when it was being called
  empty, so the canonical wire has a consumer and has always had one.
* `hook_events` is the CLOUD sink. It is correctly empty on a plane that is
  not the cloud. An empty `hook_events` on a compose lane is not a missing
  service.
* The prefix is not a second topic declaration. `node_projection_hook_ledger`
  declares only bare canonical topics -- the shared resolver rejects a
  tenant-prefixed string outright -- and the prefix is applied at runtime
  from `config.hook_ledger.cloud_wire_scope`.
* Declaring a compose-lane `hook-ledger` writer would subscribe a SECOND
  claimant to the bare-canonical topics in the shared kernel, which that
  node's own contract refuses by name: it takes no shared-kernel profile
  "because node_projection_work_events already claims the same four BARE
  canonical topics in that kernel -- a second claimant there would be a
  dispatch ambiguity, not a second reader." It would duplicate an existing
  projection into a second table and introduce exactly that ambiguity.

The corollary that cost the most time: `max(ingested_at)` on `work_events`
freezing is NOT evidence that the projection stopped. During the 2026-09-06
to 09-10 window the projection was consuming every record and upserting
idempotently; the INPUT had stopped being new, because the stream was
replaying pre-09-06 events. `hook_edge_freshness.py` in this directory is the
check that tells those two apart -- content age, never offsets.

Which credential (OMN-18120)
    The lane also declares WHERE its identity is resolved from. On the lab
    host that is the operator env file; on an operator workstation it is the
    per-lane client store under ``~/.onex`` -- the same one ``onex delegate
    --lane`` reads, so one machine dialling one lane presents one principal.
    The resolver reads the declared surface and does not fall back to the
    other: an absent identity is a refusal naming its remedy, never a
    connection as a different principal.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

logger = logging.getLogger("hook_emit_drainer")

DEFAULT_POLL_SECONDS = 2.0
DEFAULT_IDLE_POLL_SECONDS = 10.0
DEFAULT_ERROR_BACKOFF_SECONDS = 30.0
DEFAULT_BATCH_LIMIT = 200

_QUARANTINE_DIRNAME = "quarantine"

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    logger.info("received signal %s; finishing current batch then exiting", signum)


def apply_declared_lane(
    *, contract_path: Path | None = None, onex_home: Path | None = None
) -> str | None:
    """Point this process at the contract-declared bus lane. Returns the broker.

    Sets ``KAFKA_BOOTSTRAP_SERVERS`` (what ``ModelKafkaEventBusConfig`` reads),
    ``KAFKA_BROKERS`` (the legacy alias ``common.sh`` keeps in lock-step),
    ``ONEX_HOOK_EDGE_LANE`` (the lane NAME, so a log line can say which lane it
    meant instead of making a reader re-derive it from a host:port), and the
    lane's declared TRANSPORT -- ``KAFKA_SECURITY_PROTOCOL`` plus, on a SASL
    lane, ``KAFKA_SASL_MECHANISM`` / ``KAFKA_SASL_USERNAME`` /
    ``KAFKA_SASL_PASSWORD``.

    The contract wins over an ambient value, in both directions: an unset var
    is filled in, and a var naming a different lane is overwritten. That is the
    OMN-17204 rule -- an env var that disagrees is a finding, never an input --
    applied to the process that actually publishes.

    TRANSPORT, NOT JUST ADDRESS (OMN-17284). The lane declares how its broker
    is spoken to; this function never infers it from whether a credential
    happens to be present. The credential VALUE is read at run time from the
    operator env file the lane's ``sasl_env_prefix`` points at, so nothing
    secret is written into the contract, the plist, or this module.

    Returns ``None`` and leaves the environment untouched when the contract
    cannot be read OR when a SASL lane's credential is not on this host.
    Deliberately not fatal: this is a launchd ``KeepAlive`` agent, so exiting
    here would spin the restart loop and recreate the CPU burn OMN-17224
    removed. Nothing is applied on the failing path -- a half-configured SASL
    client fails differently from the failure being reported, which is worse
    than not being configured at all. The refusal names the missing variable
    and the file, because the alternative is what the operator actually saw:
    ``Unable to bootstrap from [...]`` every thirty seconds, with no way to
    tell a broker that refused an unauthenticated client from one that is down.
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

    # Resolved BEFORE anything is written to the environment, so a lane whose
    # credential is absent leaves no partial configuration behind.
    #
    # ``onex_home`` is injected so a caller -- in practice a test -- can drive a
    # synthetic client store instead of whatever this machine happens to hold.
    # None means the real one. Same injection the canonical StoreLaneCredential
    # uses, and the same reason these tests already inject an operator env file:
    # a test that reads host state gives a different verdict per machine.
    #
    # WHICH surface holds the credential is the lane's own declaration
    # (``sasl_credential_source``), not this function's guess and not a search
    # order -- see OMN-18120. On this host the dev lane declares the ~/.onex
    # client store, which is the identity ``onex delegate --lane dev`` also
    # presents, so both dev-lane clients on the machine are one principal.
    try:
        transport = hook_edge_lane.resolve_credential_environment(
            contract, onex_home=onex_home
        )
    except hook_edge_lane.HookEdgeLaneCredentialError as exc:
        logger.error(
            "declared lane %s (%s) cannot be published to from this host: %s",
            contract.lane,
            brokers,
            exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 -- degrade, do not kill the daemon
        logger.error(
            "could not resolve the transport declared for lane %s in %s: %s",
            contract.lane,
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
    os.environ.update(transport)
    # Names only. The drainer's log is ~75 MB and world-readable on the
    # operator Mac, so a value logged here is a value disclosed.
    logger.info(
        "publishing to declared lane %s (%s) over %s%s",
        contract.lane,
        brokers,
        transport[hook_edge_lane.ENV_SECURITY_PROTOCOL],
        (
            f" using {transport[hook_edge_lane.ENV_SASL_MECHANISM]} as the "
            f"principal this host declares in "
            f"{contract.known_lanes[contract.lane].sasl_credential_source}"
            if hook_edge_lane.ENV_SASL_MECHANISM in transport
            else ""
        ),
    )
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
                topic=None,
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


def _legacy_topic_to_semantic_event() -> dict[str, str] | None:
    """Read the installed contract and invert unambiguous legacy topic rules.

    The journal used to store a fully-qualified fan-out topic in ``event_type``.
    A finite migration converts only topics with one declared semantic owner.
    No hard-coded aliases are accepted: anything absent or ambiguous remains
    durable for inspection in quarantine.
    """
    try:
        import yaml
        from omnimarket.nodes.node_event_emit_effect.spool.topic_resolver import (
            default_registry_path,
        )

        raw = yaml.safe_load(default_registry_path().read_text(encoding="utf-8"))
        events = raw["events"]
        candidates: dict[str, set[str]] = {}
        for event_type, definition in events.items():
            for rule in definition.get("fan_out", []):
                topic = rule.get("topic")
                if isinstance(topic, str):
                    candidates.setdefault(topic, set()).add(event_type)
    except Exception as exc:  # noqa: BLE001 -- leave records inspectable
        logger.error("cannot load event registry for legacy journal migration: %s", exc)
        return None
    return {
        topic: next(iter(event_types))
        for topic, event_types in candidates.items()
        if len(event_types) == 1
    }


def migrate_legacy_journal(journal_dir: Path) -> tuple[int, int]:
    """Convert known FQ journal records once and quarantine the rest.

    Conversion is atomic per file and retains the original payload,
    correlation ID, event ID, and queue time. An FQ record whose topic is no
    longer contract-declared is never acked or sent to the broker: it is moved
    byte-for-byte into ``quarantine/`` for manual resolution.
    """
    topic_to_event = _legacy_topic_to_semantic_event()
    if topic_to_event is None:
        return 0, 0

    migrated = 0
    quarantined = 0
    for entry in journal.list_pending(journal_dir):
        legacy_topic = entry.record.event_type
        if not legacy_topic.startswith("onex."):
            continue
        semantic_event = topic_to_event.get(legacy_topic)
        if semantic_event is not None:
            converted = replace(entry.record, event_type=semantic_event)
            tmp = entry.path.with_name(f".{entry.path.name}.migration.tmp")
            try:
                tmp.write_text(converted.to_json(), encoding="utf-8")
                tmp.replace(entry.path)
                migrated += 1
            except OSError as exc:
                logger.error(
                    "cannot migrate legacy journal record %s: %s", entry.path, exc
                )
                try:
                    tmp.unlink()
                except OSError:
                    pass
            continue

        quarantine = journal_dir / _QUARANTINE_DIRNAME
        target = quarantine / entry.path.name
        try:
            quarantine.mkdir(parents=True, exist_ok=True)
            entry.path.replace(target)
            quarantined += 1
            logger.error(
                "quarantined unclassified legacy journal record %s (%s)",
                entry.record.event_id,
                legacy_topic,
            )
        except OSError as exc:
            logger.error(
                "cannot quarantine legacy journal record %s: %s", entry.path, exc
            )
    return migrated, quarantined


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
    migrated, quarantined = migrate_legacy_journal(journal_dir)
    if migrated or quarantined:
        logger.info(
            "legacy journal migration: migrated=%d quarantined=%d",
            migrated,
            quarantined,
        )
    logger.info("draining %s (pid %s)", journal_dir, os.getpid())

    # OMN-18471 AC4. The alert that is supposed to notice this process
    # stopping used to read emit_via_daemon's socket fail-counters, which
    # have been frozen since June and said the same thing whether this
    # drainer was healthy or dead. It now reads the two facts only this
    # loop can state: that a cycle completed, and when a publish was last
    # CONFIRMED. Written every cycle, not only on success -- a file that
    # appears only when things work cannot tell "it failed" from "nobody
    # ran it", which is the whole job.
    status_path = (
        journal_dir.parent / health.STATUS_FILENAME
        if journal_dir != health.default_journal_dir()
        else health.default_status_path()
    )
    last_publish_at: float | None = None
    published_total = 0

    def _record_cycle() -> None:
        try:
            health.write_status(
                status_path,
                health.ModelDrainerStatus(
                    last_cycle_at=time.time(),
                    last_publish_at=last_publish_at,
                    published_total=published_total,
                    pid=os.getpid(),
                ),
            )
        except OSError as exc:  # pragma: no cover - reported, never fatal
            # A drainer that cannot write its own health file must keep
            # draining: losing the signal is strictly better than losing
            # the telemetry it is reporting on.
            logger.warning("could not write drainer status %s: %s", status_path, exc)

    try:
        while True:
            published, failed = drain_once(journal_dir, emitter)
            if published:
                logger.info("published %d event(s)", published)
                published_total += published
                last_publish_at = time.time()
            _record_cycle()
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
