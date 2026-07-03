# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavior tests for HandlerContextInjection event emission (OMN-12390).

Pins the _emit_event contract:
- valid session_id derives entity_id directly from UUID
- non-UUID session_id falls through to correlation_id derivation
- no session_id AND no correlation_id skips emission silently
- non-UUID correlation_id is coerced to deterministic UUID (with warning)
- emit_hook_event failure is caught and logged, never propagated
- _derive_deterministic_id is deterministic for same inputs
- _emit_injection_record writes a record for the emit daemon
  (patching the emit side to avoid Kafka I/O)

All tests run without Kafka or external services.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelPatternRecord,
)
from omniclaude.hooks.schemas import ContextSource

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(**kwargs: Any) -> HandlerContextInjection:
    """Create a HandlerContextInjection with a noop DB loader."""
    config = ContextInjectionConfig(enabled=True, db_enabled=True, **kwargs)
    handler = HandlerContextInjection(config=config)

    async def _noop_load(
        domain: str | None = None,
        project_scope: str | None = None,
    ) -> Any:
        from omniclaude.hooks.handler_context_injection import ModelLoadPatternsResult

        return ModelLoadPatternsResult(patterns=[], source_files=[])

    handler._load_patterns_from_database = _noop_load  # type: ignore[assignment]
    return handler


def _make_pattern(
    pattern_id: str = "pat-001", confidence: float = 0.9
) -> ModelPatternRecord:
    return ModelPatternRecord(
        pattern_id=pattern_id,
        domain="testing",
        title="Test Pattern",
        description="Desc",
        confidence=confidence,
        usage_count=1,
        success_rate=0.9,
    )


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# _derive_deterministic_id
# ---------------------------------------------------------------------------


class TestDeriveDeterministicId:
    """_derive_deterministic_id returns a stable UUID from correlation_id + project."""

    def test_same_inputs_produce_same_uuid(self) -> None:
        handler = _make_handler()
        uid1 = handler._derive_deterministic_id("corr-abc", "/project/root")
        uid2 = handler._derive_deterministic_id("corr-abc", "/project/root")
        assert uid1 == uid2

    def test_different_correlation_ids_produce_different_uuids(self) -> None:
        handler = _make_handler()
        uid1 = handler._derive_deterministic_id("corr-aaa", "/project")
        uid2 = handler._derive_deterministic_id("corr-bbb", "/project")
        assert uid1 != uid2

    def test_different_project_roots_produce_different_uuids(self) -> None:
        handler = _make_handler()
        uid1 = handler._derive_deterministic_id("corr-abc", "/project/a")
        uid2 = handler._derive_deterministic_id("corr-abc", "/project/b")
        assert uid1 != uid2

    def test_none_project_root_is_handled(self) -> None:
        handler = _make_handler()
        uid = handler._derive_deterministic_id("corr-abc", None)
        assert isinstance(uid, UUID)

    def test_returns_valid_uuid(self) -> None:
        handler = _make_handler()
        uid = handler._derive_deterministic_id("corr-xyz", "/p")
        # Must be constructable as UUID — will raise ValueError if malformed
        assert UUID(str(uid)) == uid


# ---------------------------------------------------------------------------
# _emit_event: entity_id derivation paths
# ---------------------------------------------------------------------------


class TestEmitEventEntityIdDerivation:
    """_emit_event entity_id derivation contract."""

    @pytest.mark.asyncio
    async def test_valid_uuid_session_id_is_used_directly(self) -> None:
        """When session_id is a valid UUID, entity_id == that UUID."""
        handler = _make_handler()
        captured: list[Any] = []

        async def _capture(payload: Any) -> Any:
            captured.append(payload)
            return MagicMock(success=True)

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            side_effect=_capture,
        ):
            session_id = str(uuid4())
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=100,
                retrieval_ms=10,
                session_id=session_id,
                correlation_id=str(uuid4()),
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        assert len(captured) == 1
        assert str(captured[0].entity_id) == session_id

    @pytest.mark.asyncio
    async def test_no_session_id_no_correlation_id_skips_emit(self) -> None:
        """When both session_id and correlation_id are absent, emit is skipped."""
        handler = _make_handler()

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            new_callable=AsyncMock,
        ) as mock_emit:
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=100,
                retrieval_ms=10,
                session_id="",
                correlation_id="",
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_uuid_correlation_id_derives_deterministic_uuid(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-UUID correlation_id triggers warning and deterministic UUID derivation."""
        handler = _make_handler()
        captured: list[Any] = []

        async def _capture(payload: Any) -> Any:
            captured.append(payload)
            return MagicMock(success=True)

        non_uuid_correlation = "git-sha-abc123def456"

        with (
            patch(
                "omniclaude.hooks.handler_context_injection.emit_hook_event",
                side_effect=_capture,
            ),
            caplog.at_level(logging.WARNING),
        ):
            session_id = str(uuid4())
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=100,
                retrieval_ms=10,
                session_id=session_id,
                correlation_id=non_uuid_correlation,
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        assert len(captured) == 1
        # Warning must mention the non-UUID correlation ID
        assert "Non-UUID" in caplog.text or "non-uuid" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_emit_failure_is_swallowed(self) -> None:
        """If emit_hook_event raises, _emit_event catches it and does not re-raise."""
        handler = _make_handler()

        async def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Kafka gone")

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            side_effect=_raise,
        ):
            # Must not raise
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=100,
                retrieval_ms=10,
                session_id=str(uuid4()),
                correlation_id=str(uuid4()),
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

    @pytest.mark.asyncio
    async def test_pattern_count_in_payload(self) -> None:
        """pattern_count in emitted payload matches number of patterns passed."""
        handler = _make_handler()
        captured: list[Any] = []

        async def _capture(payload: Any) -> Any:
            captured.append(payload)
            return MagicMock(success=True)

        patterns = [_make_pattern(f"p-{i}") for i in range(7)]

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            side_effect=_capture,
        ):
            await handler._emit_event(
                patterns=patterns,
                context_size_bytes=1024,
                retrieval_ms=50,
                session_id=str(uuid4()),
                correlation_id=str(uuid4()),
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        assert captured[0].pattern_count == 7

    @pytest.mark.asyncio
    async def test_context_size_bytes_in_payload(self) -> None:
        """context_size_bytes is forwarded to the emitted payload."""
        handler = _make_handler()
        captured: list[Any] = []

        async def _capture(payload: Any) -> Any:
            captured.append(payload)
            return MagicMock(success=True)

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            side_effect=_capture,
        ):
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=2048,
                retrieval_ms=50,
                session_id=str(uuid4()),
                correlation_id=str(uuid4()),
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        assert captured[0].context_size_bytes == 2048

    @pytest.mark.asyncio
    async def test_context_source_database_by_default(self) -> None:
        """Default context_source is ContextSource.DATABASE."""
        handler = _make_handler()
        captured: list[Any] = []

        async def _capture(payload: Any) -> Any:
            captured.append(payload)
            return MagicMock(success=True)

        with patch(
            "omniclaude.hooks.handler_context_injection.emit_hook_event",
            side_effect=_capture,
        ):
            await handler._emit_event(
                patterns=[_make_pattern()],
                context_size_bytes=100,
                retrieval_ms=10,
                session_id=str(uuid4()),
                correlation_id=str(uuid4()),
                project_root=None,
                agent_domain="testing",
                min_confidence=0.7,
                emitted_at=_now(),
            )

        assert captured[0].context_source == ContextSource.DATABASE


# ---------------------------------------------------------------------------
# _emit_injection_record: emit daemon contract
# ---------------------------------------------------------------------------


class TestEmitInjectionRecord:
    """_emit_injection_record writes to the emit daemon without blocking."""

    def test_emit_injection_record_does_not_raise_on_failure(self) -> None:
        """_emit_injection_record must never propagate exceptions."""
        from omniclaude.hooks.cohort_assignment import EnumCohort
        from omniclaude.hooks.models_injection_tracking import (
            EnumInjectionContext,
            EnumInjectionSource,
        )

        handler = _make_handler()

        with patch(
            "omniclaude.hooks.handler_context_injection._get_emit_event",
            side_effect=RuntimeError("emit daemon not running"),
        ):
            # Must not raise — _emit_injection_record catches all exceptions
            result = handler._emit_injection_record(
                injection_id=uuid4(),
                session_id_raw="sess-abc",
                pattern_ids=["pat-001", "pat-002"],
                injection_context=EnumInjectionContext.USER_PROMPT_SUBMIT,
                source=EnumInjectionSource.INJECTED,
                cohort=EnumCohort.TREATMENT,
                assignment_seed=42,
                injected_content="## Patterns\n...",
                injected_token_count=50,
                correlation_id=str(uuid4()),
            )

        # Returns False on failure (graceful degradation, not exception)
        assert result is False
