# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Quirk detector registry — central registry of all available detectors.

Detectors self-register by being imported here.  Callers that need to run
all detectors can retrieve the full list via ``get_all_detectors()``.

Usage::

    from omniclaude.quirks.detectors.registry import get_all_detectors

    detectors = get_all_detectors()
    for detector in detectors:
        signals = detector.detect(context)

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

from omniclaude.quirks.detectors.protocol import QuirkDetector
from omniclaude.quirks.detectors.tier0.no_tests import NoTestsDetector
from omniclaude.quirks.detectors.tier0.stub_code import StubCodeDetector
from omniclaude.quirks.detectors.tier0.sycophancy import SycophancyDetector

# ---------------------------------------------------------------------------
# Registry — ordered list of all instantiated detectors.
# ---------------------------------------------------------------------------

_REGISTRY: list[QuirkDetector] = [
    StubCodeDetector(),
    NoTestsDetector(),
    SycophancyDetector(),
]


def get_all_detectors() -> list[QuirkDetector]:
    """Return the global list of registered quirk detectors.

    Returns:
        A shallow copy of the internal registry list so callers cannot
        accidentally mutate the global state.
    """
    return list(_REGISTRY)


def register_detector(detector: QuirkDetector) -> None:
    """Add a detector instance to the global registry.

    This function is intended for use in tests and extension points.
    For production use, detectors should be added directly to ``_REGISTRY``.

    Args:
        detector: Any object satisfying the ``QuirkDetector`` protocol.
    """
    _REGISTRY.append(detector)
