# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Channel orchestration handler.

Receives a normalized channel message, processes it through the assistant
pipeline, and returns an orchestrator output with the generated reply.

MVP implementation: echo-style response to prove the pipeline works.
Real LLM integration will be wired in a follow-up ticket.

Related:
    - OMN-7186: Channel orchestrator node
    - OmniClaw MVP Part 1: Prerequisites
"""

from __future__ import annotations

import logging
from uuid import uuid4

from omnibase_core.models.dispatch.model_handler_output import ModelHandlerOutput

from omniclaude.nodes.node_channel_orchestrator.models.model_channel_message_processed import (
    ModelChannelMessageProcessed,
)
from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_input import (
    ModelChannelOrchestratorInput,
)
from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_output import (
    ModelChannelOrchestratorOutput,
)
from omniclaude.nodes.node_channel_orchestrator.models.model_channel_reply_requested import (
    ModelChannelReplyRequested,
)
from omniclaude.shared.models.model_channel_envelope import (
    ModelChannelEnvelope,  # noqa: TC002
)

logger = logging.getLogger(__name__)


def handle_channel_orchestrate(
    envelope: ModelChannelEnvelope,
) -> ModelChannelOrchestratorOutput:
    """Process a channel message and produce a reply.

    MVP: produces a structured echo response that proves the full pipeline
    is connected. The delegation/LLM integration will replace this in the
    next phase.

    Args:
        envelope: Normalized channel message from any adapter.

    Returns:
        Orchestrator output with reply text and routing metadata.
    """
    logger.info(
        "Channel orchestrate: channel_type=%s correlation_id=%s",
        envelope.channel_type,
        envelope.correlation_id,
    )

    reply_text = (
        f"[OmniClaw] Received your message on {envelope.channel_type.value}: "
        f"{envelope.message_text!r}"
    )

    return ModelChannelOrchestratorOutput(
        reply_text=reply_text,
        channel_id=envelope.channel_id,
        channel_type=envelope.channel_type,
        reply_to=envelope.message_id,
        thread_id=envelope.thread_id,
        correlation_id=envelope.correlation_id,
    )


class HandlerChannelOrchestrate:
    """Def-B handler the node contract routes ``channel.orchestrate`` to.

    The runtime imports this class by the name in ``contract.yaml``, builds the
    request model from the ``handle`` annotation, and publishes each event in
    the returned output on the topic ``published_events`` gives for its class
    name minus the ``Model`` prefix. The events ride in a ``ModelHandlerOutput``
    because a bare list of events is dropped unless the runtime's multi-event
    publish seam (``ONEX_MULTI_EVENT_PUBLISH_SEAM``) is switched on.
    """

    def handle(
        self, request: ModelChannelOrchestratorInput
    ) -> ModelHandlerOutput[None]:
        """Turn one inbound channel message into its two declared events.

        Args:
            request: Normalized channel message from any adapter.

        Returns:
            Orchestrator output holding one reply-requested event for the reply
            dispatcher and one message-processed observability event, both
            carrying the message's correlation id.
        """
        output = handle_channel_orchestrate(request)
        events = (
            ModelChannelReplyRequested.model_validate(output),
            ModelChannelMessageProcessed(
                channel_id=request.channel_id,
                channel_type=request.channel_type,
                message_id=request.message_id,
                received_at=request.timestamp,
                reply_requested=True,
                correlation_id=request.correlation_id,
            ),
        )
        return ModelHandlerOutput.for_orchestrator(
            input_envelope_id=uuid4(),
            correlation_id=request.correlation_id,
            handler_id="node_channel_orchestrator.channel_orchestrate",
            events=events,
        )
