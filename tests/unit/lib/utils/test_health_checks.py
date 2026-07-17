# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for omniclaude.lib.utils.health_checks.

Covers the Phase4HealthChecker sync + async health probes, the caching
helpers, result serialization, and the comprehensive aggregation, without
touching any real infrastructure. All HTTP calls are patched at the module
boundary so `requests.exceptions.*` stay real exception classes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

from omniclaude.lib.utils import health_checks
from omniclaude.lib.utils.health_checks import (
    HealthCheckResult,
    HealthStatus,
    Phase4HealthChecker,
)

BASE_URL = "http://intelligence.test"


def _make_response(
    status_code: int = 200,
    *,
    json_data: Any = None,
    json_raises: bool = False,
    content_type: str = "application/json",
    text: str = "",
) -> MagicMock:
    """Build a fake ``requests``/``httpx`` response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.text = text
    resp.content = (text or (json.dumps(json_data) if json_data else "")).encode()
    if json_raises:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data if json_data is not None else {}
    return resp


@pytest.fixture
def checker() -> Phase4HealthChecker:
    """A checker with an explicit base_url so no settings/network is touched."""
    return Phase4HealthChecker(base_url=BASE_URL)


# ---------------------------------------------------------------------------
# HealthStatus / HealthCheckResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthModels:
    def test_health_status_values(self) -> None:
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_result_to_dict_roundtrip(self) -> None:
        result = HealthCheckResult(
            component="svc",
            status=HealthStatus.HEALTHY,
            timestamp="2026-01-01T00:00:00+00:00",
            response_time_ms=12.5,
            details={"k": "v"},
        )
        as_dict = result.to_dict()
        assert as_dict["component"] == "svc"
        # asdict does not coerce the enum; it is preserved as the Enum member.
        assert as_dict["status"] is HealthStatus.HEALTHY
        assert as_dict["response_time_ms"] == 12.5
        assert as_dict["details"] == {"k": "v"}
        assert as_dict["error_message"] is None


# ---------------------------------------------------------------------------
# init + caching helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitAndCache:
    def test_base_url_from_argument(self, checker: Phase4HealthChecker) -> None:
        assert checker.base_url == BASE_URL
        assert checker.cache_duration == 30.0

    def test_cache_roundtrip(self, checker: Phase4HealthChecker) -> None:
        payload = {"status": "healthy"}
        checker._cache_result("k", payload)
        assert checker._is_cache_valid("k") is True
        assert checker._get_cached_result("k") == payload

    def test_missing_key_is_invalid(self, checker: Phase4HealthChecker) -> None:
        assert checker._is_cache_valid("absent") is False
        assert checker._get_cached_result("absent") is None

    def test_expired_cache_is_invalid(self, checker: Phase4HealthChecker) -> None:
        checker.cache_duration = 0.0  # force everything to be considered stale
        checker._cache_result("k", {"status": "healthy"})
        assert checker._is_cache_valid("k") is False
        assert checker._get_cached_result("k") is None

    def test_log_writes_entry(
        self, checker: Phase4HealthChecker, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "health.log"
        checker.log_file = log_file
        checker._log("INFO", "hello", extra="ctx")
        with open(log_file) as f:
            line = json.loads(f.readline())
        assert line["level"] == "INFO"
        assert line["message"] == "[HEALTH] hello"
        assert line["extra"] == "ctx"

    def test_log_failure_is_silent(self, checker: Phase4HealthChecker) -> None:
        # A non-writable path must not raise out of _log.
        checker.log_file = Path("/this/path/does/not/exist/health.log")
        checker._log("ERROR", "boom")  # must not raise


# ---------------------------------------------------------------------------
# check_intelligence_service (sync)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckIntelligenceService:
    def test_healthy_json(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, json_data={"ok": True})
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_intelligence_service()
        assert out["status"] == "healthy"
        assert out["status_code"] == 200
        assert out["details"] == {"ok": True}

    def test_healthy_text_body(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, content_type="text/plain", text="pong")
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_intelligence_service()
        assert out["status"] == "healthy"
        assert out["details"] == "pong"

    def test_non_200_is_unhealthy(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(503, content_type="text/plain", text="down")
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_intelligence_service()
        assert out["status"] == "unhealthy"
        assert out["status_code"] == 503

    def test_timeout(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests,
            "get",
            side_effect=requests.exceptions.Timeout(),
        ):
            out = checker.check_intelligence_service()
        assert out["status"] == "timeout"

    def test_connection_error(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests,
            "get",
            side_effect=requests.exceptions.ConnectionError(),
        ):
            out = checker.check_intelligence_service()
        assert out["status"] == "connection_error"
        assert BASE_URL in out["error"]

    def test_generic_error(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests, "get", side_effect=RuntimeError("kaboom")
        ):
            out = checker.check_intelligence_service()
        assert out["status"] == "error"
        assert "kaboom" in out["error"]


# ---------------------------------------------------------------------------
# check_database_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckDatabaseConnectivity:
    def test_connected(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, json_data={"db": "up"})
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_database_connectivity()
        assert out["status"] == "connected"
        assert out["details"] == {"db": "up"}

    def test_connected_but_parse_fails(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, json_raises=True)
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_database_connectivity()
        assert out["status"] == "connected"
        assert out["details"] == "Connected but response parsing failed"

    def test_http_error(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(500, text="boom")
        with patch.object(health_checks.requests, "get", return_value=resp):
            out = checker.check_database_connectivity()
        assert out["status"] == "error"
        assert out["status_code"] == 500

    def test_timeout(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests,
            "get",
            side_effect=requests.exceptions.Timeout(),
        ):
            out = checker.check_database_connectivity()
        assert out["status"] == "timeout"

    def test_generic_error(self, checker: Phase4HealthChecker) -> None:
        with patch.object(health_checks.requests, "get", side_effect=RuntimeError("x")):
            out = checker.check_database_connectivity()
        assert out["status"] == "error"


# ---------------------------------------------------------------------------
# check_lineage_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckLineageEndpoint:
    def test_working(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(201, json_data={"tracked": True})
        with patch.object(health_checks.requests, "post", return_value=resp):
            out = checker.check_lineage_endpoint()
        assert out["status"] == "working"
        assert out["response_code"] == 201
        assert out["details"] == {"tracked": True}

    def test_working_but_parse_fails(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, json_raises=True)
        with patch.object(health_checks.requests, "post", return_value=resp):
            out = checker.check_lineage_endpoint()
        assert out["status"] == "working"
        assert out["details"] == "Endpoint responded but response parsing failed"

    def test_http_error(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(422, text="bad")
        with patch.object(health_checks.requests, "post", return_value=resp):
            out = checker.check_lineage_endpoint()
        assert out["status"] == "error"
        assert out["response_code"] == 422

    def test_timeout(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests,
            "post",
            side_effect=requests.exceptions.Timeout(),
        ):
            out = checker.check_lineage_endpoint()
        assert out["status"] == "timeout"

    def test_generic_error(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests, "post", side_effect=RuntimeError("x")
        ):
            out = checker.check_lineage_endpoint()
        assert out["status"] == "error"


# ---------------------------------------------------------------------------
# check_feedback_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckFeedbackEndpoint:
    def test_working(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200)
        with patch.object(health_checks.requests, "post", return_value=resp):
            out = checker.check_feedback_endpoint()
        assert out["status"] == "working"
        assert out["response_code"] == 200

    def test_http_error(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(500, text="boom")
        with patch.object(health_checks.requests, "post", return_value=resp):
            out = checker.check_feedback_endpoint()
        assert out["status"] == "error"
        assert out["response_code"] == 500

    def test_timeout(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests,
            "post",
            side_effect=requests.exceptions.Timeout(),
        ):
            out = checker.check_feedback_endpoint()
        assert out["status"] == "timeout"

    def test_generic_error(self, checker: Phase4HealthChecker) -> None:
        with patch.object(
            health_checks.requests, "post", side_effect=RuntimeError("x")
        ):
            out = checker.check_feedback_endpoint()
        assert out["status"] == "error"


# ---------------------------------------------------------------------------
# run_comprehensive_health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComprehensive:
    def test_all_healthy(self, checker: Phase4HealthChecker) -> None:
        get_resp = _make_response(200, json_data={"ok": True})
        post_resp = _make_response(200, json_data={"ok": True})
        with (
            patch.object(health_checks.requests, "get", return_value=get_resp),
            patch.object(health_checks.requests, "post", return_value=post_resp),
        ):
            out = checker.run_comprehensive_health_check()
        assert out["overall_status"] == "healthy"
        assert out["failed_checks"] == []
        assert out["summary"]["total_checks"] == 4
        assert out["summary"]["passed_checks"] == 4

    def test_unhealthy_when_service_down(self, checker: Phase4HealthChecker) -> None:
        with (
            patch.object(
                health_checks.requests,
                "get",
                side_effect=requests.exceptions.Timeout(),
            ),
            patch.object(
                health_checks.requests,
                "post",
                side_effect=requests.exceptions.Timeout(),
            ),
        ):
            out = checker.run_comprehensive_health_check()
        assert out["overall_status"] == "unhealthy"
        assert out["summary"]["failed_checks"] == 4
        assert "intelligence_service" in out["failed_checks"]


# ---------------------------------------------------------------------------
# check_intelligence_service_async
# ---------------------------------------------------------------------------


def _async_client_returning(response: MagicMock) -> MagicMock:
    """Build a fake httpx.AsyncClient usable as an async context manager."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=client)
    return factory


@pytest.mark.unit
class TestCheckIntelligenceServiceAsync:
    async def test_async_healthy(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(200, json_data={"ok": True})
        factory = _async_client_returning(resp)
        with patch.object(health_checks.httpx, "AsyncClient", factory):
            result = await checker.check_intelligence_service_async()
        assert result.status is HealthStatus.HEALTHY
        assert result.component == "intelligence_service"
        assert result.details is not None
        assert result.details["status_code"] == 200

    async def test_async_non_json_is_degraded(
        self, checker: Phase4HealthChecker
    ) -> None:
        resp = _make_response(200, json_raises=True)
        # json.JSONDecodeError is the caught type; make .json raise it.
        resp.json.side_effect = json.JSONDecodeError("x", "y", 0)
        factory = _async_client_returning(resp)
        with patch.object(health_checks.httpx, "AsyncClient", factory):
            result = await checker.check_intelligence_service_async()
        assert result.status is HealthStatus.DEGRADED

    async def test_async_http_error(self, checker: Phase4HealthChecker) -> None:
        resp = _make_response(500)
        factory = _async_client_returning(resp)
        with patch.object(health_checks.httpx, "AsyncClient", factory):
            result = await checker.check_intelligence_service_async()
        assert result.status is HealthStatus.UNHEALTHY

    async def test_async_no_httpx_falls_to_unhealthy(
        self, checker: Phase4HealthChecker
    ) -> None:
        with patch.object(health_checks, "HAS_HTTPX", False):
            result = await checker.check_intelligence_service_async()
        assert result.status is HealthStatus.UNHEALTHY
        assert result.error_message is not None

    async def test_async_uses_cache(self, checker: Phase4HealthChecker) -> None:
        cached = HealthCheckResult(
            component="intelligence_service",
            status=HealthStatus.HEALTHY,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        checker._cache_result("intelligence_service", cached.to_dict())
        # No httpx patch: if the cache is honored, no network path is reached.
        result = await checker.check_intelligence_service_async()
        assert result.status is HealthStatus.HEALTHY
