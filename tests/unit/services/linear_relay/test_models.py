# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the Linear relay Pydantic models."""

from __future__ import annotations

import pytest

from omniclaude.services.linear_relay.models import (
    LinearEpicClosedCommand,
    LinearWebhookPayload,
)
from omniclaude.services.linear_relay.publisher import compute_command_id


def _make_webhook_payload(**overrides: object) -> dict:
    """Build a minimal valid LinearWebhookPayload dict."""
    base: dict = {
        "action": "update",
        "type": "Project",
        "data": {"id": "epic-abc123", "state": "completed"},
        "organizationId": "org-xyz",
        "webhookId": "wh-001",
        "webhookTimestamp": 1700000000000,
    }
    base.update(overrides)
    return base


@pytest.mark.unit
class TestLinearWebhookPayload:
    """Tests for LinearWebhookPayload parsing."""

    def test_minimal_valid_payload(self) -> None:
        """Parses a minimal valid payload."""
        payload = LinearWebhookPayload(**_make_webhook_payload())
        assert payload.type == "Project"
        assert payload.organizationId == "org-xyz"
        assert payload.webhookId == "wh-001"

    def test_extra_fields_allowed(self) -> None:
        """Extra fields in the payload are accepted (extra='allow')."""
        raw = _make_webhook_payload(unknownField="ignored")
        payload = LinearWebhookPayload(**raw)
        assert payload.type == "Project"

    def test_data_defaults_to_empty_dict(self) -> None:
        """data field defaults to empty dict if omitted."""
        raw = _make_webhook_payload()
        del raw["data"]
        payload = LinearWebhookPayload(**raw)
        assert payload.data == {}

    def test_state_field_accessible(self) -> None:
        """data.state is accessible for filter logic."""
        payload = LinearWebhookPayload(**_make_webhook_payload())
        assert payload.data.get("state") == "completed"

    def test_initiative_type(self) -> None:
        """Initiative type is parsed correctly."""
        payload = LinearWebhookPayload(**_make_webhook_payload(type="Initiative"))
        assert payload.type == "Initiative"


@pytest.mark.unit
class TestLinearEpicClosedCommand:
    """Tests for LinearEpicClosedCommand construction."""

    def test_command_id_format(self) -> None:
        """command_id is 16 hex characters."""
        cmd = LinearEpicClosedCommand(
            command_id=compute_command_id("org-xyz", "epic-abc123"),
            org_id="org-xyz",
            epic_id="epic-abc123",
        )
        assert len(cmd.command_id) == 16
        assert all(c in "0123456789abcdef" for c in cmd.command_id)

    def test_command_id_deterministic(self) -> None:
        """compute_command_id returns the same value for same inputs."""
        id1 = compute_command_id("org-xyz", "epic-abc123")
        id2 = compute_command_id("org-xyz", "epic-abc123")
        assert id1 == id2

    def test_command_id_differs_by_org(self) -> None:
        """compute_command_id differs when org_id differs."""
        id1 = compute_command_id("org-aaa", "epic-abc123")
        id2 = compute_command_id("org-bbb", "epic-abc123")
        assert id1 != id2

    def test_command_id_differs_by_epic(self) -> None:
        """compute_command_id differs when epic_id differs."""
        id1 = compute_command_id("org-xyz", "epic-111")
        id2 = compute_command_id("org-xyz", "epic-222")
        assert id1 != id2

    def test_default_args(self) -> None:
        """Default args contain expected keys for feature-dashboard."""
        cmd = LinearEpicClosedCommand(
            command_id="aabbccdd00112233",
            org_id="org-xyz",
            epic_id="epic-abc123",
        )
        assert cmd.args["mode"] == "ticketize"
        assert cmd.args["output_dir"] == "docs/feature-dashboard"
        assert cmd.args["team"] == "OmniNode"

    def test_schema_version(self) -> None:
        """schema_version defaults to '1.0.0'."""
        cmd = LinearEpicClosedCommand(
            command_id="aabbccdd00112233",
            org_id="org-xyz",
            epic_id="epic-abc123",
        )
        assert cmd.schema_version == "1.0.0"

    def test_message_id_is_uuid(self) -> None:
        """message_id is a valid UUID string."""
        import uuid

        cmd = LinearEpicClosedCommand(
            command_id="aabbccdd00112233",
            org_id="org-xyz",
            epic_id="epic-abc123",
        )
        # Should not raise
        uuid.UUID(cmd.message_id)

    def test_model_dump_json(self) -> None:
        """model_dump(mode='json') produces a serializable dict."""
        cmd = LinearEpicClosedCommand(
            command_id=compute_command_id("org-xyz", "epic-abc123"),
            org_id="org-xyz",
            epic_id="epic-abc123",
        )
        data = cmd.model_dump(mode="json")
        assert data["org_id"] == "org-xyz"
        assert data["epic_id"] == "epic-abc123"
        assert data["command_id"] == compute_command_id("org-xyz", "epic-abc123")
