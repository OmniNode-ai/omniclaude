# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the CI relay FastAPI application."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from omniclaude.services.ci_relay.app import _reset_rate_limiter, create_app


@pytest.fixture
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the CI_CALLBACK_TOKEN environment variable for tests."""
    monkeypatch.setenv("CI_CALLBACK_TOKEN", "test-secret-token")


@pytest.fixture
def client(_set_token: None) -> TestClient:
    """Create a FastAPI test client with fresh rate limiter."""
    _reset_rate_limiter()
    app = create_app()
    return TestClient(app)


def _make_payload(
    *,
    repo: str = "OmniNode-ai/omniclaude",
    pr: int = 42,
    conclusion: str = "success",
    sha: str = "abc123",
    run_id: int = 12345,
) -> dict:
    """Build a valid callback payload dict."""
    return {
        "repo": repo,
        "pr": pr,
        "conclusion": conclusion,
        "sha": sha,
        "run_id": run_id,
        "ref": "refs/pull/42/merge",
        "head_ref": "feature/my-branch",
        "base_ref": "main",
        "workflow_url": "https://example.com/actions/runs/12345",
        "jobs": [],
    }


@pytest.mark.unit
class TestCIRelayHealth:
    """Tests for the health endpoint."""

    def test_health(self, client: TestClient) -> None:
        """Test health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ci-relay"


@pytest.mark.unit
class TestCIRelayAuth:
    """Tests for bearer token authentication."""

    def test_missing_auth_header(self, client: TestClient) -> None:
        """Test that missing auth header returns 403."""
        response = client.post("/callback", json=_make_payload())
        assert response.status_code == 403

    def test_invalid_token(self, client: TestClient) -> None:
        """Test that invalid bearer token returns 401."""
        response = client.post(
            "/callback",
            json=_make_payload(),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_valid_token(self, client: TestClient) -> None:
        """Test that valid bearer token is accepted."""
        with patch(
            "omniclaude.services.ci_relay.app._publish_to_kafka"
        ) as mock_publish:
            mock_publish.return_value = None
            response = client.post(
                "/callback",
                json=_make_payload(sha="auth-test-sha", run_id=99999),
                headers={"Authorization": "Bearer test-secret-token"},
            )
            assert response.status_code == 200


@pytest.mark.unit
class TestCIRelayCallback:
    """Tests for the callback endpoint."""

    def test_successful_callback(self, client: TestClient) -> None:
        """Test a successful callback publishes an event."""
        with patch(
            "omniclaude.services.ci_relay.app._publish_to_kafka"
        ) as mock_publish:
            mock_publish.return_value = None
            response = client.post(
                "/callback",
                json=_make_payload(),
                headers={"Authorization": "Bearer test-secret-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "published"
            assert data["conclusion"] == "success"
            assert data["pr"] == 42
            mock_publish.assert_called_once()

    def test_duplicate_callback_dedupe(self, client: TestClient) -> None:
        """Test that duplicate callbacks are deduped."""
        with patch(
            "omniclaude.services.ci_relay.app._publish_to_kafka"
        ) as mock_publish:
            mock_publish.return_value = None
            payload = _make_payload()
            headers = {"Authorization": "Bearer test-secret-token"}

            # First call should publish
            response1 = client.post("/callback", json=payload, headers=headers)
            assert response1.status_code == 200
            assert response1.json()["status"] == "published"

            # Second call with same dedupe key should be dropped
            response2 = client.post("/callback", json=payload, headers=headers)
            assert response2.status_code == 200
            assert response2.json()["status"] == "duplicate"

            # Kafka should only have been called once
            assert mock_publish.call_count == 1

    def test_sha_notification_suppression(self, client: TestClient) -> None:
        """Test that same sha+conclusion within cooldown is suppressed."""
        with patch(
            "omniclaude.services.ci_relay.app._publish_to_kafka"
        ) as mock_publish:
            mock_publish.return_value = None
            headers = {"Authorization": "Bearer test-secret-token"}

            # First call: published
            response1 = client.post(
                "/callback",
                json=_make_payload(run_id=1),
                headers=headers,
            )
            assert response1.json()["status"] == "published"

            # Second call with different run_id but same sha+conclusion:
            # suppressed by sha rate limit
            response2 = client.post(
                "/callback",
                json=_make_payload(run_id=2),
                headers=headers,
            )
            assert response2.json()["status"] == "suppressed"
