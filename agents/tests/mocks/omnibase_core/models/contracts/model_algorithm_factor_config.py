"""Mock for model_algorithm_factor_config."""

from typing import Any

from pydantic import BaseModel


class ModelAlgorithmFactorConfig(BaseModel):
    """
    Mock for ModelAlgorithmFactorConfig.

    Configuration for an algorithm factor/parameter.
    """

    factor_name: str
    weight: float = 1.0
    calculation_method: str = "linear"
    min_value: float = 0.0
    max_value: float = 1.0
    metadata: dict[str, Any] = {}

    class Config:
        """Pydantic config."""

        extra = "allow"
