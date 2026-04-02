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

from omnibase_core.models.channel.model_channel_envelope import (
    ModelChannelEnvelope,  # noqa: TC002
)

from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_output import (
    ModelChannelOrchestratorOutput,
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
        "Channel orchestrate: channel_type=%s sender=%s correlation_id=%s",
        envelope.channel_type,
        envelope.sender_id,
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
