"""
AI Consensus and Quorum System
Provides multi-model validation and scoring for pre-commit corrections.
"""

from .quorum import AIQuorum, QuorumScore, ModelConfig

__all__ = ["AIQuorum", "QuorumScore", "ModelConfig"]
