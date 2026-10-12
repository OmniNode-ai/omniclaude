# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The channel node contracts must resolve to handlers a runtime can load (OMN-21057).

The golden chain test wires the handler *functions* in process, so it never
reads the contracts. A runtime does: it imports the module named in
``handler_routing`` and fails the whole boot with CLASS_NOT_FOUND when the
named class is absent, then publishes whatever the def-B ``handle()`` returns
on the topic its ``published_events`` map gives for that model's short name.
These tests read the contracts the way the runtime does.
"""

from __future__ import annotations

import importlib
import typing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from omnibase_core.enums.enum_node_kind import EnumNodeKind
from omnibase_core.models.dispatch.model_handler_output import ModelHandlerOutput
from pydantic import BaseModel

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_input import (
    ModelChannelOrchestratorInput,
)

_NODES_ROOT = Path(__file__).resolve().parents[3] / "src" / "omniclaude" / "nodes"
_ORCHESTRATOR_CONTRACT = _NODES_ROOT / "node_channel_orchestrator" / "contract.yaml"
_DISPATCHER_CONTRACT = _NODES_ROOT / "node_channel_reply_dispatcher" / "contract.yaml"

_REPLY_REQUESTED_TOPIC = "onex.evt.omniclaw.channel-reply-requested.v1"
_MESSAGE_PROCESSED_TOPIC = "onex.evt.omniclaw.channel-message-processed.v1"


def _load(path: Path) -> dict[str, typing.Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _routed_handlers(contract_path: Path) -> list[tuple[str, str]]:
    routing = _load(contract_path)["handler_routing"]
    return [
        (entry["handler"]["module"], entry["handler"]["name"])
        for entry in routing["handlers"]
    ]


def _envelope(**overrides: object) -> ModelChannelOrchestratorInput:
    defaults: dict[str, object] = {
        "channel_id": "synthetic-room",
        "channel_type": EnumChannelType.DISCORD,
        "sender_id": "synthetic-sender",
        "message_text": "synthetic ping",
        "message_id": "synthetic-msg-1",
        "thread_id": "synthetic-thread-1",
        "timestamp": datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC),
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelOrchestratorInput.model_validate(defaults)


@pytest.mark.unit
@pytest.mark.parametrize(
    "contract_path",
    [_ORCHESTRATOR_CONTRACT, _DISPATCHER_CONTRACT],
    ids=["orchestrator", "reply_dispatcher"],
)
def test_contract_handler_class_exists_and_is_def_b(contract_path: Path) -> None:
    """Every handler the contract routes to is a class with a ``handle`` method."""
    handlers = _routed_handlers(contract_path)
    assert handlers, f"{contract_path} routes no handler"
    for module_path, class_name in handlers:
        module = importlib.import_module(module_path)
        handler_cls = getattr(module, class_name, None)
        assert isinstance(handler_cls, type), (
            f"CLASS_NOT_FOUND: {module_path}.{class_name} named by "
            f"{contract_path.parent.name}/contract.yaml does not exist"
        )
        assert callable(getattr(handler_cls, "handle", None)), (
            f"{class_name} has no handle() dispatch entrypoint"
        )


@pytest.mark.unit
def test_orchestrator_handle_declares_the_contract_input_model() -> None:
    """The runtime builds the request from handle()'s annotation, not the contract."""
    from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
        HandlerChannelOrchestrate,
    )

    hints = typing.get_type_hints(HandlerChannelOrchestrate.handle)
    assert hints["request"] is ModelChannelOrchestratorInput


@pytest.mark.unit
def test_orchestrator_emits_exactly_the_two_declared_events() -> None:
    """One inbound message yields one reply-requested and one message-processed."""
    from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
        HandlerChannelOrchestrate,
    )

    request = _envelope()
    events = HandlerChannelOrchestrate().handle(request).events

    published = {
        entry["event_type"]: entry["topic"]
        for entry in _load(_ORCHESTRATOR_CONTRACT)["published_events"]
    }
    assert published == {
        "ChannelReplyRequested": _REPLY_REQUESTED_TOPIC,
        "ChannelMessageProcessed": _MESSAGE_PROCESSED_TOPIC,
    }

    # The runtime resolves an emitted model's topic by its class name minus "Model".
    short_names = sorted(type(event).__name__.removeprefix("Model") for event in events)
    assert short_names == sorted(published), short_names
    assert {event.correlation_id for event in events} == {request.correlation_id}


@pytest.mark.unit
def test_orchestrator_events_ride_in_handler_output_not_a_bare_list() -> None:
    """A bare list is dropped unless the multi-event seam flag is on in the runtime."""
    from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
        HandlerChannelOrchestrate,
    )

    output = HandlerChannelOrchestrate().handle(_envelope())
    assert isinstance(output, ModelHandlerOutput)
    assert output.node_kind is EnumNodeKind.ORCHESTRATOR
    assert len(output.events) == 2


@pytest.mark.unit
def test_message_processed_event_carries_no_message_content() -> None:
    """The processed event is observability: no sender, no text."""
    from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
        HandlerChannelOrchestrate,
    )

    events = HandlerChannelOrchestrate().handle(_envelope()).events
    processed = next(
        event
        for event in events
        if type(event).__name__ == "ModelChannelMessageProcessed"
    )
    dumped = processed.model_dump_json()
    assert "synthetic-sender" not in dumped
    assert "synthetic ping" not in dumped


@pytest.mark.unit
def test_reply_requested_event_feeds_the_dispatcher() -> None:
    """The reply-requested payload is what the dispatcher's request model accepts."""
    from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
        HandlerChannelOrchestrate,
    )
    from omniclaude.nodes.node_channel_reply_dispatcher.handlers.handler_dispatch_reply import (
        HandlerDispatchReply,
    )
    from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
        ModelChannelReply,
    )

    request = _envelope()
    reply_requested = next(
        event
        for event in HandlerChannelOrchestrate().handle(request).events
        if type(event).__name__ == "ModelChannelReplyRequested"
    )
    reply = ModelChannelReply.model_validate(reply_requested.model_dump(mode="json"))
    result = HandlerDispatchReply().handle(reply)

    assert result.routed is True
    assert reply.correlation_id == request.correlation_id
    assert reply.reply_to == "synthetic-msg-1"


@pytest.mark.unit
def test_reply_requested_event_declares_the_dispatcher_request_fields() -> None:
    """The event declares its own fields and they equal the dispatcher request's."""
    from omniclaude.nodes.node_channel_orchestrator.models.model_channel_reply_requested import (
        ModelChannelReplyRequested,
    )
    from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
        ModelChannelReply,
    )

    assert ModelChannelReplyRequested.__bases__ == (BaseModel,)
    assert set(ModelChannelReplyRequested.model_fields) == set(
        ModelChannelReply.model_fields
    )
