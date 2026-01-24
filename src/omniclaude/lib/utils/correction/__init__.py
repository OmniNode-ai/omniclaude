"""
Correction module for AI Quality Enforcement System.
Generates intelligent corrections for code violations using RAG intelligence.
"""

from omniclaude.lib.utils.naming_validator import Violation

from .generator import CorrectionGenerator

__all__ = ["CorrectionGenerator", "Violation"]
