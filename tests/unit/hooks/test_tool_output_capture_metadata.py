# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Content-free output capture metadata (OMN-16979)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).parents[3]
_HOOKS_LIB = _ROOT / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


def test_metadata_capture_never_emits_raw_output_or_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import emit_client_wrapper
    from tool_output_capture_metadata import emit_metadata

    emitted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        emit_client_wrapper,
        "emit_event",
        lambda event_type, payload: emitted.append((event_type, payload)) or True,
    )
    raw_secret = "Bearer abcdefghijklmnopqrstuvwxyz.0123456789"
    assert emit_metadata(
        {
            "tool_name": "Bash",
            "session_id": "s-1",
            "tool_use_id": "toolu-1",
            "tool_input": {"command": "kubectl get secret"},
            "tool_response": {"stdout": raw_secret, "stderr": "", "interrupted": False},
        }
    )
    assert len(emitted) == 1
    event_type, metadata = emitted[0]
    assert event_type == "tool.output.captured"
    assert set(metadata) == {
        "tool_name",
        "suppression_decision",
        "correlation_id",
        "session_id",
        "tool_use_id",
        "command_type",
        "original_bytes",
        "original_lines",
    }
    rendered = json.dumps(metadata)
    assert raw_secret not in rendered
    assert "tool_response" not in rendered
    assert "kubectl get secret" not in rendered
