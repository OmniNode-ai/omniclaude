# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for quality_enforcer.py pattern enforcement Kafka emission.

Verifies that QualityEnforcer emits to onex.evt.omniclaude.pattern-enforcement.v1
(TopicBase.PATTERN_ENFORCEMENT) when violations are detected during Phase 1
validation.

Ticket: OMN-2378 — wire pattern enforcement emitter in omniclaude
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# Ensure src is on path
_SRC = Path(__file__).resolve().parents[4] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Ensure hooks lib is on path (needed for emit_client_wrapper)
_HOOKS_LIB = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_write_tool_call(file_path: str = "/repo/src/my_module.py") -> dict[str, Any]:
    """Minimal Write tool_call fixture."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": "class badNamingConvention:\n    pass\n",
        },
    }


def _make_violation() -> Any:
    """Return a minimal Violation-like object."""
    from dataclasses import dataclass

    @dataclass
    class FakeViolation:
        name: str = "badNaming"
        suggestion: str = "GoodNaming"
        line: int = 1
        rule: str = "class names must use PascalCase"
        violation_type: str = "naming"
        expected_format: str = "PascalCase"

    return FakeViolation()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQualityEnforcerEmission:
    """QualityEnforcer must emit to PATTERN_ENFORCEMENT topic on violation."""

    @pytest.mark.asyncio
    async def test_violation_triggers_pattern_enforcement_emission(self) -> None:
        """When violations are found, emit_event('pattern.enforcement', ...) is called."""
        from omniclaude.lib.utils.quality_enforcer import QualityEnforcer

        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            if event_type == "pattern.enforcement":
                captured.append({"event_type": event_type, "payload": payload})
            return True

        violation = _make_violation()
        tool_call = _make_write_tool_call()

        with (
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_1_VALIDATION",
                True,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_2_RAG",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_3_CORRECTION",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_4_AI_QUORUM",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.QualityEnforcer._run_phase_1_validation",
                new=AsyncMock(return_value=[violation]),
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer._emit_enforcement_event",
                side_effect=record_emit,
            ),
        ):
            enforcer = QualityEnforcer()
            await enforcer.enforce(tool_call)

        assert len(captured) == 1, (
            f"Expected 1 pattern.enforcement emit on violation, got {len(captured)}. "
            "quality_enforcer.py must call _emit_enforcement_event() when violations are found."
        )
        assert captured[0]["event_type"] == "pattern.enforcement"

    @pytest.mark.asyncio
    async def test_no_emission_when_no_violations(self) -> None:
        """When no violations are found, pattern.enforcement is NOT emitted."""
        from omniclaude.lib.utils.quality_enforcer import QualityEnforcer

        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append({"event_type": event_type})
            return True

        tool_call = _make_write_tool_call()

        with (
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_1_VALIDATION",
                True,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.QualityEnforcer._run_phase_1_validation",
                new=AsyncMock(return_value=[]),  # No violations
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer._emit_enforcement_event",
                side_effect=record_emit,
            ),
        ):
            enforcer = QualityEnforcer()
            await enforcer.enforce(tool_call)

        enforcement_emits = [
            c for c in captured if c["event_type"] == "pattern.enforcement"
        ]
        assert len(enforcement_emits) == 0, (
            f"Expected 0 pattern.enforcement emits when no violations, got {len(enforcement_emits)}"
        )

    @pytest.mark.asyncio
    async def test_emission_payload_has_required_fields(self) -> None:
        """Emitted payload includes session_id, correlation_id, timestamp, language, domain, pattern_name, outcome."""
        from omniclaude.lib.utils.quality_enforcer import QualityEnforcer

        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            if event_type == "pattern.enforcement":
                captured.append(payload)
            return True

        violation = _make_violation()
        tool_call = _make_write_tool_call("/repo/src/module.py")

        with (
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_1_VALIDATION",
                True,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_2_RAG",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_3_CORRECTION",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_4_AI_QUORUM",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.QualityEnforcer._run_phase_1_validation",
                new=AsyncMock(return_value=[violation]),
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer._emit_enforcement_event",
                side_effect=record_emit,
            ),
        ):
            enforcer = QualityEnforcer()
            await enforcer.enforce(tool_call)

        assert len(captured) == 1
        payload = captured[0]

        # Required fields per EventRegistry registration (OMN-2442)
        required_fields = {
            "session_id",
            "correlation_id",
            "timestamp",
            "language",
            "domain",
            "pattern_name",
            "outcome",
        }
        missing = required_fields - set(payload.keys())
        assert not missing, (
            f"pattern.enforcement payload missing required fields: {missing}"
        )

    @pytest.mark.asyncio
    async def test_emission_outcome_is_violation(self) -> None:
        """Outcome field must be 'violation' (not 'hit') for QualityEnforcer events."""
        from omniclaude.lib.utils.quality_enforcer import QualityEnforcer

        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            if event_type == "pattern.enforcement":
                captured.append(payload)
            return True

        violation = _make_violation()
        tool_call = _make_write_tool_call()

        with (
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_1_VALIDATION",
                True,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_2_RAG",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_3_CORRECTION",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_4_AI_QUORUM",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.QualityEnforcer._run_phase_1_validation",
                new=AsyncMock(return_value=[violation]),
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer._emit_enforcement_event",
                side_effect=record_emit,
            ),
        ):
            enforcer = QualityEnforcer()
            await enforcer.enforce(tool_call)

        assert captured[0]["outcome"] == "violation", (
            f"Expected outcome='violation' for naming violation events, "
            f"got outcome={captured[0]['outcome']!r}"
        )

    @pytest.mark.asyncio
    async def test_emission_failure_does_not_block_enforcement(self) -> None:
        """If emit fails, enforcement still completes — fail-open design."""
        from omniclaude.lib.utils.quality_enforcer import QualityEnforcer

        violation = _make_violation()
        tool_call = _make_write_tool_call()

        def failing_emit(event_type: str, payload: dict[str, Any]) -> bool:
            raise RuntimeError("Kafka unavailable")

        with (
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_1_VALIDATION",
                True,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_2_RAG",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_3_CORRECTION",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.ENABLE_PHASE_4_AI_QUORUM",
                False,
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer.QualityEnforcer._run_phase_1_validation",
                new=AsyncMock(return_value=[violation]),
            ),
            patch(
                "omniclaude.lib.utils.quality_enforcer._emit_enforcement_event",
                side_effect=failing_emit,
            ),
        ):
            enforcer = QualityEnforcer()
            # Must not raise — emit failure is non-blocking
            result = await enforcer.enforce(tool_call)

        # The enforcement result must still be the original tool_call (not None/crash)
        assert result is not None

    def test_pattern_enforcement_topic_constant(self) -> None:
        """TopicBase.PATTERN_ENFORCEMENT resolves to the canonical wire address."""
        from omniclaude.hooks.topics import TopicBase

        assert (
            TopicBase.PATTERN_ENFORCEMENT
            == "onex.evt.omniclaude.pattern-enforcement.v1"
        )

    def test_emit_enforcement_event_is_importable(self) -> None:
        """_emit_enforcement_event must be importable from quality_enforcer module."""
        from omniclaude.lib.utils import quality_enforcer

        assert hasattr(quality_enforcer, "_emit_enforcement_event"), (
            "quality_enforcer must expose _emit_enforcement_event() for testability"
        )
