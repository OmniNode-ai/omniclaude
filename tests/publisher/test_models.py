"""Tests for omniclaude.publisher.models."""

from __future__ import annotations

import pytest

from omniclaude.publisher.publisher_models import (
    ModelDaemonEmitRequest,
    ModelDaemonErrorResponse,
    ModelDaemonPingRequest,
    ModelDaemonPingResponse,
    ModelDaemonQueuedResponse,
    parse_daemon_request,
    parse_daemon_response,
)


class TestRequestModels:
    def test_ping_request(self) -> None:
        req = ModelDaemonPingRequest()
        assert req.command == "ping"
        data = req.model_dump()
        assert data == {"command": "ping"}

    def test_emit_request(self) -> None:
        req = ModelDaemonEmitRequest(
            event_type="prompt.submitted",
            payload={"session_id": "abc"},
        )
        assert req.event_type == "prompt.submitted"

    def test_emit_request_default_payload(self) -> None:
        req = ModelDaemonEmitRequest(event_type="test.event")
        assert req.payload == {}


class TestResponseModels:
    def test_ping_response(self) -> None:
        resp = ModelDaemonPingResponse(queue_size=5, spool_size=10)
        assert resp.status == "ok"
        assert resp.queue_size == 5

    def test_queued_response(self) -> None:
        resp = ModelDaemonQueuedResponse(event_id="abc-123")
        assert resp.status == "queued"
        assert resp.event_id == "abc-123"

    def test_error_response(self) -> None:
        resp = ModelDaemonErrorResponse(reason="Unknown event type")
        assert resp.status == "error"


class TestParseDaemonRequest:
    def test_parse_ping(self) -> None:
        req = parse_daemon_request({"command": "ping"})
        assert isinstance(req, ModelDaemonPingRequest)

    def test_parse_emit(self) -> None:
        req = parse_daemon_request(
            {"event_type": "session.started", "payload": {"session_id": "abc"}}
        )
        assert isinstance(req, ModelDaemonEmitRequest)
        assert req.event_type == "session.started"

    def test_parse_invalid(self) -> None:
        with pytest.raises(ValueError, match="must contain either"):
            parse_daemon_request({"unknown": "field"})


class TestParseDaemonResponse:
    def test_parse_ok(self) -> None:
        resp = parse_daemon_response({"status": "ok", "queue_size": 0, "spool_size": 0})
        assert isinstance(resp, ModelDaemonPingResponse)

    def test_parse_queued(self) -> None:
        resp = parse_daemon_response({"status": "queued", "event_id": "abc"})
        assert isinstance(resp, ModelDaemonQueuedResponse)

    def test_parse_error(self) -> None:
        resp = parse_daemon_response({"status": "error", "reason": "bad"})
        assert isinstance(resp, ModelDaemonErrorResponse)

    def test_parse_unknown_status(self) -> None:
        with pytest.raises(ValueError, match="Unknown response status"):
            parse_daemon_response({"status": "invalid"})
