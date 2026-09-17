# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-10117, as narrowed by the OMN-18471 retirement.

omniclaude#2214 removed ``start_emit_daemon_if_needed`` and its socket/pid
plumbing from ``session-start.sh``, and ``_try_restart_emit_daemon`` from
``common.sh``: the daemon socket had not existed since 2026-06-08, so the
launcher was session-start latency spent on a socket nobody wrote to. The
assertions that session-start.sh and common.sh LAUNCH the daemon were left
behind by that change and are deleted here. What survives is what the
retirement did not touch: the event registry, the ``ONEX_EMIT_EVENT_REGISTRY``
export, the stop path in ``session-end.sh``, and the negative assertions that
no launcher may reach for the legacy publisher or the deprecated CLI flags.
"""

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SESSION_START = REPO_ROOT / "plugins/onex/hooks/scripts/session-start.sh"
SESSION_END = REPO_ROOT / "plugins/onex/hooks/scripts/session-end.sh"
COMMON = REPO_ROOT / "plugins/onex/hooks/scripts/common.sh"
EVENT_REGISTRY_PATH = REPO_ROOT / "plugins/onex/lib/event_registry/omniclaude.yaml"


def _known_transforms() -> set[str]:
    """The daemon transform names this repo knows, read from the one map that owns them.

    OMN-17201: this was a hardcoded literal, and it went stale the moment
    OMN-17209 added ``redact_capture`` -- so the gate that was supposed to
    catch an unrecognised transform in the deployed registry instead blocked
    the recognised one from being declared there. The generator's
    ``TRANSFORM_NAME_TO_CALLABLE`` is the single place the daemon's names are
    mapped to this repo's callables; deriving from it means adding a transform
    is one edit, not two.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    from generate_event_registry import (  # noqa: PLC0415
        TRANSFORM_NAME_TO_CALLABLE,
    )

    return set(TRANSFORM_NAME_TO_CALLABLE)


def test_launcher_does_not_invoke_omniclaude_publisher() -> None:
    """No legacy emit-daemon invocation may return to session-start.sh.

    OMN-18471 retired the launcher entirely, so the positive half of this test
    (assert the omnimarket invocation is present, then read its arguments) was
    deleted with it. The negative assertions stand on their own and are the
    half worth keeping: whatever session-start.sh grows next, it must not be
    the legacy publisher or the removed omnibase_infra fallback.
    """
    legacy_module = "omniclaude" + ".publisher"
    text = SESSION_START.read_text()
    assert f"-m {legacy_module} start" not in text, (
        f"session-start.sh must NOT invoke -m {legacy_module} start (use omnimarket node)"
    )
    assert "omnibase_infra.runtime.emit_daemon.cli start" not in text, (
        "session-start.sh must NOT keep the removed omnibase_infra emit-daemon fallback"
    )


def test_launcher_drops_secondary_kafka_servers() -> None:
    text = SESSION_START.read_text()
    assert "--secondary-kafka-servers" not in text, (
        "session-start.sh must NOT pass --secondary-kafka-servers "
        "(omnimarket node does not support it; secondary bus is not active — OMN-10116 decision)"
    )


def test_event_registry_yaml_exists() -> None:
    assert EVENT_REGISTRY_PATH.exists(), (
        f"Event registry YAML must exist at {EVENT_REGISTRY_PATH} "
        "(required by omnimarket runner --event-registry)"
    )


def test_event_registry_yaml_is_valid() -> None:
    assert EVENT_REGISTRY_PATH.exists(), (
        "Event registry YAML missing — run test_event_registry_yaml_exists first"
    )
    raw = yaml.safe_load(EVENT_REGISTRY_PATH.read_text())
    assert isinstance(raw, dict), "Event registry must be a YAML dict"
    assert "events" in raw, "Event registry must have top-level 'events' key"
    events = raw["events"]
    assert isinstance(events, dict), "'events' value must be a dict"
    assert len(events) > 0, "Event registry must have at least one event registration"


def test_event_registry_transforms_are_known() -> None:
    if not EVENT_REGISTRY_PATH.exists():
        return
    raw = yaml.safe_load(EVENT_REGISTRY_PATH.read_text())
    events = raw.get("events", {})
    for event_type, event_def in events.items():
        if not isinstance(event_def, dict):
            continue
        for rule in event_def.get("fan_out", []):
            transform = rule.get("transform")
            known = _known_transforms()
            if transform and transform not in known:
                raise AssertionError(
                    f"Unknown transform '{transform}' for event '{event_type}'. "
                    f"Must be one of: {sorted(known)}"
                )


def test_event_registry_core_topics_registered() -> None:
    """Verify that the most critical omniclaude event types are registered."""
    if not EVENT_REGISTRY_PATH.exists():
        return
    raw = yaml.safe_load(EVENT_REGISTRY_PATH.read_text())
    events = raw.get("events", {})
    required = [
        "session.started",
        "session.ended",
        "prompt.submitted",
        "tool.executed",
    ]
    missing = [e for e in required if e not in events]
    assert not missing, f"Core event types missing from registry: {missing}"


def test_common_exports_onex_emit_event_registry() -> None:
    """common.sh must declare ONEX_EMIT_EVENT_REGISTRY default."""
    text = COMMON.read_text()
    assert "ONEX_EMIT_EVENT_REGISTRY" in text, (
        "common.sh must declare ONEX_EMIT_EVENT_REGISTRY env var "
        "so all launchers and consumers reference the single event registry path"
    )


def test_session_end_stop_path_uses_omnimarket_node() -> None:
    legacy_module = "omniclaude" + ".publisher"
    text = SESSION_END.read_text()
    assert (
        'env -u PYTHONPATH "$BREW_PY" -m omnimarket.nodes.node_emit_daemon stop' in text
    )
    assert "--pid-path" in text
    assert f"-m {legacy_module} stop" not in text
    assert "omnibase_infra.runtime.emit_daemon.cli stop" not in text
