# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the Linear relay signature verifier."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from omniclaude.services.linear_relay.verifier import verify_signature


@pytest.fixture
def _set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the LINEAR_WEBHOOK_SECRET for tests."""
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "test-webhook-secret")


def _make_signature(body: bytes, secret: str = "test-webhook-secret") -> str:
    """Compute the expected HMAC-SHA256 signature."""
    return hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.unit
class TestVerifySignature:
    """Tests for the verify_signature function."""

    def test_valid_signature(self, _set_secret: None) -> None:
        """Valid HMAC-SHA256 signature is accepted."""
        body = b'{"type": "Project", "action": "update"}'
        sig = _make_signature(body)
        assert verify_signature(body, sig) is True

    def test_invalid_signature(self, _set_secret: None) -> None:
        """Wrong signature is rejected."""
        body = b'{"type": "Project", "action": "update"}'
        assert verify_signature(body, "wrong-signature") is False

    def test_tampered_body(self, _set_secret: None) -> None:
        """Signature computed for original body fails on tampered body."""
        original_body = b'{"type": "Project"}'
        sig = _make_signature(original_body)
        tampered_body = b'{"type": "Initiative"}'
        assert verify_signature(tampered_body, sig) is False

    def test_empty_body(self, _set_secret: None) -> None:
        """Empty body with valid signature is accepted."""
        body = b""
        sig = _make_signature(body)
        assert verify_signature(body, sig) is True

    def test_missing_secret_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing LINEAR_WEBHOOK_SECRET returns False (does not raise)."""
        monkeypatch.delenv("LINEAR_WEBHOOK_SECRET", raising=False)
        body = b"some body"
        assert verify_signature(body, "any-signature") is False

    def test_empty_secret_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty LINEAR_WEBHOOK_SECRET returns False (does not raise)."""
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "")
        body = b"some body"
        assert verify_signature(body, "any-signature") is False
