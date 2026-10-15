# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A receipt-mode client stand-in for the adapter tests (OMN-18531)."""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING

from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelReceiptEvent,
)

if TYPE_CHECKING:
    from pydantic import JsonValue


class FakeClient:
    """Replays FAKE_REPLY (a JSON list of payloads), or blocks when FAKE_SLEEP is set."""

    def publish_and_await(
        self,
        *,
        topic: str,
        command_type: str,
        payload: dict[str, JsonValue],
        awaited_events: tuple[str, ...],
        deadline_ms: int,
    ) -> tuple[ModelReceiptEvent, ...]:
        if os.environ.get("FAKE_SLEEP"):
            threading.Event().wait(60)
        return tuple(
            ModelReceiptEvent(topic=awaited_events[0], payload=p)
            for p in json.loads(os.environ.get("FAKE_REPLY", "[]"))
        )
