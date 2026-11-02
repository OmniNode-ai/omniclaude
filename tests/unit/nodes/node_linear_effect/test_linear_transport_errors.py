# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Endpoint transport failures and ticket read/status behavior (OMN-21791)."""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import Mock, patch

import pytest

from omniclaude.nodes.node_linear_effect.handlers import handler_linear_ticketing as api
from omniclaude.nodes.node_linear_effect.models import (
    LinearOperation,
    LinearResultStatus,
    ModelLinearEndpoint,
    ModelLinearRequest,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("body", [[], {"errors": ["denied"]}, {"data": []}])
def test_invalid_graphql_response_closes_connection(monkeypatch, body) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "test-key")
    endpoint = ModelLinearEndpoint(host="injected.test", path="/g", timeout_seconds=2)
    with patch.object(api.http.client, "HTTPSConnection") as factory:
        connection = factory.return_value
        connection.getresponse.return_value = io.StringIO(json.dumps(body))
        with pytest.raises(api.LinearApiError):
            api.http_transport(endpoint)("query { a }", {})
        connection.close.assert_called_once()


@pytest.mark.parametrize("error", [TimeoutError(), ValueError(), OSError()])
def test_transport_error_closes_connection_and_hides_key(monkeypatch, error) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "secret-key")
    endpoint = ModelLinearEndpoint(host="injected.test", path="/g", timeout_seconds=2)
    with patch.object(api.http.client, "HTTPSConnection") as factory:
        connection = factory.return_value
        connection.request.side_effect = error
        with pytest.raises(api.LinearApiError) as caught:
            api.http_transport(endpoint)("query { a }", {})
        assert "secret-key" not in str(caught.value)
        connection.close.assert_called_once()


def test_missing_key_does_not_open_connection(monkeypatch) -> None:
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    endpoint = ModelLinearEndpoint.from_contract()
    with patch.object(api.http.client, "HTTPSConnection") as factory:
        with pytest.raises(api.LinearApiError, match="no Linear credential"):
            api.http_transport(endpoint)("query { a }", {})
        factory.assert_not_called()


@pytest.mark.parametrize("operation", list(LinearOperation))
def test_missing_operation_fields_are_rejected(operation) -> None:
    transport = Mock()
    handler = api.HandlerLinearApi(transport=transport)
    result = asyncio.run(handler.handle(ModelLinearRequest(operation=operation)))
    assert result.status is LinearResultStatus.FAILED
    transport.assert_not_called()


@pytest.mark.parametrize("issue", [None, {}, {"identifier": "OMN-2"}])
def test_ticket_get_rejects_wrong_or_missing_issue(issue) -> None:
    handler = api.HandlerLinearApi(transport=Mock(return_value={"issue": issue}))
    result = asyncio.run(
        handler.handle(
            ModelLinearRequest(operation=LinearOperation.TICKET_GET, ticket_id="OMN-1")
        )
    )
    assert result.status is LinearResultStatus.FAILED
    assert "no such ticket" in result.error


def test_ticket_get_returns_state_and_description() -> None:
    issue = {"identifier": "OMN-1", "state": {"name": "Todo"}, "description": "text"}
    handler = api.HandlerLinearApi(transport=Mock(return_value={"issue": issue}))
    result = asyncio.run(
        handler.handle(
            ModelLinearRequest(operation=LinearOperation.TICKET_GET, ticket_id="OMN-1")
        )
    )
    assert result.status is LinearResultStatus.SUCCESS
    assert result.ticket_state == "Todo"
    assert json.loads(result.output)["description"] == "text"


@pytest.mark.parametrize(
    ("allowed", "states", "expected"),
    [
        (False, [], LinearResultStatus.FAILED),
        (True, [], LinearResultStatus.FAILED),
        (True, [{"id": "state-1", "name": "Todo"}], LinearResultStatus.SUCCESS),
    ],
)
def test_status_update_requires_guard_and_matching_state(
    allowed, states, expected
) -> None:
    transport = Mock(
        return_value={
            "issue": {"identifier": "OMN-1", "team": {"states": {"nodes": states}}}
        }
    )
    handler = api.HandlerLinearApi(
        transport=transport, guard_decision=lambda call: (allowed, "guard verdict")
    )
    result = asyncio.run(
        handler.handle(
            ModelLinearRequest(
                operation=LinearOperation.TICKET_UPDATE_STATUS,
                ticket_id="OMN-1",
                status="todo",
            )
        )
    )
    assert result.status is expected
    if expected is LinearResultStatus.SUCCESS:
        assert transport.call_args.args[1]["input"] == {"stateId": "state-1"}
    else:
        assert transport.call_count == int(allowed)
