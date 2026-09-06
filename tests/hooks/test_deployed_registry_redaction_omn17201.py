# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-17201: the registry the DEPLOYED emit daemon loads must name the redaction transform.

There are three copies of the Claude Code event registry, and only two of them
were ever bound to each other:

1. ``omnimarket`` ``node_emit_daemon/registries/topics.yaml`` -- canonical
   (OMN-13146). It declares ``transform: redact_capture`` on the two governed
   hook fan-out rules (OMN-17209).
2. ``src/omniclaude/hooks/event_registry.py`` -- a generated projection of (1),
   held to it by ``scripts/validation/generate_event_registry.py --check`` and
   the ``event_registry_drift`` gate. It carries ``redact_capture`` (OMN-17959).
3. ``plugins/onex/lib/event_registry/omniclaude.yaml`` -- **the file the
   running daemon actually reads**, via ``ONEX_EMIT_EVENT_REGISTRY``
   (``plugins/onex/hooks/scripts/common.sh``) passed as ``--event-registry``
   (``session-start.sh``, and the respawn path in ``common.sh``). Nothing bound
   it to (1), and it had drifted: ``strip_prompt`` on prompt-submitted and no
   transform at all on tool-executed.

So the posture existed in two files that do not run and was absent from the one
that does. The deployed daemon resolves ``redact_capture`` perfectly well --
``omnimarket.nodes.node_emit_daemon.event_registry.TOPIC_SCOPED_TRANSFORM_REGISTRY``
contains it -- it was simply never asked for it, so no hook record was ever
stamped, and the OMN-16979 egress gate dropped 100% of both governed topics at
the trust boundary.

WHERE THE REDACTION BELONGS, cited rather than chosen here. ``omnibase_infra``
``node_bus_forwarder_effect/contract.yaml`` and
``models/model_gateway_egress_redaction.py`` both state it: "The redaction
itself is produced UPSTREAM, at omnimarket's emit seam ... That is the only
place that knows tool semantics ... This node cannot re-derive that judgement
and deliberately does not try." The gate owns refusing to cross an unstamped
record; the emit seam owns producing the stamp. This file tests the seam's
deployed wiring, and it never widens ``governed_topics`` or
``admitted_states``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.hooks.capture_redaction import (
    EnumRedactionState,
    redact_capture,
)
from omniclaude.hooks.topics import TopicBase

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYED_REGISTRY = (
    REPO_ROOT / "plugins" / "onex" / "lib" / "event_registry" / "omniclaude.yaml"
)

PROMPT_TOPIC = TopicBase.PROMPT_SUBMITTED.value
TOOL_TOPIC = TopicBase.TOOL_EXECUTED.value

#: event type -> the governed fan-out topic on it.
GOVERNED_RULES: dict[str, str] = {
    "prompt.submitted": PROMPT_TOPIC,
    "tool.executed": TOOL_TOPIC,
}

# The OMN-16979 egress admission policy, mirrored from omnibase_infra
# ``node_bus_forwarder_effect/contract.yaml``
# (``config.gateway_forwarder.egress_redaction``). Mirrored, not imported:
# this is a wire-level fact about another repo's declared policy, and a test
# that imported it could not fail when the two drift.
GATEWAY_STATE_FIELD = "redaction_state"
GATEWAY_ADMITTED_STATES = frozenset({"redacted", "restricted", "secret_detected"})

# ---------------------------------------------------------------------------
# The captured record
# ---------------------------------------------------------------------------
# Verbatim from the ``omnibase_infra`` OMN-17981 fixture, read read-only off
# the stability lane on 2026-09-06 with
# ``rpk topic consume onex.evt.omniclaude.tool-executed.v1 -p 0 -o 34710 -n 1``.
# The only substitution there and here is the live agent-session UUID, replaced
# by a fixed placeholder of identical form. Note what it does NOT carry: any
# ``redaction_state`` at all. That absence is the drop.
_SESSION_UUID = "00000000-0000-4000-8000-000000000001"
CAPTURED_TOOL_EXECUTED: dict[str, Any] = json.loads(
    '{"duration_ms": 361, "hook_source": "post_tool_use", "interrupted": false, '
    f'"session_id": "{_SESSION_UUID}", '
    '"tool_name": "Bash", "working_directory": "omni_home", '
    f'"correlation_id": "{_SESSION_UUID}", '
    '"causation_id": null, '
    '"emitted_at": "2026-09-06T07:47:38.731279+00:00", '
    f'"entity_id": "{_SESSION_UUID}", '
    '"schema_version": "1.0.0"}'
)


def _deployed_events() -> dict[str, Any]:
    raw = yaml.safe_load(DEPLOYED_REGISTRY.read_text(encoding="utf-8"))
    events = raw.get("events")
    assert isinstance(events, dict), "deployed registry has no `events` mapping"
    return events


def _deployed_transform(event_type: str, topic: str) -> str | None:
    """The transform name the deployed registry declares for one fan-out rule."""
    event = _deployed_events()[event_type]
    for rule in event["fan_out"]:
        if rule["topic"] == topic:
            transform = rule.get("transform")
            assert transform is None or isinstance(transform, str)
            return transform
    raise AssertionError(f"{event_type} declares no fan-out rule for {topic}")


def _emit_as_deployed(
    payload: dict[str, Any], *, event_type: str, topic: str
) -> dict[str, Any]:
    """What the running daemon publishes for this rule, per the deployed registry.

    Only ``redact_capture`` stamps a state; every other declared transform (and
    an absent one) leaves the payload without one, which is precisely why the
    boundary drops it. The mapping is deliberately exhaustive rather than a
    ``.get`` with a default -- an unrecognised name here is a drift signal, not
    something to pass through.
    """
    name = _deployed_transform(event_type, topic)
    if name == "redact_capture":
        return redact_capture(dict(payload), topic=topic)
    if name in (None, "passthrough", "strip_prompt", "strip_body"):
        return dict(payload)
    raise AssertionError(f"unrecognised transform {name!r} on {event_type} -> {topic}")


def _gateway_admits(payload: dict[str, Any]) -> bool:
    """``ModelGatewayEgressRedaction.admits``, mirrored exactly."""
    state = payload.get(GATEWAY_STATE_FIELD)
    if not isinstance(state, str):
        return False
    return state in GATEWAY_ADMITTED_STATES


# ---------------------------------------------------------------------------
# The deployed registry declares the transform
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(("event_type", "topic"), sorted(GOVERNED_RULES.items()))
def test_the_deployed_registry_declares_redact_capture(
    event_type: str, topic: str
) -> None:
    """The file the daemon loads, not the two that only describe it."""
    assert _deployed_transform(event_type, topic) == "redact_capture", (
        f"{DEPLOYED_REGISTRY.name} is what --event-registry points the daemon at; "
        "a governed topic whose rule does not name the transform is published "
        "unstamped and dropped at the trust boundary"
    )


@pytest.mark.unit
def test_the_captured_record_is_unstamped_on_the_wire() -> None:
    """Sanity, and the reason this ticket exists: nothing upstream stamped it."""
    assert GATEWAY_STATE_FIELD not in CAPTURED_TOOL_EXECUTED
    assert not _gateway_admits(CAPTURED_TOOL_EXECUTED)


@pytest.mark.unit
def test_the_captured_record_crosses_once_the_deployed_registry_is_wired() -> None:
    """RED before the wiring: no transform runs, so no state, so a DROP."""
    out = _emit_as_deployed(
        CAPTURED_TOOL_EXECUTED, event_type="tool.executed", topic=TOOL_TOPIC
    )
    assert out[GATEWAY_STATE_FIELD] != EnumRedactionState.RAW.value
    assert _gateway_admits(out)


@pytest.mark.unit
def test_the_prompt_body_still_never_crosses() -> None:
    """The widening must not become a disclosure: OMN-16019's surface stays closed."""
    out = _emit_as_deployed(
        {
            "session_id": "s-1",
            "hook_source": "user_prompt_submit",
            "working_directory": "omni_home",
            "prompt": "the full prompt body",
            "prompt_preview": "the full prompt bod",
        },
        event_type="prompt.submitted",
        topic=PROMPT_TOPIC,
    )
    rendered = json.dumps(out)
    assert "the full prompt body" not in rendered
    assert "prompt" not in out
    assert out["prompt_length"] == len("the full prompt body")
    assert _gateway_admits(out)


@pytest.mark.unit
def test_content_fields_are_actually_redacted_not_merely_stamped() -> None:
    """A stamp on unredacted content would be worse than no stamp at all."""
    out = _emit_as_deployed(
        {
            "session_id": "s-1",
            "tool_name": "Bash",
            "command": "valkey-cli -h omninode-valkey config get requirepass",
            "tool_output": '1) "requirepass"\n2) "S3cr3t-Valkey-Pw-2026"',
        },
        event_type="tool.executed",
        topic=TOOL_TOPIC,
    )
    rendered = json.dumps(out)
    assert "S3cr3t-Valkey-Pw-2026" not in rendered
    assert "requirepass" not in rendered
    assert str(out["command"]).startswith("sha256:")
    assert str(out["tool_output"]).startswith("sha256:")
    assert _gateway_admits(out)


# ---------------------------------------------------------------------------
# The third copy cannot drift again
# ---------------------------------------------------------------------------


def _omnimarket_root() -> Path | None:
    """Resolve a canonical omnimarket checkout, or None.

    CI checks out omnimarket@dev at ``_registry/omnimarket``; locally the
    canonical clone sits beside this repo. Both are tried; neither is
    fabricated with a default path (Operating Rule 8).
    """
    candidates = [
        REPO_ROOT / "_registry" / "omnimarket",
        REPO_ROOT.parent / "omnimarket",
    ]
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        candidates.append(Path(omni_home) / "omnimarket")
    for candidate in candidates:
        if (candidate / "src" / "omnimarket").is_dir():
            return candidate
    return None


@pytest.mark.unit
def test_the_deployed_registry_agrees_with_the_canonical_one_on_every_transform() -> (
    None
):
    """The binding that did not exist, which is why this drifted unnoticed.

    Compared over every fan-out rule the two files share, in both directions,
    so a transform added or removed on either side is a failure here rather
    than a silent difference between the file that is reviewed and the file
    that runs.
    """
    root = _omnimarket_root()
    if root is None:
        pytest.skip("no canonical omnimarket checkout resolvable")
    canonical_path = (
        root / "src/omnimarket/nodes/node_emit_daemon/registries/topics.yaml"
    )
    canonical = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))["events"]
    deployed = _deployed_events()

    def _transforms(events: dict[str, Any]) -> dict[tuple[str, str], str]:
        # An absent transform and an explicit ``passthrough`` are the same
        # instruction to the daemon -- its loader reads
        # ``if transform_name and transform_name != "passthrough"`` -- so they
        # are normalised here rather than reported as drift.
        return {
            (event_type, rule["topic"]): rule.get("transform") or "passthrough"
            for event_type, event in events.items()
            if isinstance(event, dict)
            for rule in event.get("fan_out", [])
        }

    canonical_transforms = _transforms(canonical)
    deployed_transforms = _transforms(deployed)
    shared = set(canonical_transforms) & set(deployed_transforms)
    assert shared, "positive control: the two registries share no fan-out rule"
    mismatched = {
        rule: (canonical_transforms[rule], deployed_transforms[rule])
        for rule in sorted(shared)
        if canonical_transforms[rule] != deployed_transforms[rule]
    }
    assert not mismatched, (
        "deployed registry disagrees with the canonical one (canonical, deployed): "
        f"{mismatched}"
    )
