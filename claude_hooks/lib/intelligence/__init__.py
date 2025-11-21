"""
Intelligence subsystem for pre-commit hooks.

Provides RAG-based intelligence for code quality enforcement.
"""

from .rag_client import RAGIntelligenceClient


__all__ = ["RAGIntelligenceClient"]
