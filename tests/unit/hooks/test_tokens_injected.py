# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for tokens_injected field on ModelHookContextInjectedPayload (OMN-5548)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.hooks.schemas import (
    ContextSource,
    ModelHookContextInjectedPayload,
)

pytestmark = pytest.mark.unit


class TestTokensInjected:
    """Test tokens_injected field on context injection payload."""

    def _make_payload(self, **overrides: object) -> ModelHookContextInjectedPayload:
        defaults = {
            "entity_id": uuid4(),
            "session_id": "sess-001",
            "correlation_id": uuid4(),
            "causation_id": uuid4(),
            "emitted_at": datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC),
            "context_source": ContextSource.DATABASE,
            "pattern_count": 3,
            "context_size_bytes": 1024,
            "retrieval_duration_ms": 50,
        }
        defaults.update(overrides)
        return ModelHookContextInjectedPayload(**defaults)  # type: ignore[arg-type]

    def test_tokens_injected_default_zero(self) -> None:
        payload = self._make_payload()
        assert payload.tokens_injected == 0

    def test_tokens_injected_set_explicitly(self) -> None:
        payload = self._make_payload(tokens_injected=500)
        assert payload.tokens_injected == 500

    def test_tokens_injected_serializes(self) -> None:
        payload = self._make_payload(tokens_injected=250)
        data = payload.model_dump(mode="json")
        assert data["tokens_injected"] == 250

    def test_tokens_injected_rejects_negative(self) -> None:
        with pytest.raises(Exception):
            self._make_payload(tokens_injected=-1)

    def test_tokens_injected_frozen(self) -> None:
        payload = self._make_payload(tokens_injected=100)
        with pytest.raises(Exception):
            payload.tokens_injected = 200  # type: ignore[misc]
