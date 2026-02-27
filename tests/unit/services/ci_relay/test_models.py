# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for CI relay models."""

from __future__ import annotations

import pytest

from omniclaude.services.ci_relay.models import CICallbackPayload, PRStatusEvent


@pytest.mark.unit
class TestCICallbackPayload:
    """Tests for CICallbackPayload model."""

    def test_minimal_payload(self) -> None:
        """Test creating a payload with required fields only."""
        payload = CICallbackPayload(
            repo="OmniNode-ai/omniclaude",
            pr=42,
            conclusion="success",
            sha="abc123def456",
            run_id=12345,
            ref="refs/pull/42/merge",
            head_ref="feature/my-branch",
            base_ref="main",
            workflow_url="https://github.com/OmniNode-ai/omniclaude/actions/runs/12345",
        )
        assert payload.repo == "OmniNode-ai/omniclaude"
        assert payload.pr == 42
        assert payload.conclusion == "success"
        assert payload.jobs == []

    def test_payload_with_jobs(self) -> None:
        """Test payload with job summaries."""
        jobs = [
            {
                "name": "quality",
                "conclusion": "success",
                "url": "https://example.com/1",
            },
            {"name": "tests", "conclusion": "failure", "url": "https://example.com/2"},
        ]
        payload = CICallbackPayload(
            repo="OmniNode-ai/omniclaude",
            pr=42,
            conclusion="failure",
            sha="abc123",
            run_id=12345,
            ref="refs/pull/42/merge",
            head_ref="feature/my-branch",
            base_ref="main",
            workflow_url="https://example.com",
            jobs=jobs,
        )
        assert len(payload.jobs) == 2
        assert payload.jobs[1]["conclusion"] == "failure"

    def test_push_triggered_pr_zero(self) -> None:
        """Test payload with pr=0 for push-triggered workflows."""
        payload = CICallbackPayload(
            repo="OmniNode-ai/omniclaude",
            pr=0,
            conclusion="success",
            sha="abc123",
            run_id=12345,
            ref="refs/heads/main",
            head_ref="",
            base_ref="",
            workflow_url="https://example.com",
        )
        assert payload.pr == 0


@pytest.mark.unit
class TestPRStatusEvent:
    """Tests for PRStatusEvent model."""

    def test_from_callback(self) -> None:
        """Test creating a PRStatusEvent from a CICallbackPayload."""
        payload = CICallbackPayload(
            repo="OmniNode-ai/omniclaude",
            pr=42,
            conclusion="success",
            sha="abc123",
            run_id=12345,
            ref="refs/pull/42/merge",
            head_ref="feature/my-branch",
            base_ref="main",
            workflow_url="https://example.com",
        )
        event = PRStatusEvent.from_callback(payload)

        assert event.repo == "OmniNode-ai/omniclaude"
        assert event.pr == 42
        assert event.conclusion == "success"
        assert event.dedupe_key == "OmniNode-ai/omniclaude:abc123:12345"
        assert event.resolved_pr is None
        assert event.schema_version == "1.0.0"
        assert event.message_id  # Should be auto-generated UUID
        assert event.emitted_at  # Should be auto-generated timestamp

    def test_from_callback_with_resolved_pr(self) -> None:
        """Test creating event with resolved PR for push-triggered workflows."""
        payload = CICallbackPayload(
            repo="OmniNode-ai/omniclaude",
            pr=0,
            conclusion="success",
            sha="abc123",
            run_id=12345,
            ref="refs/heads/main",
            head_ref="",
            base_ref="",
            workflow_url="https://example.com",
        )
        event = PRStatusEvent.from_callback(
            payload,
            resolved_pr=99,
            trace={"correlation_id": "test-123"},
        )

        assert event.pr == 0
        assert event.resolved_pr == 99
        assert event.trace == {"correlation_id": "test-123"}

    def test_dedupe_key_format(self) -> None:
        """Test that dedupe key follows the expected format."""
        payload = CICallbackPayload(
            repo="OmniNode-ai/omnibase_core",
            pr=10,
            conclusion="failure",
            sha="deadbeef",
            run_id=99999,
            ref="refs/pull/10/merge",
            head_ref="fix/bug",
            base_ref="main",
            workflow_url="https://example.com",
        )
        event = PRStatusEvent.from_callback(payload)
        assert event.dedupe_key == "OmniNode-ai/omnibase_core:deadbeef:99999"
