#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate/verify omniclaude's EVENT_REGISTRY from omnimarket's topics.yaml (OMN-15967).

omnimarket's ``topics.yaml`` (``src/omnimarket/nodes/node_emit_daemon/registries/
topics.yaml``) is the single canonical source of truth for the Claude Code event
registry — it is what the emit daemon actually loads at runtime (OMN-13146).
omniclaude's ``EVENT_REGISTRY`` (``src/omniclaude/hooks/event_registry.py``) is a
**generated projection** of that file, not a hand-maintained second copy: this
script is the one and only place event/fan-out/partition-key/required-field data
is derived from the daemon registry into the committed Python literal.

Two intentional, documented exclusions keep the projection from being a strict
mirror (OMN-15967 acceptance criterion: "the 63-vs-62 delta is resolved or
explicitly documented as an intentional daemon-internal exception"):

1. ``DAEMON_INTERNAL_EVENT_TYPES`` — event types the daemon handles/emits
   entirely internally (health probes, delegation-request bookkeeping). No hook
   client ever emits these, so there is no client-side registration to project.
2. ``diagnostic.daemon.health`` fans out, on the daemon side, to one extra topic
   (``onex.evt.diagnostic.daemon-health.v1``) that does not follow the ONEX
   canonical ``onex.{kind}.{producer}.{event-name}.v{n}`` format and therefore
   has no ``TopicBase`` member to project onto. This is the pre-existing,
   documented daemon-widens-here exception already carried by
   ``tests/hooks/test_registry_consistency.py``.

Usage:
    # Regenerate the EVENT_REGISTRY literal in event_registry.py from a fresh
    # omnimarket checkout, then run ruff format/check --fix over it:
    python scripts/validation/generate_event_registry.py \\
        --daemon-registry /path/to/omnimarket/src/omnimarket/nodes/node_emit_daemon/registries/topics.yaml \\
        --write

    # CI / pre-commit drift gate: fail if the committed EVENT_REGISTRY has
    # drifted from the daemon registry (no file is written):
    python scripts/validation/generate_event_registry.py \\
        --daemon-registry /path/to/topics.yaml --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENT_REGISTRY_MODULE = REPO_ROOT / "src" / "omniclaude" / "hooks" / "event_registry.py"

# Event types the emit daemon owns entirely internally. No hook client ever
# constructs or emits these, so omniclaude's client-side EVENT_REGISTRY
# intentionally does not carry a registration for them. Keep this set in sync
# with the module docstring in event_registry.py and the OMN-15967 ticket body.
DAEMON_INTERNAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "daemon.health.probe",
        "delegation.request",
    }
)

# Daemon-side fan-out topics that do not resolve to a TopicBase member because
# they do not follow the ONEX canonical topic format. The daemon is the
# runtime routing authority and is allowed to fan out wider than the hook-side
# registration; omniclaude cannot represent a non-canonical topic in
# TopicBase without failing the topic-naming lint, so these are dropped from
# the generated projection rather than silently ignored.
NON_CANONICAL_DAEMON_TOPICS: frozenset[str] = frozenset(
    {
        "onex.evt.diagnostic.daemon-health.v1",
    }
)

# Daemon YAML transform names -> the Python callable name used by
# event_registry.py's FanOutRule.transform. "passthrough" (or an absent
# transform key) maps to None (the FanOutRule default).
TRANSFORM_NAME_TO_CALLABLE: dict[str, str | None] = {
    "passthrough": None,
    "strip_prompt": "transform_for_observability",
    "strip_body": "_transform_chat_broadcast",
    "redact_capture": "redact_capture",
}

# OMN-17959: `redact_capture` resolves a posture that lives in a YAML contract,
# and omnimarket owns that contract the same way it owns topics.yaml. omniclaude
# carries a mirror (the pinned `omnimarket` dependency predates the contract, and
# the emit seam must stay off the Pydantic import chain), so the mirror needs the
# same mechanical drift gate the registry itself has -- otherwise the two halves
# of one posture could silently diverge, which is the exact failure class this
# ticket exists to close.
#
# The comparison is of the RESOLVED POSTURE, not of bytes. A byte gate was tried
# first and is wrong here: this repo's own mandated pre-commit hooks rewrite the
# file on arrival (the SPDX stamper normalises the copyright year and moves the
# YAML document marker; detect-secrets appends an allowlist pragma to the line
# quoting the 2026-08-19 incident URL). Those are header and prose edits that
# cannot change what is captured. Gating on bytes would therefore fail every
# build for a reason unrelated to disclosure, and the pressure would be to
# weaken the gate. Gating on the parsed contract -- field classes, output
# classes, command/content fields, secret patterns, governed topics, derived
# fields and the state field -- fails if and only if the POSTURE differs, which
# is the thing that must not drift. Prose `reason` text is deliberately outside
# the comparison: it is documentation, and the resolver does not store it.
CAPTURE_REDACTION_TRANSFORM = "redact_capture"
VENDORED_CAPTURE_CONTRACT = (
    REPO_ROOT / "src" / "omniclaude" / "hooks" / "contracts" / "capture_redaction.yaml"
)
# Path of the owning contract RELATIVE TO the daemon registry's `nodes/` dir,
# so it is resolved from whatever omnimarket checkout the caller passed rather
# than from a second hardcoded location.
OWNING_CAPTURE_CONTRACT_RELPATH = Path(
    "node_event_emit_effect/contracts/capture_redaction.yaml"
)


def load_daemon_events(daemon_registry_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(daemon_registry_path.read_text(encoding="utf-8"))
    events = raw.get("events") if isinstance(raw, dict) else None
    if not isinstance(events, dict):
        raise ValueError(
            f"{daemon_registry_path} must contain a top-level 'events' mapping"
        )
    result: dict[str, Any] = events
    return result


def project_registration(event_type: str, event_def: dict[str, Any]) -> dict[str, Any]:
    """Project one daemon event definition into the generated-registry shape.

    Returns a plain-data dict (not the dataclass) so this module has no
    dependency on omniclaude's package internals — only ``event_registry.py``
    itself constructs ``EventRegistration``/``FanOutRule`` instances.
    """
    fan_out: list[dict[str, Any]] = []
    for rule in event_def.get("fan_out", []):
        topic = rule["topic"]
        if topic in NON_CANONICAL_DAEMON_TOPICS:
            continue
        transform_name = rule.get("transform", "passthrough")
        if transform_name not in TRANSFORM_NAME_TO_CALLABLE:
            raise ValueError(
                f"{event_type}: unknown daemon transform '{transform_name}' — add it to "
                "TRANSFORM_NAME_TO_CALLABLE (and event_registry.py) before regenerating"
            )
        fan_out.append(
            {
                "topic": topic,
                "transform": TRANSFORM_NAME_TO_CALLABLE[transform_name],
                "description": rule.get("description", ""),
            }
        )
    return {
        "event_type": event_type,
        "fan_out": fan_out,
        "partition_key_field": event_def.get("partition_key_field"),
        "required_fields": list(event_def.get("required_fields", []) or []),
    }


def build_projected_registry(
    daemon_events: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build the full generated-registry projection from daemon event defs."""
    return {
        event_type: project_registration(event_type, event_def)
        for event_type, event_def in daemon_events.items()
        if event_type not in DAEMON_INTERNAL_EVENT_TYPES
    }


def load_committed_registry_as_data() -> dict[str, dict[str, Any]]:
    """Import the committed EVENT_REGISTRY and reduce it to the same plain-data
    shape ``build_projected_registry`` produces, for structural comparison."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from omniclaude.hooks.capture_redaction import redact_capture  # noqa: PLC0415
    from omniclaude.hooks.event_registry import (  # noqa: PLC0415
        EVENT_REGISTRY,
        _transform_chat_broadcast,
        transform_for_observability,
    )

    def _transform_name(transform: Any) -> str | None:
        if transform is None:
            return None
        if transform is transform_for_observability:
            return "transform_for_observability"
        if transform is _transform_chat_broadcast:
            return "_transform_chat_broadcast"
        if transform is redact_capture:
            return "redact_capture"
        return f"UNKNOWN:{transform!r}"

    data: dict[str, dict[str, Any]] = {}
    for event_type, reg in EVENT_REGISTRY.items():
        fan_out = [
            {
                "topic": str(rule.topic_base.value),
                "transform": _transform_name(rule.transform),
                "description": rule.description,
            }
            for rule in reg.fan_out
        ]
        data[event_type] = {
            "event_type": event_type,
            "fan_out": fan_out,
            "partition_key_field": reg.partition_key_field,
            "required_fields": list(reg.required_fields),
        }
    return data


def _resolved_posture(contract_path: Path) -> dict[str, Any]:
    """Reduce a capture-redaction contract to its comparable posture.

    Uses omniclaude's own resolver, so anything the resolver refuses to load is
    a refusal here too rather than a silently-empty comparison.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from omniclaude.hooks.capture_redaction import load_contract  # noqa: PLC0415

    contract = load_contract(contract_path)
    return {
        "default_field_class": contract.default_field_class.value,
        "output_classes": [
            (oc.name, sorted(oc.tool_names), oc.command_pattern.pattern)
            for oc in contract.output_classes
        ],
        "command_fields": list(contract.command_fields),
        "tool_name_field": contract.tool_name_field,
        "content_fields": sorted(contract.content_fields),
        "secret_patterns": [
            (name, pattern.pattern) for name, pattern in contract.secret_patterns
        ],
        "topics": {
            topic: {
                "fields": {f: c.value for f, c in policy.fields.items()},
                "derived": [(d.target, d.source, d.derive) for d in policy.derived],
            }
            for topic, policy in contract.topics.items()
        },
        "redaction_state_field": contract.redaction_state_field,
    }


def check_vendored_capture_contract(
    generated: dict[str, dict[str, Any]], daemon_registry_path: Path
) -> list[str]:
    """Hold omniclaude's mirrored redaction contract to omnimarket's owning copy.

    Returns a list of violations; empty means either the transform is not in
    use, or the mirror is byte-identical to the owner.

    Fail-closed in both directions: a projection that names the transform with
    no resolvable owning contract is a violation, not a pass. An unresolvable
    owner means the check silently verified nothing, which reads exactly like
    a clean result.
    """
    in_use = any(
        rule["transform"] == CAPTURE_REDACTION_TRANSFORM
        for registration in generated.values()
        for rule in registration["fan_out"]
    )
    if not in_use:
        return []

    violations: list[str] = []
    if not VENDORED_CAPTURE_CONTRACT.is_file():
        violations.append(
            f"{CAPTURE_REDACTION_TRANSFORM} is declared by the daemon registry but "
            f"the mirrored contract is missing at "
            f"{VENDORED_CAPTURE_CONTRACT.relative_to(REPO_ROOT)}"
        )
        return violations

    # nodes/<node>/registries/topics.yaml -> nodes/
    owner = daemon_registry_path.resolve().parents[2] / OWNING_CAPTURE_CONTRACT_RELPATH
    if not owner.is_file():
        violations.append(
            f"cannot resolve omnimarket's owning capture-redaction contract at "
            f"{owner} — refusing to report the mirror as verified against nothing"
        )
        return violations

    try:
        mirrored = _resolved_posture(VENDORED_CAPTURE_CONTRACT)
        owned = _resolved_posture(owner)
    except Exception as exc:  # noqa: BLE001 - any resolution failure is a refusal
        violations.append(
            f"cannot resolve the capture-redaction posture for comparison: {exc}"
        )
        return violations

    if mirrored != owned:
        differing = sorted(
            key for key in owned if mirrored.get(key) != owned.get(key)
        ) or ["<key set>"]
        violations.append(
            f"{VENDORED_CAPTURE_CONTRACT.relative_to(REPO_ROOT)} has drifted from "
            f"omnimarket's owning copy at {owner}: {differing}. omnimarket owns "
            f"this contract; copy the posture over rather than editing the mirror."
        )
    return violations


def diff_registries(
    generated: dict[str, dict[str, Any]], committed: dict[str, dict[str, Any]]
) -> list[str]:
    violations: list[str] = []

    missing_from_committed = sorted(set(generated) - set(committed))
    if missing_from_committed:
        violations.append(
            "Event types in the daemon projection but missing from the committed "
            f"EVENT_REGISTRY: {missing_from_committed}"
        )
    extra_in_committed = sorted(set(committed) - set(generated))
    if extra_in_committed:
        violations.append(
            "Event types in the committed EVENT_REGISTRY but not projected from the "
            f"daemon registry (stale / hand-added?): {extra_in_committed}"
        )

    for event_type in sorted(set(generated) & set(committed)):
        gen = generated[event_type]
        com = committed[event_type]
        if gen["partition_key_field"] != com["partition_key_field"]:
            violations.append(
                f"{event_type}: partition_key_field generated={gen['partition_key_field']!r} "
                f"committed={com['partition_key_field']!r}"
            )
        if set(gen["required_fields"]) != set(com["required_fields"]):
            violations.append(
                f"{event_type}: required_fields generated={sorted(gen['required_fields'])} "
                f"committed={sorted(com['required_fields'])}"
            )
        gen_topics = {(r["topic"], r["transform"]) for r in gen["fan_out"]}
        com_topics = {(r["topic"], r["transform"]) for r in com["fan_out"]}
        if gen_topics != com_topics:
            violations.append(
                f"{event_type}: fan_out (topic, transform) generated={sorted(gen_topics)} "
                f"committed={sorted(com_topics)}"
            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon-registry", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed EVENT_REGISTRY has drifted from the daemon registry",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help=(
            "Print the regenerated EVENT_REGISTRY literal to stdout for manual "
            f"splicing into {EVENT_REGISTRY_MODULE.relative_to(REPO_ROOT)} "
            "(this script never writes source files directly)"
        ),
    )
    args = parser.parse_args(argv)

    daemon_events = load_daemon_events(args.daemon_registry)
    generated = build_projected_registry(daemon_events)

    contract_violations = check_vendored_capture_contract(
        generated, args.daemon_registry
    )
    if contract_violations:
        for violation in contract_violations:
            print(f"- {violation}")
        return 1

    if args.write:
        import json  # noqa: PLC0415

        print(json.dumps(generated, indent=2, sort_keys=True))
        return 0

    committed = load_committed_registry_as_data()
    violations = diff_registries(generated, committed)
    if violations:
        print(
            f"Event registry drift: committed EVENT_REGISTRY does not match the "
            f"projection of {args.daemon_registry} ({len(violations)} violation(s))"
        )
        for v in violations:
            print(f"- {v}")
        print(
            "\nRegenerate with --write and splice the result into "
            f"{EVENT_REGISTRY_MODULE.relative_to(REPO_ROOT)}, or update "
            "DAEMON_INTERNAL_EVENT_TYPES / NON_CANONICAL_DAEMON_TOPICS in this script "
            "if the divergence is an intentional daemon-internal exception."
        )
        return 1

    print(
        f"Event registry projection check passed: {len(generated)} event types "
        f"match {args.daemon_registry}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
