#!/usr/bin/env python3
"""
Quorum Configuration for Generation Pipeline

Configures multi-model validation at critical pipeline stages.
"""

from dataclasses import dataclass


@dataclass
class QuorumConfig:
    """Configuration for quorum validation in generation pipeline"""

    # Validation stages
    validate_prd_analysis: bool = True  # Stage 1
    validate_intelligence: bool = False  # Stage 1.5
    validate_contract: bool = True  # Stage 2 (CRITICAL)
    validate_node_code: bool = False  # Stage 3

    # Retry configuration
    retry_on_fail: bool = True
    max_retries_per_stage: int = 2

    # Thresholds
    pass_threshold: float = 0.75  # >75% = PASS
    retry_threshold: float = 0.50  # 50-75% = RETRY, <50% = FAIL

    # Performance
    quorum_timeout_seconds: int = 10
    parallel_validation: bool = False

    @classmethod
    def from_mode(cls, mode: str) -> "QuorumConfig":
        """
        Create config from execution mode.

        Modes:
        - fast: No quorum validation (current behavior)
        - balanced: PRD + Contract validation (recommended default)
        - standard: PRD + Contract + Intelligence
        - strict: All stages validated

        Args:
            mode: Execution mode name

        Returns:
            QuorumConfig for the specified mode
        """
        modes = {
            "fast": cls(
                validate_prd_analysis=False,
                validate_intelligence=False,
                validate_contract=False,
                validate_node_code=False,
            ),
            "balanced": cls(
                validate_prd_analysis=True,
                validate_intelligence=False,
                validate_contract=True,
                validate_node_code=False,
            ),
            "standard": cls(
                validate_prd_analysis=True,
                validate_intelligence=True,
                validate_contract=True,
                validate_node_code=False,
            ),
            "strict": cls(
                validate_prd_analysis=True,
                validate_intelligence=True,
                validate_contract=True,
                validate_node_code=True,
            ),
        }
        return modes.get(mode, modes["balanced"])

    @classmethod
    def disabled(cls) -> "QuorumConfig":
        """Create config with all validation disabled (backward compatibility)"""
        return cls.from_mode("fast")


__all__ = ["QuorumConfig"]
