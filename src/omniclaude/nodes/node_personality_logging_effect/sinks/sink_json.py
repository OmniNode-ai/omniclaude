# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""JsonSink — writes raw LogEvent as newline-delimited JSON.

Personality rendering is bypassed — the raw structured event is always used.
Writes to a file or stdout (``path="-"``).

Failures are caught and logged internally; they never propagate to the caller.
"""

from __future__ import annotations

import logging
import sys

from omniclaude.nodes.node_personality_logging_effect.models.model_rendered_log import (
    ModelRenderedLog,
)

logger = logging.getLogger(__name__)


class JsonSink:
    """Writes the raw ``LogEvent`` as newline-delimited JSON.

    Personality rendering is bypassed — consumers of this sink always receive
    the canonical structured event regardless of the active profile.

    Args:
        path: Destination file path, or ``"-"`` to write to stdout.
    """

    def __init__(self, path: str = "-") -> None:
        self._path = path

    def emit(self, rendered: ModelRenderedLog) -> None:
        """Serialize the original event as newline-delimited JSON and write it.

        Sink failures are caught and logged internally — never raised.

        Args:
            rendered: The rendered log. The ``original_event`` field is used;
                the ``rendered_message`` is ignored.
        """
        try:
            line = rendered.original_event.model_dump_json()
            if self._path == "-":
                print(line, file=sys.stdout, flush=True)
            else:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:
            logger.exception("JsonSink.emit failed")


__all__ = ["JsonSink"]
