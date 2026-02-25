# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tier 1 AST-based quirk detectors.

These detectors parse Python source code using the stdlib ``ast`` module for
higher-precision analysis than Tier 0 regex heuristics.  They augment (do not
replace) Tier 0 detectors.

Detectors:
    - AstStubCodeDetector  (STUB_CODE) — AST upgrade over Tier 0
    - HallucinatedApiDetector (HALLUCINATED_API)

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from omniclaude.quirks.detectors.tier1.ast_stub_code import AstStubCodeDetector
from omniclaude.quirks.detectors.tier1.hallucinated_api import HallucinatedApiDetector

__all__ = [
    "AstStubCodeDetector",
    "HallucinatedApiDetector",
]
