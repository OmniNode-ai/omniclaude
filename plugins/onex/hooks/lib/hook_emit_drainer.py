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
import fcntl
import json
import logging
import logging.handlers
import os
import signal
import stat
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_bus  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402

logger = logging.getLogger("hook_emit_drainer")

DEFAULT_POLL_SECONDS = 2.0
DEFAULT_IDLE_POLL_SECONDS = 10.0
DEFAULT_ERROR_BACKOFF_SECONDS = 30.0
DEFAULT_BATCH_LIMIT = 200

# How many CONSECUTIVE failures of the same head record before it is treated as
# poison and moved to the dead-letter (OMN-19074).
#
# THE ARITHMETIC, not a round number. A failing cycle costs one publish attempt
# plus DEFAULT_ERROR_BACKOFF_SECONDS, so with the transport failing fast on a
# permanent refusal a cycle is ~30s and five of them are ~2.5 minutes. A broker
# blip that resolves inside two and a half minutes therefore never reaches the
# threshold, and a record is never set aside for a fault that had already
# healed. Raising it trades a longer total stall for a margin the stand-down
# probe below already provides more cheaply; lowering it buys minutes at the
# cost of that margin.
#
# The threshold is the CHEAP half of the guard and deliberately not the whole
# one. What actually distinguishes "this record is poison" from "the broker is
# down" is _broker_answers_behind_the_head, which measures rather than guesses.
DEFAULT_QUARANTINE_AFTER_FAILURES = 5

_QUARANTINE_DIRNAME = "quarantine"

#: Written beside a dead-lettered journal record, in the shape
#: node_event_emit_effect's own ModelQuarantineReason uses, so one reconcile can
#: read both dead-letters. Kept as a plain dict because this module is
#: stdlib-only by contract and must not import a Pydantic model to write a file.
_QUARANTINE_REASON_SCHEMA_VERSION = 1

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


#: Payload key carrying the instant the HOOK FIRED, as distinct from the
#: instant this drainer published it (OMN-18609).
FIRE_TIME_KEY = "hook_fired_at"


def _with_fire_time(record: journal.JournalRecord) -> dict[str, object]:
    """``record.payload`` plus the instant the hook fired.

    WHY THIS EXISTS. Before it, the only timestamp that survived to the cloud
    was stamped by the emit envelope at PUBLISH time, so the ledger's time axis
    was the relay's rather than the work's. The journal has always recorded
    ``queued_at`` at the moment the hook fired; ``publish`` simply did not carry
    it, so it was discarded at the last hop.

    MEASURED CONSEQUENCE, 2026-09-17. This drainer died at 15:31Z and was
    unsupervised, so the last event reaching the cloud before the outage is
    stamped 15:20:54.543159Z and the next 16:01:46.740871Z -- a hole of 40
    minutes 52 seconds. The backlog that accumulated inside it was published
    stamped 16:01 to 16:03, putting 468 rows into the single minute 16:02
    against a normal rate of 20 to 40. The work happened during the hole; the
    ledger said it happened after it. Any drop detector reading that table sees
    a relay recovery as a burst of activity and a relay outage as the silence
    of every lane at once.

    The original payload is never mutated -- the journal record is re-published
    on a retry, and a publish must be idempotent in what it sends.
    """
    payload = dict(record.payload)
    payload[FIRE_TIME_KEY] = record.queued_at.isoformat()
    return payload


class _Emitter:
    """Lazily-built, reused handler.

    The whole point of this class is that ``_load()`` runs at most once per
    process. Constructing it eagerly at import time would make a
    ``--help`` or a misconfigured start pay the 30s cost for nothing.
    """

    def __init__(self) -> None:
        self._handler: Any | None = None
        self._request_cls: Any | None = None
        self._bus: hook_emit_bus.PersistentBus | None = None

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
        try:
            adapter = self._build_persistent_adapter(HandlerEventEmitEffect)
        except Exception as exc:  # noqa: BLE001 -- the next publish retries the load
            # Same failure the handler would raise from handle() when the Kafka
            # target is not configured; the record stays journalled.
            logger.error("emit publish adapter could not be built: %s", exc)
            return False
        self._handler = HandlerEventEmitEffect(publish_adapter=adapter)
        self._request_cls = ModelEmitRequest
        logger.info(
            "emit handler loaded in %.1fs (paid once for this process, "
            "not once per tool call)",
            time.perf_counter() - t0,
        )
        return True

    def _build_persistent_adapter(self, handler_cls: Any) -> Any | None:
        """A publisher whose Kafka bus is started once per process (OMN-19518).

        Without an injected adapter the handler builds a ``KafkaEventPublisher``
        per ``handle()`` call, and that publisher starts and closes a bus per
        record: 2,584 SCRAM logins for 1,274 events in one measured hour. The
        publisher's own ``bus_factory`` seam takes a factory; this one always
        returns the same :class:`hook_emit_bus.PersistentBus`, which owns one
        real bus and discards it on any failure.

        ``None`` keeps the handler's own contract-declared spool-only opt-out
        working: with no adapter injected, the handler resolves it exactly as
        before and publishes nothing.
        """
        if handler_cls._spool_only_opt_out():
            return None
        from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
        from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
            KafkaEventPublisher,
        )

        bootstrap = ModelKafkaEventBusConfig().apply_environment_overrides()
        bootstrap_servers = bootstrap.bootstrap_servers

        def _real_bus() -> Any:
            # The sanctioned constructor, resolved at call time so the bus
            # picks up the lane apply_declared_lane() put in the environment.
            # The transport is explicit: the drainer publishes to the declared
            # Kafka lane or not at all, never to an in-memory bus.
            from omnibase_infra.backends.auto_configure import (
                BUS_KAFKA,
                select_event_bus,
            )

            return select_event_bus(
                bus_type=BUS_KAFKA, kafka_bootstrap_servers=bootstrap_servers
            )

        self._bus = hook_emit_bus.PersistentBus(_real_bus)
        bus = self._bus
        return KafkaEventPublisher(bootstrap_servers, bus_factory=lambda: bus)

    def close(self) -> None:
        """Close the persistent bus. Called once, when the drainer exits."""
        if self._bus is None:
            return
        try:
            self._bus.shutdown_blocking()
        except Exception as exc:  # noqa: BLE001 -- shutdown must not raise
            logger.warning("closing the persistent emit bus failed: %s", exc)

    def publish(self, record: journal.JournalRecord) -> bool:
        """Publish one journalled event. Returns True only on a confirmed ack."""
        if not self._load():
            return False
        assert self._handler is not None and self._request_cls is not None
        try:
            request = self._request_cls(
                event_type=record.event_type,
                topic=None,
                payload=_with_fire_time(record),
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


def publishable_event_types() -> tuple[str, ...] | None:
    """The event types the installed emit registry declares (OMN-19551).

    Written into the drainer's status so a producer can tell, before it
    journals a new event type, whether this drainer can publish it. A record
    this drainer cannot resolve would fail at the journal head every cycle and
    hold every record behind it until it is dead-lettered, which is the
    OMN-19074 outage shape. ``None`` when the registry cannot be read.
    """
    try:
        import yaml
        from omnimarket.nodes.node_event_emit_effect.spool.topic_resolver import (
            default_registry_path,
        )

        raw = yaml.safe_load(default_registry_path().read_text(encoding="utf-8"))
        events = raw["events"]
    except Exception as exc:  # noqa: BLE001 -- report nothing rather than guess
        logger.error("cannot read the emit registry's event types: %s", exc)
        return None
    if not isinstance(events, dict):
        return None
    return tuple(sorted(str(event_type) for event_type in events))


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


def _overtaken_by_phrase(overtaken_by: journal.JournalEntry | None) -> str:
    """Name the record that published first, or say plainly that it is unknown.

    Never a bare "records behind this one": that states a consequence the
    reader cannot inspect. When the caller has the entry -- which it does on
    the only path that reaches the dead-letter -- the operator gets an id they
    can go and look at. When it does not, saying so is better than implying a
    precision that is absent.
    """
    if overtaken_by is None:
        return "a record queued behind this one (its id was not recorded)"
    return (
        f"record {overtaken_by.record.event_id} "
        f"({overtaken_by.record.event_type}), which was queued behind this one,"
    )


def quarantine_record(
    journal_dir: Path,
    entry: journal.JournalEntry,
    *,
    failures: int,
    overtaken_by: journal.JournalEntry | None = None,
) -> Path | None:
    """Move one unpublishable record into the journal's dead-letter.

    A MOVE, never a delete, for the reason ``SpoolOutbox.quarantine`` gives one
    layer down: the record is unpublishable against today's broker state, which
    is a statement about a grant and not about the record. Provision the grant,
    move the file back, and the drainer publishes it on its next cycle. That
    replay was proven by hand on 2026-09-21 -- four records took their topic's
    high watermark from 0 to 4 with no duplication.

    REPLAY DOES NOT PRESERVE ORDER, and both surfaces below say so (OMN-19118).
    By the time a record is dead-lettered the stand-down probe has already
    published the record that sat BEHIND it, so those two have gone out in the
    opposite order from the journal. Moving the head back later re-introduces
    it into a stream that has already moved past it. Nothing about that is
    fixable here -- a record the broker refuses cannot publish in position
    under any quarantining design -- but the operator holding the grant is the
    one who should decide whether it matters, and they can only decide it if
    the instruction telling them to replay also tells them what replay costs.
    Found in countersign, not by the author: the text was written for someone
    else to follow and read as complete to the person who wrote it.

    ``overtaken_by`` NAMES the record that went out first, and the boundary it
    sits on is the useful part. Saying "records behind this one have already
    published" without saying WHICH one hands the operator a consequence they
    cannot inspect; the probe entry is in the caller's hand at that moment, so
    withholding it is throwing away information this process already has. What
    is deliberately NOT written here is any advice on whether the inversion
    matters. That depends on what consumes the topic and whether it is
    order-sensitive, which the drainer cannot know, and a sentence restating
    the operator's own problem back at them adds length without information.
    Name the pair; do not judge it. (Second-actor finding, omniclaude#2304.)

    The reason is written FIRST and the record moved second, the same ordering
    and for the same reason: a crash between the two then leaves an orphan
    reason beside a still-pending record, which is inert and self-correcting,
    rather than a quarantined record with no reason, which reads exactly like a
    lost one.
    """
    quarantine = journal_dir / _QUARANTINE_DIRNAME
    reason = {
        "schema_version": _QUARANTINE_REASON_SCHEMA_VERSION,
        "quarantined_at": datetime.now(UTC).isoformat(),
        "reason_code": "publish_failed_repeatedly",
        "detail": (
            f"{failures} consecutive publish failures at the journal head, and "
            f"the record behind it published on the same cycle, so the broker "
            f"is reachable and this record is not. To replay: provision the "
            f"grant, then move this file back into the journal directory. "
            f"REPLAY DOES NOT PRESERVE ORDER -- {_overtaken_by_phrase(overtaken_by)} "
            f"already published, so on replay downstream receives this record "
            f"after it, not before."
        ),
        "overtaken_by_event_id": (
            None if overtaken_by is None else overtaken_by.record.event_id
        ),
        "overtaken_by_event_type": (
            None if overtaken_by is None else overtaken_by.record.event_type
        ),
        "event_id": entry.record.event_id,
        "event_type": entry.record.event_type,
        "queued_at": entry.record.queued_at.isoformat(),
        "consecutive_failures": failures,
    }
    try:
        quarantine.mkdir(parents=True, exist_ok=True)
        reason_path = quarantine / f"{entry.path.stem}.reason.json"
        tmp = reason_path.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(reason, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(reason_path)
        target = quarantine / entry.path.name
        entry.path.replace(target)
    except OSError as exc:
        # Never fatal. Failing to dead-letter leaves the record queued, which
        # is the pre-OMN-19074 behaviour, and that is strictly better than
        # losing it.
        logger.error("cannot quarantine journal record %s: %s", entry.path, exc)
        return None
    logger.warning(
        "dead-lettered journal record %s (%s) after %d consecutive failures; "
        "it is MOVED, not deleted -- provision the grant and move it back to "
        "replay it, but note REPLAY DOES NOT PRESERVE ORDER: %s already "
        "published",
        entry.record.event_id,
        entry.record.event_type,
        failures,
        _overtaken_by_phrase(overtaken_by),
    )
    return target


def _broker_answers_behind_the_head(
    pending: list[journal.JournalEntry], emitter: _Emitter
) -> journal.JournalEntry | None:
    """Publish the record BEHIND the head. Returns it on success, else None.

    THE WHOLE GUARD IS HERE, and it is why this is not "skip anything that
    fails". A failure count alone cannot tell a poison record from an
    unreachable broker: both produce an unbounded run of failures at the head.
    Under a count-only rule a long outage would dead-letter the entire backlog
    one record at a time, which is the opposite of what this exists to do.

    So unpublishability is MEASURED rather than inferred. If the next record
    goes out, the broker is reachable and the head is genuinely refused. If it
    fails too, the fault is not specific to the head and nothing is moved.

    Deliberately NOT keyed on the exception type. The transport masked a
    permanent ACL refusal as a TimeoutError for three days (OMN-19073), so a
    guard that trusted an error type would have been the one thing that could
    not see the outage it exists to end. A publish that succeeds is evidence no
    classifier can fake.
    """
    if len(pending) < 2:
        return None
    candidate = pending[1]
    if emitter.publish(candidate.record):
        return candidate
    return None


def drain_once(
    journal_dir: Path,
    emitter: _Emitter,
    *,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    failure_counts: dict[str, int] | None = None,
    quarantine_after: int = DEFAULT_QUARANTINE_AFTER_FAILURES,
) -> tuple[int, int]:
    """Drain up to ``batch_limit`` records. Returns (published, failed).

    Stops at the first failure so ordering is preserved and a dead broker does
    not burn the whole backlog against a wall.

    ONE EXCEPTION, added by OMN-19074. A record that has failed at the head
    ``quarantine_after`` times in a row, while the record behind it publishes
    on the same cycle, has been shown not to be an ordering constraint on
    anything: the broker is answering and is refusing this one. It is
    dead-lettered and the drain continues.

    Before this, one ungranted event class stopped the edge permanently.
    ``drain_once`` halted on it every cycle, the handler quarantined its
    downstream spool copy and still reported ``published=False``, and nothing
    upstream ever acked the journal record. On 2026-09-21 four such records
    held roughly four thousand authorized ones for 105 minutes, the fourth
    outage of that exact shape.

    ``failure_counts`` is owned by the caller so the count survives across
    cycles; a per-call map would reset every 30 seconds and never reach any
    threshold. It is keyed by journal FILENAME, which is unique and stable for
    the life of a record, rather than by event id, because a retried record is
    handed a fresh request id on every attempt (OMN-19073).

    THE COUNT IS PER-PROCESS AND RESETS ON RESTART, deliberately. It lives in
    ``run``'s frame rather than on disk, so a drainer restarted mid-run begins
    counting again and a poison record needs a fresh run of ``quarantine_after``
    failures inside one process lifetime. That is the right trade for a resident
    KeepAlive daemon: persisting it would add a second piece of durable state to
    reconcile against the journal, and the failure it would prevent -- a record
    that is poison across restarts but never fails often enough within one --
    requires the drainer to be dying faster than it can count, which is a
    different defect that this file must not paper over. Worth knowing when
    reproducing: ``--once`` runs one cycle per PROCESS, so it can never reach
    the threshold, and the behaviour must be reproduced against the loop.
    """
    counts = failure_counts if failure_counts is not None else {}
    pending = journal.list_pending(journal_dir)[:batch_limit]
    published = 0
    for index, entry in enumerate(pending):
        if _shutdown:
            break
        if emitter.publish(entry.record):
            journal.ack(entry)
            counts.pop(entry.path.name, None)
            published += 1
            continue

        key = entry.path.name
        counts[key] = counts.get(key, 0) + 1
        failures = counts[key]

        # Only the HEAD of this cycle's batch is ever a dead-letter candidate.
        # A record further back has not been given the chance to fail on its
        # own merits -- it has only been waiting -- so its count means nothing.
        if index == 0 and failures >= quarantine_after:
            probe = _broker_answers_behind_the_head(pending, emitter)
            if probe is not None:
                journal.ack(probe)
                counts.pop(probe.path.name, None)
                published += 1
                if (
                    quarantine_record(
                        journal_dir, entry, failures=failures, overtaken_by=probe
                    )
                    is not None
                ):
                    counts.pop(key, None)
                    # Re-list rather than continuing over a stale `pending`:
                    # two entries left it just now, and the next cycle is
                    # milliseconds away.
                    return published, max(0, len(pending) - published - 1)
            else:
                logger.warning(
                    "head record %s has failed %d times, but the record behind "
                    "it cannot publish either; the broker is unreachable, so "
                    "nothing is being dead-lettered",
                    entry.record.event_id,
                    failures,
                )
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
    # Owned by the loop, not by drain_once: a record's failures only mean
    # anything across cycles, and a per-call map would reset every 30 seconds
    # and never reach the threshold (OMN-19074).
    failure_counts: dict[str, int] = {}
    # Read once per process: the installed registry cannot change under a
    # running drainer, and a restart is what picks up a new one.
    publishable = publishable_event_types()

    def _record_cycle() -> None:
        try:
            health.write_status(
                status_path,
                health.ModelDrainerStatus(
                    last_cycle_at=time.time(),
                    last_publish_at=last_publish_at,
                    published_total=published_total,
                    pid=os.getpid(),
                    publishable_event_types=publishable,
                ),
            )
        except OSError as exc:  # pragma: no cover - reported, never fatal
            # A drainer that cannot write its own health file must keep
            # draining: losing the signal is strictly better than losing
            # the telemetry it is reporting on.
            logger.warning("could not write drainer status %s: %s", status_path, exc)

    try:
        while True:
            cycle_started = time.perf_counter()
            published, failed = drain_once(
                journal_dir, emitter, failure_counts=failure_counts
            )
            if published:
                # The cycle time makes the publish rate readable from this log
                # alone (OMN-19518 measured before/after events per second).
                logger.info(
                    "published %d event(s) in %.2fs",
                    published,
                    time.perf_counter() - cycle_started,
                )
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
        emitter.close()
        lock.release()


#: Log bound and retention for the drainer's own log (OMN-19519). The bound is
#: the OMN-8429 hook-log default, so every hook log in the tree shares one
#: number; with three backups the drainer log never exceeds about 200 MB.
DEFAULT_LOG_MAX_MB = 50
DEFAULT_LOG_BACKUPS = 3

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _StdioFollowingRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A size-rotated log file that also carries this process's fd 1 and fd 2.

    WHY. launchd opens StandardErrorPath once and hands the process that file
    as fd 2. Renaming it from outside changes nothing: the drainer keeps
    writing into the renamed inode. So the drainer rotates its own log, and
    at every (re)open points fd 1 and fd 2 at the fresh file, so an uncaught
    exception or a stray write from a library lands beside the log lines
    rather than in a backup that is about to be deleted.
    """

    def __init__(
        self, filename: Path, *, max_bytes: int, backups: int, follow_stdio: bool
    ) -> None:
        self._follow_stdio = follow_stdio
        super().__init__(
            filename, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )

    def _open(self) -> Any:
        stream = super()._open()
        if self._follow_stdio:
            for handle in (sys.stdout, sys.stderr):
                try:
                    handle.flush()
                except (OSError, ValueError):
                    pass
            os.dup2(stream.fileno(), 1)
            os.dup2(stream.fileno(), 2)
        return stream


def _regular_file_behind_fd(fd: int) -> Path | None:
    """The path of the regular file open on ``fd``, or ``None`` (tty, pipe, ...)."""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
    except OSError:
        return None
    get_path = getattr(fcntl, "F_GETPATH", None)
    if get_path is not None:  # macOS, where launchd runs the drainer
        try:
            raw = fcntl.fcntl(fd, get_path, b"\0" * 1024)
        except OSError:
            return None
        return Path(raw.split(b"\0", 1)[0].decode())
    try:
        return Path(f"/proc/self/fd/{fd}").readlink()
    except OSError:
        return None


def configure_logging(
    level: str, *, log_file: Path | None, max_bytes: int, backups: int
) -> Path | None:
    """Configure the drainer's logging. Returns the rotated log path, or ``None``.

    With ``log_file`` given, that file is rotated. Otherwise, when stderr is a
    regular file (launchd's StandardErrorPath), that file is rotated and this
    process's stdio follows it across rollovers. A terminal or a pipe on
    stderr gets plain stderr logging, as before.
    """
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    stderr_file = _regular_file_behind_fd(2)
    target = log_file if log_file is not None else stderr_file
    if target is None:
        logging.basicConfig(level=resolved_level, format=_LOG_FORMAT)
        return None
    follow = stderr_file is not None and os.path.realpath(
        stderr_file
    ) == os.path.realpath(target)
    handler = _StdioFollowingRotatingFileHandler(
        target, max_bytes=max_bytes, backups=backups, follow_stdio=follow
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(resolved_level)
    return target


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
    parser.add_argument(
        "--log-file",
        default=None,
        help=(
            "Log to this file with size rotation. Default: when stderr is a "
            "regular file (the launchd StandardErrorPath), rotate that file."
        ),
    )
    parser.add_argument(
        "--log-max-mb",
        type=int,
        default=DEFAULT_LOG_MAX_MB,
        help="Rotate the log when it reaches this many MB (OMN-19519).",
    )
    parser.add_argument(
        "--log-backups",
        type=int,
        default=DEFAULT_LOG_BACKUPS,
        help="Rotated log files kept; older ones are deleted (OMN-19519).",
    )
    args = parser.parse_args(argv)

    configure_logging(
        args.log_level,
        log_file=Path(args.log_file) if args.log_file else None,
        max_bytes=max(1, args.log_max_mb) * 1024 * 1024,
        backups=max(1, args.log_backups),
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
