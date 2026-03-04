# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the Linear relay FastAPI application.

Includes representative fixture payloads to verify filter logic per the spec.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from omniclaude.services.linear_relay.app import _reset_dedup_store, create_app
from omniclaude.services.linear_relay.dedup import DedupStore

# ---------------------------------------------------------------------------
# Fixture payloads — representative Linear webhook bodies
# ---------------------------------------------------------------------------

_PROJECT_COMPLETED_PAYLOAD: dict = {
    "action": "update",
    "type": "Project",
    "data": {"id": "proj-abc123", "name": "My Epic", "state": "completed"},
    "organizationId": "org-xyz",
    "webhookId": "wh-project-completed",
    "webhookTimestamp": 1700000000000,
}

_PROJECT_STARTED_PAYLOAD: dict = {
    "action": "update",
    "type": "Project",
    "data": {"id": "proj-def456", "state": "started"},
    "organizationId": "org-xyz",
    "webhookId": "wh-project-started",
    "webhookTimestamp": 1700000001000,
}

_INITIATIVE_COMPLETED_PAYLOAD: dict = {
    "action": "update",
    "type": "Initiative",
    "data": {"id": "init-ghi789", "state": "completed"},
    "organizationId": "org-xyz",
    "webhookId": "wh-initiative-completed",
    "webhookTimestamp": 1700000002000,
}

_ISSUE_PAYLOAD: dict = {
    "action": "create",
    "type": "Issue",
    "data": {"id": "issue-111", "state": "completed"},
    "organizationId": "org-xyz",
    "webhookId": "wh-issue",
    "webhookTimestamp": 1700000003000,
}

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = _TEST_SECRET) -> str:
    """Compute HMAC-SHA256 signature for the body."""
    return hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


def _post(
    client: TestClient,
    payload: dict,
    *,
    secret: str = _TEST_SECRET,
    sig_override: str | None = None,
    extra_headers: dict | None = None,
) -> object:
    """POST a signed JSON payload to /webhook."""
    body = json.dumps(payload).encode("utf-8")
    sig = sig_override if sig_override is not None else _sign(body, secret)
    headers: dict = {"content-type": "application/json", "linear-signature": sig}
    if extra_headers:
        headers.update(extra_headers)
    return client.post("/webhook", content=body, headers=headers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set environment variables required by the app."""
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", _TEST_SECRET)
    monkeypatch.setenv("LINEAR_EPIC_TYPES", "Project")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a FastAPI test client with a fresh in-memory dedup store."""
    store = DedupStore(db_path=tmp_path / "test_dedup.db")
    _reset_dedup_store(store)
    app = create_app()
    yield TestClient(app)
    _reset_dedup_store(None)
    store.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinearRelayHealth:
    """Tests for the health endpoint."""

    def test_health(self, client: TestClient) -> None:
        """Health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "linear-relay"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinearRelaySignature:
    """Tests for HMAC signature verification."""

    def test_missing_signature_returns_401(self, client: TestClient) -> None:
        """Missing Linear-Signature header returns 401."""
        body = json.dumps(_PROJECT_COMPLETED_PAYLOAD).encode()
        response = client.post(
            "/webhook",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 401

    def test_wrong_signature_returns_401(self, client: TestClient) -> None:
        """Wrong signature returns 401."""
        response = _post(client, _PROJECT_COMPLETED_PAYLOAD, sig_override="badsig")
        assert response.status_code == 401

    def test_valid_signature_passes(self, client: TestClient) -> None:
        """Valid HMAC signature passes authentication."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ):
            response = _post(client, _PROJECT_COMPLETED_PAYLOAD)
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# Filter logic — representative fixture payloads
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinearRelayFilter:
    """Tests for the type and state filter logic."""

    def test_project_completed_is_published(self, client: TestClient) -> None:
        """Project + completed → published (primary use case)."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, _PROJECT_COMPLETED_PAYLOAD)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "published"
            mock_publish.assert_called_once()

    def test_project_not_completed_is_skipped(self, client: TestClient) -> None:
        """Project with non-completed state is skipped (no 4xx)."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, _PROJECT_STARTED_PAYLOAD)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "skipped"
            assert data["reason"] == "state_not_completed"
            mock_publish.assert_not_called()

    def test_issue_type_is_skipped(self, client: TestClient) -> None:
        """Issue type is not in LINEAR_EPIC_TYPES → skipped."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, _ISSUE_PAYLOAD)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "skipped"
            assert data["reason"] == "type_not_matched"
            mock_publish.assert_not_called()

    def test_initiative_skipped_when_not_in_types(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Initiative type is skipped when LINEAR_EPIC_TYPES=Project only."""
        monkeypatch.setenv("LINEAR_EPIC_TYPES", "Project")
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, _INITIATIVE_COMPLETED_PAYLOAD)
            assert response.status_code == 200
            assert response.json()["status"] == "skipped"
            mock_publish.assert_not_called()

    def test_initiative_published_when_in_types(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Initiative type is published when LINEAR_EPIC_TYPES includes Initiative."""
        monkeypatch.setenv("LINEAR_EPIC_TYPES", "Project,Initiative")
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, _INITIATIVE_COMPLETED_PAYLOAD)
            assert response.status_code == 200
            assert response.json()["status"] == "published"
            mock_publish.assert_called_once()

    def test_missing_state_field_is_skipped(self, client: TestClient) -> None:
        """Payload without data.state is treated as non-completed → skipped."""
        payload = dict(_PROJECT_COMPLETED_PAYLOAD)
        payload["data"] = {"id": "proj-nostatetest"}  # no 'state' key
        payload["webhookId"] = "wh-nostate"
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            response = _post(client, payload)
            assert response.status_code == 200
            assert response.json()["status"] == "skipped"
            mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinearRelayDedup:
    """Tests for webhook deduplication by webhookId."""

    def test_duplicate_webhook_returns_409(self, client: TestClient) -> None:
        """Second request with same webhookId returns 409."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ):
            # First call: published
            r1 = _post(client, _PROJECT_COMPLETED_PAYLOAD)
            assert r1.status_code == 200
            assert r1.json()["status"] == "published"

            # Second call: same webhookId → 409
            r2 = _post(client, _PROJECT_COMPLETED_PAYLOAD)
            assert r2.status_code == 409

    def test_different_webhook_ids_are_independent(
        self, client: TestClient
    ) -> None:
        """Two requests with different webhookIds are both published."""
        payload1 = dict(_PROJECT_COMPLETED_PAYLOAD)
        payload2 = dict(_PROJECT_COMPLETED_PAYLOAD)
        payload2["webhookId"] = "wh-different-id"

        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            r1 = _post(client, payload1)
            r2 = _post(client, payload2)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert mock_publish.call_count == 2


# ---------------------------------------------------------------------------
# Publish output
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinearRelayPublish:
    """Tests for the publish output shape."""

    def test_response_contains_expected_fields(self, client: TestClient) -> None:
        """Published response includes webhookId, org_id, epic_id."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ):
            response = _post(client, _PROJECT_COMPLETED_PAYLOAD)
            data = response.json()
            assert data["status"] == "published"
            assert data["webhookId"] == "wh-project-completed"
            assert data["org_id"] == "org-xyz"
            assert data["epic_id"] == "proj-abc123"

    def test_publish_helper_called_with_org_and_epic(
        self, client: TestClient
    ) -> None:
        """_publish is called with correct org_id and epic_id."""
        with patch(
            "omniclaude.services.linear_relay.app._publish",
            new_callable=AsyncMock,
        ) as mock_publish:
            _post(client, _PROJECT_COMPLETED_PAYLOAD)
            mock_publish.assert_called_once_with("org-xyz", "proj-abc123")
