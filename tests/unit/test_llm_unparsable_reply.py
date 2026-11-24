# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-26353: an unparsable LLM reply is a typed result, never None.

Falsifiers named by the ticket:

* ``-k llm_unparsable_reply_typed``: each of the three sites returns a
  ``ModelLlmParseResult`` for an unparsable reply.
* ``-k llm_unparsable_reply_callers``: each caller branches on the typed result
  and none treats an unparsable reply as no answer (``is None``).
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from omniclaude.enums.enum_llm_parse_status import EnumLlmParseStatus
from omniclaude.lib.utils.consensus import quorum as quorum_module
from omniclaude.lib.utils.consensus.quorum import (
    AIQuorum,
    ModelConfig,
    ModelProvider,
)
from omniclaude.models.model_llm_parse_result import ModelLlmParseResult
from omniclaude.nodes.node_agent_routing_compute import handler_routing_llm as routing
from omniclaude.nodes.node_agent_routing_compute.handler_routing_llm import (
    HandlerRoutingLlm,
    _parse_agent_from_response,
)
from omniclaude.nodes.node_transition_selector_effect.node import (
    NodeTransitionSelectorEffect,
)

pytestmark = pytest.mark.unit

GARBAGE = "I cannot decide, sorry"


def _quorum_model() -> ModelConfig:
    return ModelConfig(
        name="m1",
        provider=ModelProvider.OPENAI_COMPATIBLE,
        endpoint="http://127.0.0.1:1",
        weight=1.0,
    )


def _http_client_returning(content: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={"choices": [{"message": {"content": content}}]}
    )
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------- typed (AC1)


def test_llm_unparsable_reply_typed_model_shape() -> None:
    result = ModelLlmParseResult[str].unparsable(raw_reply=GARBAGE, reason="no name")
    assert result.status is EnumLlmParseStatus.UNPARSABLE
    assert result.value is None
    assert result.is_parsed is False
    parsed = ModelLlmParseResult[int].parsed(3)
    assert parsed.status is EnumLlmParseStatus.PARSED
    assert parsed.value == 3
    assert parsed.is_parsed is True


def test_llm_unparsable_reply_typed_routing_site() -> None:
    result = _parse_agent_from_response(GARBAGE, {"agent-debugger"})
    assert isinstance(result, ModelLlmParseResult)
    assert result.status is EnumLlmParseStatus.UNPARSABLE
    assert GARBAGE in result.raw_reply
    ok = _parse_agent_from_response("agent-debugger", {"agent-debugger"})
    assert isinstance(ok, ModelLlmParseResult)
    assert ok.value == "agent-debugger"


@pytest.mark.asyncio
async def test_llm_unparsable_reply_typed_routing_ask_llm() -> None:
    handler = HandlerRoutingLlm(llm_url="http://127.0.0.1:1", model_name="m")
    client = _http_client_returning(GARBAGE)
    candidate = MagicMock()
    candidate.agent_name = "agent-debugger"
    candidate.match_reason = "r"
    with patch.object(routing.httpx, "AsyncClient", return_value=client):
        selection, _, _, _ = await handler._ask_llm(
            candidates=[candidate],
            prompt="p",
            agent_names={"agent-debugger"},
            correlation_id=uuid4(),
        )
    assert isinstance(selection, ModelLlmParseResult)
    assert selection.status is EnumLlmParseStatus.UNPARSABLE


@pytest.mark.parametrize(
    "raw", ["", "not json", '{"selected": "abc"}', '{"selected": true}', "[1]"]
)
def test_llm_unparsable_reply_typed_selector_site(raw: str) -> None:
    result = NodeTransitionSelectorEffect._parse_selection(raw)
    assert isinstance(result, ModelLlmParseResult)
    assert result.status is EnumLlmParseStatus.UNPARSABLE
    assert result.value is None


def test_llm_unparsable_reply_typed_selector_parsed() -> None:
    result = NodeTransitionSelectorEffect._parse_selection('{"selected": 2}')
    assert isinstance(result, ModelLlmParseResult)
    assert result.value == 2


@pytest.mark.asyncio
async def test_llm_unparsable_reply_typed_quorum_site() -> None:
    quorum = AIQuorum(models=[_quorum_model()])
    client = _http_client_returning(GARBAGE)
    with patch.object(quorum_module.httpx, "AsyncClient", return_value=client):
        _model, outcome = await quorum._score_with_openai_compatible(
            _quorum_model(), "prompt"
        )
    assert isinstance(outcome, ModelLlmParseResult)
    assert outcome.status is EnumLlmParseStatus.UNPARSABLE
    assert GARBAGE in outcome.raw_reply


# ------------------------------------------------------------- callers (AC2)


def _is_none_compare_on(node: ast.AST, names: set[str]) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    left = node.left
    if not (isinstance(left, ast.Name) and left.id in names):
        return False
    return any(isinstance(op, ast.Is | ast.IsNot) for op in node.ops) and any(
        isinstance(c, ast.Constant) and c.value is None for c in node.comparators
    )


def _none_checks(func: Any, names: set[str]) -> list[int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return [n.lineno for n in ast.walk(tree) if _is_none_compare_on(n, names)]


def test_llm_unparsable_reply_callers_no_is_none_check() -> None:
    offenders = {
        "compute_routing": _none_checks(
            HandlerRoutingLlm.compute_routing, {"selected_agent", "selection"}
        ),
        "select": _none_checks(
            NodeTransitionSelectorEffect.select, {"selected_index", "selection"}
        ),
        "_calculate_consensus": _none_checks(
            AIQuorum._calculate_consensus, {"score_data", "outcome"}
        ),
    }
    assert offenders == {k: [] for k in offenders}


@pytest.mark.asyncio
async def test_llm_unparsable_reply_callers_routing_names_unparsable_reason() -> None:
    from tests.routing.test_handler_routing_llm import (
        _make_agent,
        _make_request,
    )

    handler = HandlerRoutingLlm(llm_url="http://127.0.0.1:1", model_name="m")
    agents = (
        _make_agent("agent-debugger", triggers=("debug",)),
        _make_agent("general-purpose", triggers=("poly",)),
    )
    request = _make_request("debug this issue", agents)
    unparsable = ModelLlmParseResult[str].unparsable(raw_reply=GARBAGE, reason="x")
    unavailable = ModelLlmParseResult[str].unavailable(reason="timeout")
    with patch.object(
        handler, "_ask_llm", new_callable=AsyncMock, return_value=(unparsable, 1, 2, 3)
    ):
        bad = await handler.compute_routing(request)
    with patch.object(
        handler, "_ask_llm", new_callable=AsyncMock, return_value=(unavailable, 0, 0, 0)
    ):
        down = await handler.compute_routing(request)
    assert bad.fallback_reason is not None and "unrecognised" in bad.fallback_reason
    assert down.fallback_reason is not None and "unavailable" in down.fallback_reason
    assert bad.fallback_reason != down.fallback_reason


@pytest.mark.asyncio
async def test_llm_unparsable_reply_callers_quorum_does_not_vote_half() -> None:
    models = [_quorum_model()]
    quorum = AIQuorum(models=models)
    unparsable = ModelLlmParseResult[dict[str, Any]].unparsable(
        raw_reply=GARBAGE, reason="not json"
    )
    result = quorum._calculate_consensus([(models[0], unparsable)])
    # An unparsable reply is not a 0.5 vote: it does not participate, and the
    # reply is named in the reasoning.
    assert result.model_scores == {}
    assert result.recommendation == "FAIL_PARTICIPATION"
    assert "unparsable" in result.model_reasoning["m1"]
