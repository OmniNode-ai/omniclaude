# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Linear endpoint comes from the node contract or an injected value (OMN-21791)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_linear_effect.handlers import handler_linear_ticketing
from omniclaude.nodes.node_linear_effect.handlers.handler_linear_ticketing import (
    HandlerLinearApi,
)
from omniclaude.nodes.node_linear_effect.models import ModelLinearEndpoint

pytestmark = pytest.mark.unit


def test_endpoint_is_read_from_packaged_contract() -> None:
    contract = Path(handler_linear_ticketing.__file__).parents[1] / "contract.yaml"
    endpoint = ModelLinearEndpoint.from_contract()
    assert f"host: {endpoint.host}" in contract.read_text(encoding="utf-8")
    assert endpoint.path.startswith("/")
    assert endpoint.timeout_seconds > 0


def test_contract_without_endpoint_fails(tmp_path: Path) -> None:
    bare = tmp_path / "contract.yaml"
    bare.write_text("name: x\n", encoding="utf-8")
    with pytest.raises(KeyError):
        ModelLinearEndpoint.from_contract(bare)


def test_invalid_endpoint_values_fail_validation() -> None:
    with pytest.raises(ValidationError):
        ModelLinearEndpoint(host="", path="/g", timeout_seconds=1)
    with pytest.raises(ValidationError):
        ModelLinearEndpoint(host="h", path="g", timeout_seconds=1)
    with pytest.raises(ValidationError):
        ModelLinearEndpoint(host="h", path="/g", timeout_seconds=0)


def test_injected_endpoint_reaches_the_connection(monkeypatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "k")
    endpoint = ModelLinearEndpoint(host="injected.test", path="/inj", timeout_seconds=3)
    handler = HandlerLinearApi(endpoint=endpoint)
    with mock.patch.object(
        handler_linear_ticketing.http.client, "HTTPSConnection"
    ) as connection_class:
        connection = connection_class.return_value
        connection.getresponse.return_value.read.return_value = b'{"data": {"a": 1}}'
        data = handler._transport("query { a }", {})
    assert data == {"a": 1}
    connection_class.assert_called_once_with("injected.test", timeout=3)
    assert connection.request.call_args.args[:2] == ("POST", "/inj")
