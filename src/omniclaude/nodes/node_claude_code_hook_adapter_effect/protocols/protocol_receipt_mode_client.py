# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The receipt-mode bus client the adapter publishes through (OMN-18531)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelReceiptEvent,
)

if TYPE_CHECKING:
    from pydantic import JsonValue


class ProtocolReceiptModeClient(Protocol):
    """Publish one command and await its correlated events; hosts no handler.

    The omnibase_infra receipt-mode client (cli/receipt_mode.py) selects terminals strictly by
    expected_correlation_id; a library call over it is the production implementation.
    """

    def publish_and_await(
        self,
        *,
        topic: str,
        command_type: str,
        payload: dict[str, JsonValue],
        awaited_events: tuple[str, ...],
        deadline_ms: int,
    ) -> tuple[ModelReceiptEvent, ...]: ...
