"""Mock for model_algorithm_config."""

from typing import Any

from pydantic import BaseModel


class ModelAlgorithmConfig(BaseModel):
    """
    Mock for ModelAlgorithmConfig.

    Configuration for algorithm-based computations.
    """

    algorithm_type: str
    factors: list[str] = []
    normalization_method: str = "min_max"
    precision_digits: int = 6
    metadata: dict[str, Any] = {}

    class Config:
        """Pydantic config."""

        extra = "allow"
