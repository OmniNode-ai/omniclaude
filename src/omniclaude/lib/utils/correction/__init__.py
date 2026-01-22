"""
Correction module for AI Quality Enforcement System.
Generates intelligent corrections for code violations using RAG intelligence.
"""

from .generator import CorrectionGenerator, Violation

__all__ = ["CorrectionGenerator", "Violation"]
