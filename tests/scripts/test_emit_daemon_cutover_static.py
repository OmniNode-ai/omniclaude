# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ROUTING_RECORDER = REPO_ROOT / "src/omniclaude/routing/routing_recorder.py"
EVIDENCE_WRITER = REPO_ROOT / "src/omniclaude/verification/evidence_writer.py"
USER_PROMPT_SUBMIT = REPO_ROOT / "plugins/onex/hooks/scripts/user-prompt-submit.sh"
PUBLISHER_INIT = REPO_ROOT / "src/omniclaude/publisher/__init__.py"


def test_emit_client_imports_use_omnimarket_daemon_client() -> None:
    for path in (ROUTING_RECORDER, EVIDENCE_WRITER, PUBLISHER_INIT):
        text = path.read_text()
        assert "omnimarket.nodes.node_emit_daemon.client" in text
        assert "EmitClient" in text
        assert "omniclaude.publisher.emit_client" not in text


def test_emit_health_warning_references_omnimarket_daemon() -> None:
    text = USER_PROMPT_SUBMIT.read_text()
    assert "pkill -f 'omnimarket.nodes.node_emit_daemon'" in text
    assert "pkill -f 'omniclaude.publisher'" not in text
