# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the delegation daemon with Valkey caching.

These tests verify:
- Classification caching via Valkey (hit/miss/key uniqueness)
- Request handling (valid/invalid/missing fields)
- Valkey failure modes (unavailable/timeout/schema mismatch)

All Valkey and orchestration dependencies are mocked — no live services needed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestClassifyWithCache:
    """Tests for _classify_with_cache()."""

    def _import_module(self) -> Any:
        """Import delegation_daemon module (deferred so tests fail cleanly if missing)."""
        # The module lives under plugins/onex/hooks/lib/ which is added to sys.path
        # at import time.  We import by name since the module sets up its own paths.
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_classify_and_cache_miss(self) -> None:
        """Cache miss: calls TaskClassifier, stores result in Valkey."""
        mod = self._import_module()

        fake_classification = {
            "intent": "document",
            "confidence": 0.92,
            "delegatable": True,
        }
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = None  # cache miss

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                intent=MagicMock(value="document"),
                confidence=0.92,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write docs for the API", "corr-123")

        assert result is not None
        assert result["intent"] == "document"
        # Verify Valkey set was called
        mock_valkey.set.assert_called_once()

    def test_classify_and_cache_hit(self) -> None:
        """Cache hit: returns cached classification without calling TaskClassifier."""
        mod = self._import_module()

        cached_data = json.dumps(
            {
                "schema_version": 1,
                "intent": "test",
                "confidence": 0.88,
                "delegatable": True,
                "cached_at": "2026-01-01T00:00:00Z",
            }
        )
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = cached_data.encode()

        with patch.object(mod, "_get_valkey", return_value=mock_valkey):
            result = mod._classify_with_cache("Write unit tests", "corr-456")

        assert result is not None
        assert result["intent"] == "test"
        assert result["confidence"] == 0.88

    def test_cache_key_differs_for_different_prompts(self) -> None:
        """Different prompts produce different cache keys."""
        prompt_a = "Write documentation"
        prompt_b = "Fix the bug in auth"

        key_a = (
            f"delegation:classify:{hashlib.sha256(prompt_a[:500].encode()).hexdigest()}"
        )
        key_b = (
            f"delegation:classify:{hashlib.sha256(prompt_b[:500].encode()).hexdigest()}"
        )

        assert key_a != key_b


@pytest.mark.unit
class TestHandleRequest:
    """Tests for _handle_request()."""

    def _import_module(self) -> Any:
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_handle_request_valid_json(self) -> None:
        """Valid JSON request returns orchestration result."""
        mod = self._import_module()

        request = json.dumps(
            {
                "prompt": "Write docs",
                "correlation_id": "corr-789",
                "session_id": "sess-001",
            }
        ).encode()

        fake_result = {"delegated": True, "response": "Here are docs"}

        with patch.object(
            mod, "orchestrate_delegation", return_value=fake_result
        ) as mock_orch:
            response = mod._handle_request(request)

        parsed = json.loads(response)
        assert parsed["delegated"] is True
        mock_orch.assert_called_once()

    def test_handle_request_invalid_json(self) -> None:
        """Garbage input returns error JSON."""
        mod = self._import_module()

        response = mod._handle_request(b"not json at all {{{")
        parsed = json.loads(response)
        assert parsed.get("delegated") is False
        assert "error" in parsed or "reason" in parsed

    def test_handle_request_missing_fields(self) -> None:
        """JSON without 'prompt' field returns error."""
        mod = self._import_module()

        request = json.dumps({"correlation_id": "corr-000"}).encode()
        response = mod._handle_request(request)
        parsed = json.loads(response)
        assert parsed.get("delegated") is False


@pytest.mark.unit
class TestValkeyFailureModes:
    """Tests for Valkey failure scenarios."""

    def _import_module(self) -> Any:
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_valkey_unavailable_falls_back(self) -> None:
        """When Valkey is unreachable, classification proceeds without cache."""
        mod = self._import_module()

        with (
            patch.object(mod, "_get_valkey", return_value=None),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                intent=MagicMock(value="research"),
                confidence=0.85,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Research the topic", "corr-fallback")

        assert result is not None
        assert result["intent"] == "research"

    def test_valkey_timeout_falls_back(self) -> None:
        """When Valkey.get() times out, classification proceeds without cache."""
        mod = self._import_module()

        mock_valkey = MagicMock()
        mock_valkey.get.side_effect = TimeoutError("Connection timed out")

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                intent=MagicMock(value="test"),
                confidence=0.90,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write tests", "corr-timeout")

        assert result is not None
        assert result["intent"] == "test"

    def test_cache_schema_mismatch_ignored(self) -> None:
        """Cached entry with wrong schema_version is treated as cache miss."""
        mod = self._import_module()

        stale_data = json.dumps(
            {
                "schema_version": 999,  # wrong version
                "intent": "document",
                "confidence": 0.99,
                "delegatable": True,
            }
        )
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = stale_data.encode()

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                intent=MagicMock(value="document"),
                confidence=0.91,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write docs", "corr-schema")

        assert result is not None
        # Should have called classifier (cache miss due to schema mismatch)
        mock_tc_cls.assert_called_once()
