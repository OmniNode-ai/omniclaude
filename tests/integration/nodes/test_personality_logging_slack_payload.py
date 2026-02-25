# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Integration test: emit a LogEvent → verify Slack Block Kit payload structure (OMN-2575).

This test verifies the full pipeline:
  LogEvent → NodePersonalityLoggingEffect → SlackSink → Block Kit payload

The Slack webhook POST is intercepted using unittest.mock to avoid external I/O.
The test verifies the Block Kit payload structure, not network delivery.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.nodes.node_personality_logging_effect.models.model_log_event import (
    EnumLogSeverity,
    ModelLogEvent,
    ModelLogMetrics,
    ModelLogPolicy,
    ModelLogTrace,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_logging_config import (
    ModelLoggingConfig,
    ModelQuietHours,
    ModelRoutingRule,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_rendered_log import (
    ModelRenderedLog,
)
from omniclaude.nodes.node_personality_logging_effect.node import (
    NodePersonalityLoggingEffect,
)
from omniclaude.nodes.node_personality_logging_effect.sinks.sink_slack import SlackSink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    severity: EnumLogSeverity = EnumLogSeverity.ERROR,
    event_name: str = "db.query.slow",
    message: str = "Query exceeded threshold",
    attrs: dict | None = None,
    metrics: ModelLogMetrics | None = None,
) -> ModelLogEvent:
    return ModelLogEvent(
        severity=severity,
        event_name=event_name,
        message=message,
        attrs=attrs or {"query": "SELECT * FROM orders", "duration_ms": 1500},
        metrics=metrics,
        trace=ModelLogTrace(),
        policy=ModelLogPolicy(),
    )


# ---------------------------------------------------------------------------
# Integration: Slack Block Kit payload structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slack_sink_builds_valid_block_kit_payload() -> None:
    """Verify that SlackSink produces a well-formed Block Kit payload."""
    config = ModelLoggingConfig(
        slack_webhook_url="https://hooks.slack.com/services/FAKE/FAKE/FAKE",
        personality_profile="default",
        # Disable quiet hours so the test runs regardless of UTC time
        quiet_hours=ModelQuietHours(start=0, end=0),
    )
    sink = SlackSink(config=config)

    event = _make_event(
        metrics=ModelLogMetrics(cpu=0.75, mem=0.4, queue_depth=10, latency_p95=250.5),
    )
    from omniclaude.nodes.node_personality_logging_effect.personality_adapter import (
        PersonalityAdapter,
    )
    adapter = PersonalityAdapter()
    rendered = adapter.render(event, "default")

    captured_payload: dict[str, Any] = {}

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        sink.emit(rendered)
        # Extract the payload from the actual call
        assert mock_urlopen.called, "urlopen must have been called"
        call_args = mock_urlopen.call_args
        req_arg = call_args[0][0]  # first positional arg is the Request object
        body = req_arg.data.decode("utf-8")
        captured_payload.update(json.loads(body))

    # Must have a "blocks" key
    assert "blocks" in captured_payload, "Block Kit payload must have 'blocks'"
    blocks = captured_payload["blocks"]
    assert isinstance(blocks, list) and len(blocks) >= 2

    # First block: header
    header_block = blocks[0]
    assert header_block["type"] == "header"
    assert "ERROR" in header_block["text"]["text"].upper() or "db.query.slow" in header_block["text"]["text"]

    # Second block: section with rendered message
    section_block = blocks[1]
    assert section_block["type"] == "section"
    assert "text" in section_block

    # Metrics block must be present
    metric_block = next(
        (b for b in blocks if b.get("type") == "section" and "fields" in b), None
    )
    assert metric_block is not None, "Metrics section with fields must be present"
    field_texts = [f["text"] for f in metric_block["fields"]]
    assert any("CPU" in t for t in field_texts), "CPU metric must appear in fields"
    assert any("Mem" in t for t in field_texts), "Memory metric must appear in fields"
    assert any("Queue" in t for t in field_texts), "Queue depth must appear in fields"
    assert any("p95" in t for t in field_texts), "p95 latency must appear in fields"


@pytest.mark.unit
def test_slack_sink_suppresses_during_quiet_hours() -> None:
    """Slack sink must not post during quiet hours."""
    from datetime import UTC, datetime
    from unittest.mock import patch as _patch

    config = ModelLoggingConfig(
        slack_webhook_url="https://hooks.slack.com/services/FAKE/FAKE/FAKE",
    )
    sink = SlackSink(config=config)

    # Force current UTC hour to be inside quiet hours (default 22–08)
    quiet_hour = 23
    fake_now = datetime(2026, 1, 1, quiet_hour, 0, 0, tzinfo=UTC)

    posted = []

    with _patch(
        "omniclaude.nodes.node_personality_logging_effect.sinks.sink_slack.datetime"
    ) as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.UTC = UTC
        with _patch("urllib.request.urlopen") as mock_post:
            event = _make_event()
            from omniclaude.nodes.node_personality_logging_effect.personality_adapter import (
                PersonalityAdapter,
            )
            adapter = PersonalityAdapter()
            rendered = adapter.render(event, "default")
            sink.emit(rendered)
            posted.append(mock_post.called)

    assert not posted[0], "SlackSink must not post during quiet hours"


@pytest.mark.unit
async def test_node_routes_to_slack_and_returns_rendered_log() -> None:
    """Full pipeline: emit → node → slack sink → RenderedLog returned."""
    config = ModelLoggingConfig(
        personality_profile="deadpan",
        slack_webhook_url="https://hooks.slack.com/services/FAKE/FAKE/FAKE",
        routing_rules=[
            ModelRoutingRule(pattern="db.*", sinks=["slack", "stdout"]),
        ],
        # Disable quiet hours so the test runs regardless of UTC time
        quiet_hours=ModelQuietHours(start=0, end=0),
    )
    node = NodePersonalityLoggingEffect(config=config)

    event = _make_event(event_name="db.query.slow")

    with patch("urllib.request.urlopen") as mock_post:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_response

        rendered = await node.process_one(event)

    assert rendered is not None, "process_one must return a RenderedLog"
    assert isinstance(rendered, ModelRenderedLog)
    assert rendered.personality_name == "deadpan"
    assert "severity index" in rendered.rendered_message  # deadpan phrase


@pytest.mark.unit
async def test_node_applies_redaction_in_strict_mode() -> None:
    """strict privacy_mode must redact attrs before rendering."""
    config = ModelLoggingConfig(
        privacy_mode="strict",
        personality_profile="default",
    )
    node = NodePersonalityLoggingEffect(config=config)

    event = ModelLogEvent(
        severity=EnumLogSeverity.INFO,
        event_name="user.login",
        message="User logged in",
        attrs={"password": "hunter2", "user_id": "u123"},
        policy=ModelLogPolicy(redaction_rules=["password"]),
        trace=ModelLogTrace(),
    )

    rendered = await node.process_one(event)

    assert rendered is not None
    # The original_event in RenderedLog should have been through redaction
    assert rendered.original_event.attrs.get("password") == "[REDACTED]"
    assert rendered.original_event.attrs.get("user_id") == "u123"
