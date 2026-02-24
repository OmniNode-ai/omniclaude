# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Acceptance tests for OMN-2355: context injection API-based pattern read.

Verifies:
1. Handler includes patterns when the API mock returns them
2. Handler warns (via caplog) when confidence filter excludes all patterns
3. Handler excludes patterns missing required fields (id, pattern_signature, confidence)
4. Handler warns on excluded patterns with missing required fields
5. API URL resolves from INTELLIGENCE_SERVICE_URL env var
6. Handler gracefully degrades when API is unavailable

OMN-2355: fix context injection injecting zero patterns — restore API-based pattern read
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.context_config import ContextInjectionConfig
from omniclaude.hooks.handler_context_injection import (
    HandlerContextInjection,
    ModelLoadPatternsResult,
    ModelPatternRecord,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _make_api_page(patterns: list[dict[str, Any]], limit: int = 50) -> dict[str, Any]:
    """Build a ModelPatternQueryPage-compatible dict for mock responses."""
    return {
        "patterns": patterns,
        "total_returned": len(patterns),
        "limit": limit,
        "offset": 0,
    }


def _make_handler(
    *,
    api_enabled: bool = True,
    api_url: str = "http://localhost:8053",
    min_confidence: float = 0.7,
) -> HandlerContextInjection:
    """Create a HandlerContextInjection with API source configured."""
    config = ContextInjectionConfig(
        enabled=True,
        db_enabled=True,  # db_enabled still needed for flow control
        api_enabled=api_enabled,
        api_url=api_url,
        min_confidence=min_confidence,
    )
    return HandlerContextInjection(config=config)


# =============================================================================
# Core acceptance tests (from OMN-2355 ticket)
# =============================================================================


class TestContextInjectorIncludesPatternsFromAPI:
    """OMN-2355 acceptance: API returns patterns → context has patterns."""

    @pytest.mark.asyncio
    async def test_includes_patterns_when_api_returns_them(self) -> None:
        """OMN-2059 regression: API returned patterns but context has none.

        This is the primary acceptance test from the ticket:
            def test_context_injector_includes_patterns_when_api_returns_them(mock_pattern_api):
                mock_pattern_api.return_value = [
                    {"pattern_id": "PAT-001", "signature": "no bare except",
                     "confidence": 0.90, "language": "python"}
                ]
                context = build_injection_context(session_id="test-session")
                assert len(context.patterns) > 0, "OMN-2059 regression: API returned..."
        """
        api_response = _make_api_page(
            [
                {
                    "id": "PAT-001",
                    "pattern_signature": "no bare except",
                    "confidence": 0.90,
                    "domain_id": "python",
                }
            ]
        )

        handler = _make_handler(min_confidence=0.0)

        with patch.object(handler, "_load_patterns_from_api") as mock_api:
            mock_api.return_value = ModelLoadPatternsResult(
                patterns=[
                    ModelPatternRecord(
                        pattern_id="PAT-001",
                        domain="python",
                        title="no bare except",
                        description="no bare except",
                        confidence=0.90,
                        usage_count=0,
                        success_rate=0.0,
                    )
                ],
                source_files=[],
            )
            result = await handler.handle(session_id="test-session", emit_event=False)

        assert result.pattern_count > 0, (
            "OMN-2059 regression: API returned patterns but context has none"
        )
        assert result.pattern_count == 1
        assert result.success is True

    @pytest.mark.asyncio
    async def test_context_markdown_contains_pattern_title(self) -> None:
        """Pattern title appears in injected context markdown."""
        handler = _make_handler(min_confidence=0.0)

        with patch.object(handler, "_load_patterns_from_api") as mock_api:
            mock_api.return_value = ModelLoadPatternsResult(
                patterns=[
                    ModelPatternRecord(
                        pattern_id="PAT-002",
                        domain="general",
                        title="avoid bare except",
                        description="avoid bare except",
                        confidence=0.85,
                        usage_count=5,
                        success_rate=0.80,
                    )
                ],
                source_files=[],
            )
            result = await handler.handle(emit_event=False)

        assert "avoid bare except" in result.context_markdown

    @pytest.mark.asyncio
    async def test_zero_patterns_when_api_disabled(self) -> None:
        """When api_enabled=False, no patterns are loaded."""
        handler = _make_handler(api_enabled=False, min_confidence=0.0)

        result = await handler.handle(emit_event=False)

        assert result.pattern_count == 0
        assert result.success is True


# =============================================================================
# Filter exclusion warning tests
# =============================================================================


class TestContextInjectorFilterWarnings:
    """OMN-2355 acceptance: filter warning logs when all patterns excluded."""

    @pytest.mark.asyncio
    async def test_logs_warning_when_filter_excludes_all(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning is logged when confidence filter excludes all available patterns.

        From ticket acceptance test:
            def test_context_injector_logs_when_filter_excludes_all(mock_pattern_api, caplog):
                mock_pattern_api.return_value = [
                    {"pattern_id": "PAT-001", "signature": "x",
                     "confidence": 0.10, "language": "python"}
                ]
                with caplog.at_level(logging.WARNING):
                    build_injection_context(session_id="test-session", confidence_min=0.8)
                assert "filter excluded all" in caplog.text.lower()
        """
        handler = _make_handler(min_confidence=0.8)

        # API returns one low-confidence pattern (0.10 < 0.80 threshold)
        with patch.object(handler, "_load_patterns_from_api") as mock_api:
            mock_api.return_value = ModelLoadPatternsResult(
                patterns=[
                    ModelPatternRecord(
                        pattern_id="PAT-001",
                        domain="python",
                        title="x",
                        description="x",
                        confidence=0.10,
                        usage_count=0,
                        success_rate=0.0,
                    )
                ],
                source_files=[],
            )
            with caplog.at_level(logging.WARNING):
                result = await handler.handle(emit_event=False)

        assert result.pattern_count == 0
        assert "filter excluded all" in caplog.text.lower(), (
            f"Expected 'filter excluded all' in warning logs. Got: {caplog.text!r}"
        )

    @pytest.mark.asyncio
    async def test_no_filter_warning_when_api_returns_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No filter warning when API returns 0 patterns (no patterns to filter)."""
        handler = _make_handler(min_confidence=0.8)

        with patch.object(handler, "_load_patterns_from_api") as mock_api:
            mock_api.return_value = ModelLoadPatternsResult(
                patterns=[],
                source_files=[],
            )
            with caplog.at_level(logging.WARNING):
                result = await handler.handle(emit_event=False)

        assert result.pattern_count == 0
        assert "filter excluded all" not in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_no_filter_warning_when_some_patterns_pass(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No filter warning when at least one pattern passes the threshold."""
        handler = _make_handler(min_confidence=0.7)

        with patch.object(handler, "_load_patterns_from_api") as mock_api:
            mock_api.return_value = ModelLoadPatternsResult(
                patterns=[
                    ModelPatternRecord(
                        pattern_id="PAT-001",
                        domain="python",
                        title="high confidence",
                        description="high confidence",
                        confidence=0.90,
                        usage_count=5,
                        success_rate=0.80,
                    ),
                    ModelPatternRecord(
                        pattern_id="PAT-002",
                        domain="python",
                        title="low confidence",
                        description="low confidence",
                        confidence=0.10,
                        usage_count=1,
                        success_rate=0.0,
                    ),
                ],
                source_files=[],
            )
            with caplog.at_level(logging.WARNING):
                result = await handler.handle(emit_event=False)

        assert result.pattern_count == 1  # Only high-confidence passes
        assert "filter excluded all" not in caplog.text.lower()


# =============================================================================
# _load_patterns_from_api field validation tests
# =============================================================================


class TestLoadPatternsFromApiFieldValidation:
    """Test _load_patterns_from_api field mapping and validation."""

    @pytest.mark.asyncio
    async def test_excludes_pattern_missing_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Patterns missing 'id' field are excluded with WARNING."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    # Missing 'id'
                    "pattern_signature": "no bare except",
                    "confidence": 0.90,
                }
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 0
        assert any("missing required fields" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_excludes_pattern_missing_signature(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Patterns missing 'pattern_signature' field are excluded with WARNING."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    "id": "PAT-001",
                    # Missing 'pattern_signature'
                    "confidence": 0.90,
                }
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 0
        assert any("missing required fields" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_excludes_pattern_missing_confidence(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Patterns missing 'confidence' field are excluded with WARNING."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    "id": "PAT-001",
                    "pattern_signature": "no bare except",
                    # Missing 'confidence'
                }
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 0
        assert any("missing required fields" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_valid_pattern_maps_correctly(self) -> None:
        """Valid API response maps correctly to ModelPatternRecord."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    "id": "PAT-001",
                    "pattern_signature": "no bare except",
                    "confidence": 0.90,
                    "domain_id": "python",
                    "quality_score": 0.85,
                    "status": "validated",
                }
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 1
        p = result.patterns[0]
        assert p.pattern_id == "PAT-001"
        assert p.title == "no bare except"
        assert p.confidence == 0.90
        assert p.domain == "python"
        assert p.success_rate == pytest.approx(0.85)
        assert p.lifecycle_state == "validated"

    @pytest.mark.asyncio
    async def test_optional_domain_defaults_to_general(self) -> None:
        """Patterns without domain_id default to 'general'."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    "id": "PAT-001",
                    "pattern_signature": "no bare except",
                    "confidence": 0.90,
                    # No domain_id
                }
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 1
        assert result.patterns[0].domain == "general"

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid_patterns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Valid patterns are included even when others in the batch are invalid."""
        handler = _make_handler()

        api_page = _make_api_page(
            [
                {
                    "id": "PAT-VALID",
                    "pattern_signature": "valid pattern",
                    "confidence": 0.90,
                },
                {
                    # Missing id - should be excluded
                    "pattern_signature": "invalid pattern",
                    "confidence": 0.80,
                },
            ]
        )

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(api_page).encode("utf-8")
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id == "PAT-VALID"
        # Should have warned about excluded pattern
        assert any("excluded" in r.message.lower() for r in caplog.records)


# =============================================================================
# API unavailability tests
# =============================================================================


class TestAPIUnavailability:
    """Test graceful degradation when omniintelligence API is unavailable."""

    @pytest.mark.asyncio
    async def test_graceful_when_api_connection_refused(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Returns empty patterns with warning when API is unreachable."""
        import urllib.error

        handler = _make_handler(api_url="http://localhost:9999")

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 0
        assert len(result.warnings) > 0
        assert any("unavailable" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_graceful_when_api_returns_invalid_json(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Returns empty patterns with warning when API returns non-JSON."""
        handler = _make_handler()

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b"not json at all"
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            with caplog.at_level(logging.WARNING):
                result = await handler._load_patterns_from_api()

        assert len(result.patterns) == 0
        assert len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_handle_returns_empty_gracefully_when_api_down(self) -> None:
        """Full handle() still returns success=True when API is down."""
        import urllib.error

        handler = _make_handler(api_url="http://localhost:9999")

        with patch(
            "omniclaude.hooks.handler_context_injection.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            result = await handler.handle(emit_event=False)

        # Graceful degradation: success=True, pattern_count=0
        assert result.success is True
        assert result.pattern_count == 0


# =============================================================================
# Config: INTELLIGENCE_SERVICE_URL resolution
# =============================================================================


class TestContextInjectionConfigAPIUrl:
    """Test ContextInjectionConfig resolves api_url from INTELLIGENCE_SERVICE_URL."""

    def test_api_url_defaults_to_localhost_8053(self) -> None:
        """Default api_url is http://localhost:8053."""
        import os

        # Inject a sentinel value so patch.dict always has the key to restore,
        # then immediately remove it — guaranteeing INTELLIGENCE_SERVICE_URL is
        # absent for the duration of this test regardless of the outer environment.
        with patch.dict(os.environ, {"INTELLIGENCE_SERVICE_URL": ""}, clear=False):
            del os.environ["INTELLIGENCE_SERVICE_URL"]
            cfg = ContextInjectionConfig()
            assert "8053" in cfg.api_url or "localhost" in cfg.api_url

    def test_api_url_reads_intelligence_service_url(self) -> None:
        """api_url falls back to INTELLIGENCE_SERVICE_URL env var."""
        import os

        with patch.dict(
            os.environ,
            {"INTELLIGENCE_SERVICE_URL": "http://localhost:8053"},
            clear=False,
        ):
            cfg = ContextInjectionConfig()
            assert cfg.api_url == "http://localhost:8053"

    def test_api_enabled_default_true(self) -> None:
        """api_enabled defaults to True."""
        cfg = ContextInjectionConfig()
        assert cfg.api_enabled is True
