# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""QuirkDetector protocol — structural interface for all detector tiers.

Any class that implements a ``detect`` method with the correct signature
satisfies this protocol.  Detectors are stateless; all required context
is passed in via ``DetectionContext``.

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.models import QuirkSignal


@runtime_checkable
class QuirkDetector(Protocol):
    """Structural protocol for quirk detectors across all tiers.

    Implementors must be **stateless** — all per-call context is supplied
    via ``DetectionContext``.  Any instance-level state should be limited to
    configuration injected at construction time (e.g. threshold values).
    """

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        """Run the detector against the supplied context.

        Args:
            context: Immutable bundle of diff, model output, and session
                metadata for the current detection run.

        Returns:
            A (possibly empty) list of ``QuirkSignal`` instances, one per
            distinct occurrence detected.  Returns an empty list when no
            quirk is found.
        """
        ...
