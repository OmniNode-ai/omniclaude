# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""StdoutSink — writes rendered log messages to stdout.

Failures are caught and logged internally; they never propagate to the caller.
"""

from __future__ import annotations

import logging
import sys

from omniclaude.nodes.node_personality_logging_effect.models.model_log_event import (
    EnumLogSeverity,
)
from omniclaude.nodes.node_personality_logging_effect.models.model_rendered_log import (
    ModelRenderedLog,
)

logger = logging.getLogger(__name__)

# Map LogEvent severity to Python logging levels for filtering
_SEVERITY_LEVEL: dict[str, int] = {
    EnumLogSeverity.TRACE: logging.DEBUG - 5,   # custom sub-level
    EnumLogSeverity.DEBUG: logging.DEBUG,
    EnumLogSeverity.INFO: logging.INFO,
    EnumLogSeverity.WARN: logging.WARNING,
    EnumLogSeverity.ERROR: logging.ERROR,
    EnumLogSeverity.FATAL: logging.CRITICAL,
}


class StdoutSink:
    """Writes rendered log messages to stdout, respecting log-level filtering.

    Args:
        min_severity: Minimum severity level to emit (inclusive).
            Events below this threshold are silently dropped.
    """

    def __init__(
        self,
        min_severity: EnumLogSeverity = EnumLogSeverity.DEBUG,
    ) -> None:
        self._min_level = _SEVERITY_LEVEL.get(min_severity, logging.DEBUG)

    def emit(self, rendered: ModelRenderedLog) -> None:
        """Write the rendered message to stdout.

        Sink failures are caught and logged internally — never raised.

        Args:
            rendered: The rendered log to emit.
        """
        try:
            event_level = _SEVERITY_LEVEL.get(
                rendered.original_event.severity, logging.DEBUG
            )
            if event_level < self._min_level:
                return
            print(rendered.rendered_message, file=sys.stdout, flush=True)
        except Exception:
            logger.exception("StdoutSink.emit failed")


__all__ = ["StdoutSink"]
