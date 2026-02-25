# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Utility tools for the Quirks Detector system.

Tools:
    - SymbolIndexBuilder: Walk a Python package and produce a symbol index
      for use with HallucinatedApiDetector.

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2360: Quirks Detector epic
"""

from omniclaude.quirks.tools.build_symbol_index import SymbolIndexBuilder

__all__ = ["SymbolIndexBuilder"]
