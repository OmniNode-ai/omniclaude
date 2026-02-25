# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tier 0 heuristic / regex-based quirk detectors.

These detectors require no model inference and operate entirely on diffs
and raw text using regular expressions and simple counting heuristics.

Detectors:
    - StubCodeDetector  (STUB_CODE)
    - NoTestsDetector   (NO_TESTS)
    - SycophancyDetector (SYCOPHANCY)

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from omniclaude.quirks.detectors.tier0.no_tests import NoTestsDetector
from omniclaude.quirks.detectors.tier0.stub_code import StubCodeDetector
from omniclaude.quirks.detectors.tier0.sycophancy import SycophancyDetector

__all__ = [
    "NoTestsDetector",
    "StubCodeDetector",
    "SycophancyDetector",
]
