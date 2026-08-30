#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook-edge bus lane resolution from the declared contract [OMN-17204].

The hook edge used to have no declared lane. Which .201 broker a
``*_bus_mirror.sh`` published to was decided, per invocation, by shell
sourcing order: ``common.sh`` sources ``~/.omnibase/.env`` under ``set -a``
*after* the Claude session env is in place, so that file beat
``~/.claude/settings.json``'s own ``KAFKA_BOOTSTRAP_SERVERS`` export — while
``omnibase_infra/config/overlays/mac-dev.yaml``, which the emit node's own
``contract.yaml`` names as the authority, carried a third value matching
neither. Three separate wrong conclusions were drawn from that one undeclared
fact (OMN-16162, OMN-16996, ``beta/GOAL.md`` row 0).

This module reads ``plugins/onex/hooks/contracts/hook_edge_lane.yaml`` — the
single authority — and exposes:

* :func:`load_contract` — parse and structurally validate the declaration.
* :func:`resolve_bootstrap_servers` — the publisher's answer.
* :func:`audit_surfaces` — which demoted host surfaces disagree, so a
  disagreement is *legible* rather than *decisive* (AC3).

Deliberately dependency-light and side-effect-free: the shell resolver
(``scripts/hook_edge_lane.sh``) does not call into Python at hook time at all,
so a broken interpreter can never cost the session a lane. This module is what
the tests and the CI gate read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "HookEdgeLaneContract",
    "LaneEndpoint",
    "SurfaceFinding",
    "audit_surfaces",
    "load_contract",
    "resolve_bootstrap_servers",
    "resolve_governed_topics",
]


class HookEdgeLaneError(ValueError):
    """The declaration is structurally unusable.

    Raised, never swallowed: an unreadable lane declaration must fail the gate
    loudly. The *hook* path never imports this module, so raising here cannot
    break a user's session.
    """


@dataclass(frozen=True)
class LaneEndpoint:
    """One lane's host-side bus endpoint and container network."""

    name: str
    compose_project: str
    network: str
    bootstrap_servers: str


@dataclass(frozen=True)
class HookEdgeLaneContract:
    """The declared hook-edge lane pairing.

    ``lane`` is the single field both sides read. ``bootstrap_servers`` and
    ``relay_required_network`` are *derived* from it, which is why a
    publisher/consumer split cannot be written down in the first place — the
    only way to express one is to make ``relay.required_network`` disagree with
    the lane's network, and that is precisely what the gate rejects.
    """

    path: Path
    lane: str
    known_lanes: dict[str, LaneEndpoint]
    relay_container: str
    relay_required_network: str
    topic_registry: str
    governed_topics: tuple[str, ...]
    non_authoritative_surfaces: tuple[str, ...]

    @property
    def bootstrap_servers(self) -> str:
        return self.known_lanes[self.lane].bootstrap_servers

    @property
    def network(self) -> str:
        return self.known_lanes[self.lane].network


@dataclass(frozen=True)
class SurfaceFinding:
    """What one demoted host surface says, and whether it matches the contract."""

    surface: str
    observed: str | None
    expected: str
    agrees: bool


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    """Fetch a required key, or fail loudly.

    No defaults: a missing field in the one file that settles the lane must
    surface as an error, not as a quietly-chosen fallback. Silent defaults are
    the exact failure mode this ticket exists to retire.
    """
    if key not in mapping:
        raise HookEdgeLaneError(f"{where}: missing required key {key!r}")
    return mapping[key]


def load_contract(path: Path) -> HookEdgeLaneContract:
    """Parse and structurally validate the hook-edge lane declaration."""
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookEdgeLaneError(f"no hook-edge lane contract at {path}") from exc
    if not isinstance(raw, dict):
        raise HookEdgeLaneError(f"{path}: contract must be a mapping")

    where = str(path)
    lanes_raw = _require(raw, "known_lanes", where)
    if not isinstance(lanes_raw, dict) or not lanes_raw:
        raise HookEdgeLaneError(f"{where}: known_lanes must be a non-empty mapping")

    known: dict[str, LaneEndpoint] = {}
    for name, entry in lanes_raw.items():
        if not isinstance(entry, dict):
            raise HookEdgeLaneError(f"{where}: known_lanes.{name} must be a mapping")
        scope = f"{where}: known_lanes.{name}"
        known[str(name)] = LaneEndpoint(
            name=str(name),
            compose_project=str(_require(entry, "compose_project", scope)),
            network=str(_require(entry, "network", scope)),
            bootstrap_servers=str(_require(entry, "bootstrap_servers", scope)),
        )

    lane = str(_require(raw, "lane", where))
    if lane not in known:
        raise HookEdgeLaneError(
            f"{where}: declared lane {lane!r} is not in known_lanes ({sorted(known)})"
        )

    relay = _require(raw, "relay", where)
    if not isinstance(relay, dict):
        raise HookEdgeLaneError(f"{where}: relay must be a mapping")

    governed = _require(raw, "governed_topics", where)
    if not isinstance(governed, list) or not governed:
        raise HookEdgeLaneError(
            f"{where}: governed_topics must be a non-empty list of canonical "
            "topic-registry constant names"
        )

    demoted = _require(raw, "non_authoritative_surfaces", where)
    if not isinstance(demoted, list) or not demoted:
        raise HookEdgeLaneError(
            f"{where}: non_authoritative_surfaces must list the surfaces this "
            "contract demotes — an empty list would mean nothing was actually "
            "taken out of the resolution path"
        )

    return HookEdgeLaneContract(
        path=path,
        lane=lane,
        known_lanes=known,
        relay_container=str(_require(relay, "container", f"{where}: relay")),
        relay_required_network=str(
            _require(relay, "required_network", f"{where}: relay")
        ),
        topic_registry=str(_require(raw, "topic_registry", where)),
        governed_topics=tuple(str(name) for name in governed),
        non_authoritative_surfaces=tuple(str(s) for s in demoted),
    )


def resolve_bootstrap_servers(contract: HookEdgeLaneContract) -> str:
    """The publisher's broker, from the contract and nothing else.

    Note what this function does NOT do: consult the environment. That is the
    whole point — an env var that disagrees is a finding (see
    :func:`audit_surfaces`), never an input.
    """
    return contract.bootstrap_servers


def audit_surfaces(
    contract: HookEdgeLaneContract,
    *,
    surfaces: dict[str, str | None],
) -> tuple[SurfaceFinding, ...]:
    """Report which demoted surfaces disagree with the contract (AC3).

    ``surfaces`` maps a surface label (``~/.omnibase/.env``,
    ``~/.claude/settings.json``, ...) to the broker value it currently sets, or
    ``None`` when it sets none. A surface that sets nothing is not a
    disagreement — silence is compatible with any lane.
    """
    expected = contract.bootstrap_servers
    return tuple(
        SurfaceFinding(
            surface=label,
            observed=observed,
            expected=expected,
            agrees=observed is None or observed == expected,
        )
        for label, observed in sorted(surfaces.items())
    )


def resolve_governed_topics(
    contract: HookEdgeLaneContract, *, repo_root: Path
) -> dict[str, str]:
    """Resolve the contract's governed-topic constants to topic strings.

    The topic string has exactly one home — ``src/omniclaude/hooks/topic_registry.yaml``,
    the file ``TopicBase`` and ``emit_client_wrapper`` already read. This
    contract names registry *constants* so it can never become a second place a
    topic is spelled, and so a rename in the registry surfaces here as a
    resolution failure instead of a stale literal that quietly governs nothing.

    Raises on an unknown constant: a lane policy that silently governs an empty
    topic set is the same class of un-noticed nothing this ticket exists to
    retire.
    """
    import yaml

    registry_path = repo_root / contract.topic_registry
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookEdgeLaneError(
            f"{contract.path}: topic_registry {registry_path} does not exist"
        ) from exc
    entries = (raw or {}).get("topics")
    if not isinstance(entries, list):
        raise HookEdgeLaneError(f"{registry_path}: no 'topics' list")

    by_constant: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        constant = entry.get("topic_base_constant")
        topic = entry.get("topic")
        if isinstance(constant, str) and isinstance(topic, str):
            by_constant[constant] = topic

    resolved: dict[str, str] = {}
    for name in contract.governed_topics:
        if name not in by_constant:
            raise HookEdgeLaneError(
                f"{contract.path}: governed topic constant {name!r} is not in "
                f"{registry_path} — the lane policy would govern a topic that "
                "does not exist"
            )
        resolved[name] = by_constant[name]
    return resolved
