# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Consume a transcript usage read (OMN-18946).

The read returns the marker state it would leave; the caller writes it here
only after every event of the read was journalled. A marker that cannot be
written is reported, not hidden: the usage will be counted again by the next
read, which is the safe direction for a counter that must not lose tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

from omniclaude.nodes.node_transcript_usage_read_effect.models import (
    ModelTranscriptUsageCommitRequest,
    ModelTranscriptUsageCommitResult,
)


class HandlerTranscriptUsageCommit:
    """Write the marker a read returned, atomically."""

    def handle(
        self, request: ModelTranscriptUsageCommitRequest
    ) -> ModelTranscriptUsageCommitResult:
        marker = Path(request.marker_path)
        payload = json.dumps(
            {"offset": request.next_offset, "ids": list(request.seen_ids)}
        )
        tmp = marker.with_suffix(".usage.tmp")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(marker)
        except OSError as exc:
            return ModelTranscriptUsageCommitResult(
                committed=False, reason=type(exc).__name__
            )
        return ModelTranscriptUsageCommitResult(committed=True)


__all__ = ["HandlerTranscriptUsageCommit"]
