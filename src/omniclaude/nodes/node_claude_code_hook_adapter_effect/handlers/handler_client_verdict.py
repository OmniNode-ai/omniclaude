# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pure verdict compute and the verdict-to-hook-output table (OMN-18531).

The adapter's only decisions live here, as functions of the binding row and the
events: reassemble a chunked reply by content-record id (P15), check its sha256
against the echoed hash, and map the typed action to the hook's output shape by
table lookup.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientVerdictAction,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientBinding,
    ModelClientVerdict,
    ModelReceiptEvent,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

_PACKAGE_ACTIONS = frozenset(
    {
        EnumClientVerdictAction.INSTALL,
        EnumClientVerdictAction.INJECT,
    }
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reassemble_chunks(
    events: tuple[ModelReceiptEvent, ...], record_id: str
) -> str | None:
    """Join a record's chunks in chunk_index order; None when one is missing or duplicated."""
    chunks = [
        e.payload
        for e in events
        if e.payload.get("record_id") == record_id and "chunk_index" in e.payload
    ]
    if not chunks:
        return None
    totals = {c.get("chunk_total") for c in chunks}
    if len(totals) != 1:
        return None
    (total,) = totals
    indexed = sorted(
        (c["chunk_index"], c.get("data", ""))
        for c in chunks
        if isinstance(c["chunk_index"], int)
    )
    if not isinstance(total, int) or [i for i, _ in indexed] != list(range(total)):
        return None
    return "".join(str(d) for _, d in indexed)


def compute_client_verdict(
    binding: ModelClientBinding, events: tuple[ModelReceiptEvent, ...]
) -> ModelClientVerdict:
    """Fold the awaited events into one verdict; an unverifiable reply is the binding's fallback."""
    fallback = ModelClientVerdict(action=binding.unverified_action)
    verdicts = [e.payload for e in events if "action" in e.payload]
    if not verdicts:
        return fallback
    reply = verdicts[-1]
    try:
        action = EnumClientVerdictAction(str(reply["action"]))
    except ValueError:
        return fallback
    echoed = str(reply.get("package_sha256", ""))
    record_id = reply.get("record_id")
    if isinstance(record_id, str):
        text = reassemble_chunks(events, record_id)
        if text is None or sha256_text(text) != echoed:
            return fallback
    else:
        text = str(reply.get("text", ""))
        if action in _PACKAGE_ACTIONS and sha256_text(text) != echoed:
            return fallback
    return ModelClientVerdict(action=action, text=text, package_sha256=echoed)


def _result(binding: ModelClientBinding, v: ModelClientVerdict) -> dict[str, JsonValue]:
    return {"result": v.text}


def _deny(binding: ModelClientBinding, v: ModelClientVerdict) -> dict[str, JsonValue]:
    return {"deny": v.text}


def _messages(
    binding: ModelClientBinding, v: ModelClientVerdict
) -> dict[str, JsonValue]:
    return {"messages": json.loads(v.text)}


def _additional_context(
    binding: ModelClientBinding, v: ModelClientVerdict
) -> dict[str, JsonValue]:
    return {
        "hookSpecificOutput": {
            "hookEventName": binding.hook_event,
            "additionalContext": v.text,
        }
    }


def _nothing(binding: ModelClientBinding, v: ModelClientVerdict) -> None:
    return None


_OUTPUT_TABLE: dict[
    EnumClientVerdictAction,
    Callable[[ModelClientBinding, ModelClientVerdict], dict[str, JsonValue] | None],
] = {
    EnumClientVerdictAction.ANSWER: _result,
    EnumClientVerdictAction.REFUSE: _deny,
    EnumClientVerdictAction.PROCEED_NATIVE: _nothing,
    EnumClientVerdictAction.INSTALL: _messages,
    EnumClientVerdictAction.NATIVE: _nothing,
    EnumClientVerdictAction.INJECT: _additional_context,
    EnumClientVerdictAction.NONE: _nothing,
}


def hook_output_for(
    binding: ModelClientBinding, verdict: ModelClientVerdict
) -> dict[str, JsonValue] | None:
    """Table lookup: the hook's own output shape for a verdict, or None for no output."""
    return _OUTPUT_TABLE[verdict.action](binding, verdict)
