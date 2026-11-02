# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The context size and model a PostCompact event is stamped with (OMN-22004, TA.22).

The savings handler in omnimarket counts a mod-answered compaction from two
keys of the PostCompact payload: ``context_tokens``, the ``preTokens`` of the
compaction's ``compact_boundary`` record, and ``model``, the session model.
Claude Code hands the hook neither, so the capture producer reads them from the
transcript. The boundary is the one the TA.20b ``compact`` capture already read
(``node_compact_package_read_effect``): this module takes that item and parses
nothing the reader did not find. A key is absent, never invented or zero, when
the transcript does not hold it.

The hook process imports this module, so it uses the standard library and the
node's own models only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniclaude.nodes.node_transcript_usage_read_effect.models import (
    ModelCompactStampRequest,
    ModelCompactStampResult,
)

#: A transcript's last bytes are read for the model; a session's newest
#: assistant entry sits near the tail.
MODEL_TAIL_BYTES = 8 * 1024 * 1024


def _transcript_model(transcript: Path) -> str | None:
    """The newest main-thread assistant model in the tail; a harness pseudo-model (``<synthetic>``) is not one."""
    try:
        size = transcript.stat().st_size
        with transcript.open("rb") as handle:
            handle.seek(max(0, size - MODEL_TAIL_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        model = message.get("model") if isinstance(message, dict) else None
        if (
            entry.get("type") == "assistant"
            and not entry.get("isSidechain")
            and isinstance(model, str)
            and model
            and not model.startswith("<")
        ):
            return model
    return None


def compact_stamp(request: ModelCompactStampRequest) -> ModelCompactStampResult:
    """No boundary, or no positive integer ``preTokens``, stamps nothing."""
    nothing = ModelCompactStampResult()
    if not request.package:
        return nothing
    try:
        boundary = json.loads(request.package.split("\n", 1)[0])
    except json.JSONDecodeError:
        return nothing
    meta = boundary.get("compactMetadata") if isinstance(boundary, dict) else None
    pre = meta.get("preTokens") if isinstance(meta, dict) else None
    if not isinstance(pre, int) or isinstance(pre, bool) or pre < 1:
        return nothing
    return ModelCompactStampResult(
        context_tokens=pre, model=_transcript_model(Path(request.transcript_path))
    )


class HandlerCompactStamp:
    """The context size and model of one compaction, from the transcript."""

    def handle(self, request: ModelCompactStampRequest) -> ModelCompactStampResult:
        return compact_stamp(request)


def stamp(
    payload: dict[str, Any],
    items_for_compact: Callable[[dict[str, Any]], list[dict[str, Any]]],
    hook_input: dict[str, Any],
) -> None:
    """The hook's call: set the keys the transcript gives on a PostCompact payload.

    ``items_for_compact`` is the TA.20b capture's own transcript read, so the
    boundary is read once and by one parser.
    """
    path = hook_input.get("transcript_path")
    items = items_for_compact(hook_input) if isinstance(path, str) and path else []
    package = str(items[0].get("content", "")) if items else ""
    request = ModelCompactStampRequest(package=package, transcript_path=str(path))
    payload.update(compact_stamp(request).stamp())
