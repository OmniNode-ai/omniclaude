# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ROUTING_RECORDER = REPO_ROOT / "src/omniclaude/routing/routing_recorder.py"
EVIDENCE_WRITER = REPO_ROOT / "src/omniclaude/verification/evidence_writer.py"
USER_PROMPT_SUBMIT = REPO_ROOT / "plugins/onex/hooks/scripts/user-prompt-submit.sh"
LEGACY_PUBLISHER_SRC = REPO_ROOT / "src" / "omniclaude" / "publisher"
LEGACY_PUBLISHER_TESTS = REPO_ROOT / "tests" / "publisher"


def test_emit_client_imports_use_omnimarket_emit_effect_node() -> None:
    """OMN-15968: routing_recorder/evidence_writer must import the canonical
    node_event_emit_effect node, not the dead node_emit_daemon.client that
    omnimarket#1246 deleted (OMN-13213 D1 follow-through)."""
    for path in (ROUTING_RECORDER, EVIDENCE_WRITER):
        text = path.read_text()
        assert "omnimarket.nodes.node_event_emit_effect" in text
        assert "HandlerEventEmitEffect" in text
        assert "omnimarket.nodes.node_emit_daemon.client" not in text
        assert "EmitClient" not in text
        assert "omniclaude" + ".publisher.emit_client" not in text


def test_legacy_publisher_package_removed() -> None:
    assert not LEGACY_PUBLISHER_SRC.exists()
    assert not LEGACY_PUBLISHER_TESTS.exists()


def test_emit_health_warning_references_omnimarket_daemon() -> None:
    text = USER_PROMPT_SUBMIT.read_text()
    assert "pkill -f 'omnimarket.nodes.node_emit_daemon'" in text
    assert "pkill -f '" + "omniclaude" + ".publisher'" not in text
