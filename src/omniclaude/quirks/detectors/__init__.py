# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Quirks Detector hierarchy — public surface.

Tier 0 heuristic detectors (no model inference):
    - StubCodeDetector
    - NoTestsDetector
    - SycophancyDetector

Usage::

    from omniclaude.quirks.detectors import (
        DetectionContext,
        QuirkDetector,
        StubCodeDetector,
        NoTestsDetector,
        SycophancyDetector,
    )

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.protocol import QuirkDetector
from omniclaude.quirks.detectors.tier0.no_tests import NoTestsDetector
from omniclaude.quirks.detectors.tier0.stub_code import StubCodeDetector
from omniclaude.quirks.detectors.tier0.sycophancy import SycophancyDetector

__all__ = [
    "DetectionContext",
    "NoTestsDetector",
    "QuirkDetector",
    "StubCodeDetector",
    "SycophancyDetector",
]
