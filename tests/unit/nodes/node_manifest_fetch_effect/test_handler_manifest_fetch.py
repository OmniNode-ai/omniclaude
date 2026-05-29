# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerManifestFetch.

Tests cover:
- Successful manifest fetch (HTTP 200 with JSON payload)
- Timeout handling (httpx.TimeoutException)
- Network error handling (httpx.NetworkError)
- Non-200 HTTP status codes
- Malformed JSON response
- Protocol conformance (ProtocolManifestFetch)
- Model field validation (ModelManifestFetchRequest, ModelManifestFetchResult)
- EnumManifestFetchStatus values

All tests are unit tests with no network calls — httpx is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest

from omniclaude.nodes.node_manifest_fetch_effect import (
    EnumManifestFetchStatus,
    HandlerManifestFetch,
    ModelManifestFetchRequest,
    ModelManifestFetchResult,
    ProtocolManifestFetch,
)
from omniclaude.nodes.node_manifest_fetch_effect.handlers.handler_manifest_fetch import (
    MANIFEST_PATH,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUNTIME_URL = "http://localhost:18085"
_EXPECTED_URL = f"{_RUNTIME_URL}{MANIFEST_PATH}"
_SAMPLE_MANIFEST = {
    "nodes": [{"name": "node_agent_chat", "version": "1.0.0"}],
    "version": "0.36.0",
}
_CORRELATION_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_request(
    runtime_url: str = _RUNTIME_URL,
    timeout_ms: int = 5000,
    correlation_id: UUID | None = None,
) -> ModelManifestFetchRequest:
    return ModelManifestFetchRequest(
        runtime_url=runtime_url,
        timeout_ms=timeout_ms,
        correlation_id=correlation_id,
    )


def _make_http_response(
    status_code: int = 200,
    json_body: object = None,
    raise_json_error: bool = False,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("invalid JSON")
    else:
        resp.json.return_value = (
            json_body if json_body is not None else _SAMPLE_MANIFEST
        )
    return resp


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelManifestFetchRequest:
    """Validate ModelManifestFetchRequest field constraints."""

    def test_defaults(self) -> None:
        req = ModelManifestFetchRequest(runtime_url=_RUNTIME_URL)
        assert req.runtime_url == _RUNTIME_URL
        assert req.timeout_ms == 5000
        assert req.correlation_id is None

    def test_custom_fields(self) -> None:
        req = ModelManifestFetchRequest(
            runtime_url="http://localhost:8085",
            timeout_ms=1000,
            correlation_id=_CORRELATION_ID,
        )
        assert req.timeout_ms == 1000
        assert req.correlation_id == _CORRELATION_ID

    def test_frozen(self) -> None:
        req = _make_request()
        with pytest.raises(
            Exception
        ):  # frozen=True raises ValidationError or AttributeError
            req.runtime_url = "http://other"  # type: ignore[misc]

    def test_timeout_lower_bound(self) -> None:
        with pytest.raises(Exception):
            ModelManifestFetchRequest(runtime_url=_RUNTIME_URL, timeout_ms=99)

    def test_timeout_upper_bound(self) -> None:
        with pytest.raises(Exception):
            ModelManifestFetchRequest(runtime_url=_RUNTIME_URL, timeout_ms=60001)

    def test_empty_runtime_url_rejected(self) -> None:
        with pytest.raises(Exception):
            ModelManifestFetchRequest(runtime_url="")


@pytest.mark.unit
class TestModelManifestFetchResult:
    """Validate ModelManifestFetchResult field contract."""

    def test_success_result(self) -> None:
        result = ModelManifestFetchResult(
            status=EnumManifestFetchStatus.SUCCESS,
            manifest=_SAMPLE_MANIFEST,
            runtime_url=_RUNTIME_URL,
            duration_ms=42.5,
        )
        assert result.status == EnumManifestFetchStatus.SUCCESS
        assert result.manifest == _SAMPLE_MANIFEST
        assert result.error is None

    def test_failure_result(self) -> None:
        result = ModelManifestFetchResult(
            status=EnumManifestFetchStatus.TIMEOUT,
            manifest={},
            runtime_url=_RUNTIME_URL,
            duration_ms=5001.0,
            error="Request timed out after 5000ms",
        )
        assert result.status == EnumManifestFetchStatus.TIMEOUT
        assert result.manifest == {}
        assert result.error is not None

    def test_frozen(self) -> None:
        result = ModelManifestFetchResult(
            status=EnumManifestFetchStatus.SUCCESS,
            manifest={},
            runtime_url=_RUNTIME_URL,
        )
        with pytest.raises(Exception):
            result.status = EnumManifestFetchStatus.ERROR  # type: ignore[misc]


@pytest.mark.unit
class TestEnumManifestFetchStatus:
    """Validate enum values."""

    def test_all_values_present(self) -> None:
        values = {s.value for s in EnumManifestFetchStatus}
        assert "success" in values
        assert "timeout" in values
        assert "unavailable" in values
        assert "error" in values


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProtocolConformance:
    """HandlerManifestFetch satisfies ProtocolManifestFetch."""

    def test_isinstance_check(self) -> None:
        handler = HandlerManifestFetch()
        assert isinstance(handler, ProtocolManifestFetch)

    def test_handler_key(self) -> None:
        handler = HandlerManifestFetch()
        assert handler.handler_key == "http"


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerManifestFetch:
    """Tests for HandlerManifestFetch.fetch()."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """HTTP 200 with valid JSON returns SUCCESS status and manifest payload."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, _SAMPLE_MANIFEST)

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.SUCCESS
        assert result.manifest == _SAMPLE_MANIFEST
        assert result.runtime_url == _RUNTIME_URL
        assert result.error is None
        assert result.duration_ms >= 0.0
        mock_client.get.assert_called_once_with(_EXPECTED_URL, timeout=5.0)

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """httpx.TimeoutException returns TIMEOUT status with error message."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request(timeout_ms=1000))

        assert result.status == EnumManifestFetchStatus.TIMEOUT
        assert result.manifest == {}
        assert result.error is not None
        assert "1000" in result.error

    @pytest.mark.asyncio
    async def test_network_error(self) -> None:
        """httpx.NetworkError returns UNAVAILABLE status."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.NetworkError("connection refused")

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.UNAVAILABLE
        assert result.manifest == {}
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_http_404(self) -> None:
        """Non-200 HTTP status returns UNAVAILABLE with HTTP status in error."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(404)

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.UNAVAILABLE
        assert result.manifest == {}
        assert "404" in (result.error or "")

    @pytest.mark.asyncio
    async def test_http_500(self) -> None:
        """HTTP 500 returns UNAVAILABLE."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(500)

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.UNAVAILABLE
        assert "500" in (result.error or "")

    @pytest.mark.asyncio
    async def test_malformed_json(self) -> None:
        """JSON parse failure returns ERROR status."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, raise_json_error=True)

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.ERROR
        assert result.manifest == {}
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_unexpected_exception(self) -> None:
        """Unexpected exception returns ERROR status and does not propagate."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = RuntimeError("unexpected failure")

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.ERROR
        assert result.error is not None
        assert "RuntimeError" in (result.error or "")

    @pytest.mark.asyncio
    async def test_runtime_url_trailing_slash_stripped(self) -> None:
        """Trailing slash on runtime_url does not produce double-slash in URL."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, {})

        handler = HandlerManifestFetch(client=mock_client)
        await handler.fetch(_make_request(runtime_url=f"{_RUNTIME_URL}/"))

        call_url = mock_client.get.call_args[0][0]
        assert "//" not in call_url.replace("http://", "").replace("https://", "")

    @pytest.mark.asyncio
    async def test_result_type_is_model_manifest_fetch_result(self) -> None:
        """Return type is always ModelManifestFetchResult."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, {})

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert isinstance(result, ModelManifestFetchResult)

    @pytest.mark.asyncio
    async def test_empty_manifest_payload(self) -> None:
        """Empty JSON object {} is a valid SUCCESS response."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, {})

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request())

        assert result.status == EnumManifestFetchStatus.SUCCESS
        assert result.manifest == {}

    @pytest.mark.asyncio
    async def test_correlation_id_passed_through(self) -> None:
        """correlation_id in request does not affect fetch behaviour."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = _make_http_response(200, _SAMPLE_MANIFEST)

        handler = HandlerManifestFetch(client=mock_client)
        result = await handler.fetch(_make_request(correlation_id=_CORRELATION_ID))

        assert result.status == EnumManifestFetchStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_manifest_path_constant(self) -> None:
        """MANIFEST_PATH is the expected introspection endpoint."""
        assert MANIFEST_PATH == "/v1/introspection/manifest"
