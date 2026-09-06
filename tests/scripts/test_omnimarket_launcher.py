# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-10117: session-start.sh must launch the omnimarket runner."""

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


def test_launcher_invokes_omnimarket_node() -> None:
    legacy_module = "omniclaude" + ".publisher"
    text = SESSION_START.read_text()
    assert "omnimarket.nodes.node_emit_daemon" in text, (
        f"session-start.sh must invoke omnimarket.nodes.node_emit_daemon, not {legacy_module}"
    )
    assert "--kafka-bootstrap-servers" in text, (
        "session-start.sh must use --kafka-bootstrap-servers (omnimarket CLI arg)"
    )
    assert "--event-registry" in text, (
        "session-start.sh must pass --event-registry to the omnimarket daemon"
    )


def test_launcher_does_not_invoke_omniclaude_publisher() -> None:
    legacy_module = "omniclaude" + ".publisher"
    text = SESSION_START.read_text()
    # The old invocation line must be gone
    assert f"-m {legacy_module} start" not in text, (
        f"session-start.sh must NOT invoke -m {legacy_module} start (use omnimarket node)"
    )
    assert "omnibase_infra.runtime.emit_daemon.cli start" not in text, (
        "session-start.sh must NOT keep the removed omnibase_infra emit-daemon fallback"
    )
    # The active daemon launch must not use the deprecated --kafka-servers CLI arg.
    assert "omnimarket.nodes.node_emit_daemon start" in text, (
        "sanity: omnimarket daemon start must be present before checking for arg absence"
    )
    omnimarket_block_start = text.index("omnimarket.nodes.node_emit_daemon start")
    # Find the end of the nohup block (next & after the start invocation)
    omnimarket_block_end = text.index(" &\n", omnimarket_block_start)
    omnimarket_invocation = text[omnimarket_block_start:omnimarket_block_end]
    assert "--kafka-servers " not in omnimarket_invocation, (
        "omnimarket daemon launch must not use deprecated --kafka-servers (use --kafka-bootstrap-servers)"
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


def test_launcher_uses_pid_path_flag() -> None:
    text = SESSION_START.read_text()
    assert "--pid-path" in text, (
        "session-start.sh must pass --pid-path to the omnimarket daemon "
        "(was implicit in the legacy config; must be explicit now)"
    )


def test_launcher_uses_spool_dir_flag() -> None:
    text = SESSION_START.read_text()
    assert "--spool-dir" in text, (
        "session-start.sh must pass --spool-dir to preserve event spool continuity "
        "across daemon restart (OMN-10116 Part 4)"
    )


def test_launcher_uses_log_path_without_appending_stdout_to_log() -> None:
    text = SESSION_START.read_text()
    marker = (
        'nohup env -u PYTHONPATH "$BREW_PY" -m omnimarket.nodes.node_emit_daemon start'
    )
    assert marker in text
    block_start = text.index(marker)
    block_end = text.index(" &\n", block_start)
    invocation = text[block_start:block_end]

    assert "--log-path" in invocation
    assert '>> "${ONEX_STATE_DIR}/hooks/logs/emit-daemon.log"' not in invocation
    assert ">/dev/null 2>&1" in invocation


def test_common_restart_path_uses_omnimarket_node() -> None:
    legacy_module = "omniclaude" + ".publisher"
    text = COMMON.read_text()
    marker = 'env -u PYTHONPATH "$BREW_PY" -m omnimarket.nodes.node_emit_daemon start'
    assert marker in text
    block_start = text.index(marker)
    block_end = text.index(" &\n", block_start)
    invocation = text[block_start:block_end]
    assert "--kafka-bootstrap-servers" in invocation
    assert "--pid-path" in invocation
    assert "--spool-dir" in invocation
    assert "--event-registry" in invocation
    assert "--log-path" in invocation
    assert '>> "${ONEX_STATE_DIR}/hooks/logs/emit-daemon.log"' not in invocation
    assert ">/dev/null 2>&1" in invocation
    assert f"-m {legacy_module} start" not in invocation
    assert "omnibase_infra.runtime.emit_daemon.cli start" not in invocation


def test_session_end_stop_path_uses_omnimarket_node() -> None:
    legacy_module = "omniclaude" + ".publisher"
    text = SESSION_END.read_text()
    assert (
        'env -u PYTHONPATH "$BREW_PY" -m omnimarket.nodes.node_emit_daemon stop' in text
    )
    assert "--pid-path" in text
    assert f"-m {legacy_module} stop" not in text
    assert "omnibase_infra.runtime.emit_daemon.cli stop" not in text
