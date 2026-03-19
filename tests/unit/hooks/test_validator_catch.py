# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for ModelValidatorCatchPayload and validator catch events (OMN-5549)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.schemas import ModelValidatorCatchPayload

pytestmark = pytest.mark.unit


class TestModelValidatorCatchPayload:
    """Test ModelValidatorCatchPayload model."""

    def _make_payload(self, **overrides: object) -> ModelValidatorCatchPayload:
        defaults = {
            "session_id": "sess-001",
            "validator_type": "pre_commit",
            "validator_name": "ruff",
            "catch_description": "Import sorting violation in module.py",
            "severity": "error",
            "timestamp_iso": "2026-03-19T12:00:00.000Z",
        }
        defaults.update(overrides)
        return ModelValidatorCatchPayload(**defaults)  # type: ignore[arg-type]

    def test_valid_payload(self) -> None:
        payload = self._make_payload()
        assert payload.session_id == "sess-001"
        assert payload.validator_type == "pre_commit"
        assert payload.validator_name == "ruff"
        assert payload.severity == "error"

    def test_serializes_correctly(self) -> None:
        payload = self._make_payload()
        data = payload.model_dump(mode="json")
        assert data["validator_type"] == "pre_commit"
        assert data["validator_name"] == "ruff"
        assert data["catch_description"] == "Import sorting violation in module.py"
        assert data["severity"] == "error"
        assert data["timestamp_iso"] == "2026-03-19T12:00:00.000Z"

    def test_frozen(self) -> None:
        payload = self._make_payload()
        with pytest.raises(Exception):
            payload.severity = "warning"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            self._make_payload(extra_field="not_allowed")

    def test_poly_enforcer_type(self) -> None:
        payload = self._make_payload(
            validator_type="poly_enforcer",
            validator_name="context-scope-auditor",
            catch_description="Tool scope violation: Bash not in [Read, Write]",
            severity="error",
        )
        assert payload.validator_type == "poly_enforcer"
        assert payload.validator_name == "context-scope-auditor"

    def test_warning_severity(self) -> None:
        payload = self._make_payload(severity="warning")
        assert payload.severity == "warning"

    def test_max_description_length(self) -> None:
        long_desc = "x" * 500
        payload = self._make_payload(catch_description=long_desc)
        assert len(payload.catch_description) == 500

    def test_description_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_payload(catch_description="x" * 501)

    def test_empty_session_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make_payload(session_id="")
