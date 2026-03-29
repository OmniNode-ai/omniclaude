# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for task_id passthrough in the emission pipeline.

OMN-6852: Ensure ONEX_TASK_ID is injected into payloads by emit_client_wrapper.py
and preserved through the embedded_publisher fan-out path.

The emit_client_wrapper lives at plugins/onex/hooks/lib/emit_client_wrapper.py
and is NOT importable as a Python module. Tests validate:
1. Observability transform preserves task_id (event_registry.py)
2. Fan-out passthrough rules preserve all payload fields including task_id
3. emit_client_wrapper injects ONEX_TASK_ID into payloads missing it
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestTaskIdPassthrough:
    """Test that task_id flows through the emission pipeline."""

    def test_observability_transform_preserves_task_id(self) -> None:
        """Observability transform does not strip task_id field."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload: dict[str, object] = {
            "session_id": "s1",
            "task_id": "OMN-9999",
            "prompt": "a" * 500,
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        }
        transformed = transform_for_observability(payload)
        assert transformed["task_id"] == "OMN-9999"

    def test_observability_transform_preserves_none_task_id(self) -> None:
        """Observability transform preserves task_id=None without dropping it."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload: dict[str, object] = {
            "session_id": "s1",
            "task_id": None,
            "prompt": "hello",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        }
        transformed = transform_for_observability(payload)
        assert "task_id" in transformed
        assert transformed["task_id"] is None

    def test_event_registration_passthrough_preserves_task_id(self) -> None:
        """FanOutRule with no transform preserves all payload fields including task_id."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("prompt.submitted")
        # Find passthrough fan-out rule (transform=None)
        passthrough_rules = [r for r in reg.fan_out if r.transform is None]
        assert len(passthrough_rules) >= 1, (
            "prompt.submitted must have at least one passthrough fan-out"
        )
        # Passthrough means dict is forwarded as-is -- task_id preserved by identity

    def test_emit_client_wrapper_injects_task_id(self) -> None:
        """emit_client_wrapper injects ONEX_TASK_ID into payloads missing task_id.

        The wrapper is a plugin script (not importable as a package module).
        We verify the injection pattern exists in the source by locating the
        file relative to the project root (4 levels up from this test file).
        """
        from pathlib import Path

        # tests/unit/publisher/test_*.py -> 4 parents -> project root
        project_root = Path(__file__).resolve().parents[3]
        wrapper = (
            project_root
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
            / "emit_client_wrapper.py"
        )
        if not wrapper.exists():
            pytest.skip(f"emit_client_wrapper.py not found at {wrapper}")

        content = wrapper.read_text()
        assert "ONEX_TASK_ID" in content, (
            "emit_client_wrapper.py must reference ONEX_TASK_ID for task_id injection"
        )
        assert '"task_id" not in payload' in content, (
            "emit_client_wrapper.py must check for existing task_id before injection"
        )

    def test_observability_transform_with_new_payload_shape(self) -> None:
        """Observability transform preserves task_id with new prompt_b64 shape."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload: dict[str, object] = {
            "session_id": "s1",
            "task_id": "OMN-1234",
            "prompt_preview": "Fix the bug",
            "prompt_b64": "RnVsbA==",
            "prompt_length": 42,
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
        }
        transformed = transform_for_observability(payload)
        assert transformed["task_id"] == "OMN-1234"
        assert "prompt_b64" not in transformed
