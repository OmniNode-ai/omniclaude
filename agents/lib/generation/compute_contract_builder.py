"""
COMPUTE Contract Builder - Type-Safe Contract Generation.

Builds ModelContractCompute instances from parsed prompt data using
Pydantic models for pure computational nodes.
"""

import logging
from typing import Any, Dict

from omnibase_core.enums import EnumNodeType
from omnibase_core.models.contracts.model_algorithm_config import ModelAlgorithmConfig
from omnibase_core.models.contracts.model_algorithm_factor_config import (
    ModelAlgorithmFactorConfig,
)
from omnibase_core.models.contracts.model_contract_compute import ModelContractCompute

from .contract_builder import ContractBuilder

logger = logging.getLogger(__name__)


class ComputeContractBuilder(ContractBuilder[ModelContractCompute]):
    """
    Build COMPUTE node contracts using Pydantic models.

    COMPUTE nodes handle pure computational operations:
    - Data transformations
    - Calculations
    - Validation logic
    - Filtering and processing
    - Algorithm execution

    Example:
        ```python
        builder = ComputeContractBuilder()
        contract = builder.build({
            "node_type": "COMPUTE",
            "service_name": "price_calculator",
            "domain": "business",
            "description": "Calculate prices with tax and discounts",
            "operations": ["calculate total", "apply discount"],
        })
        yaml_content = builder.to_yaml(contract)
        ```
    """

    def build(self, data: Dict[str, Any]) -> ModelContractCompute:
        """
        Build COMPUTE contract from parsed data.

        Args:
            data: Parsed prompt data

        Returns:
            Fully populated ModelContractCompute instance

        Raises:
            ModelOnexError: If validation fails
        """
        self.validate_input(data)

        # Build algorithm configuration
        algorithm = self._build_algorithm_config(data.get("operations", []))

        # Build input/output model references
        service_name = data["service_name"]
        pascal_name = self._to_pascal_case(service_name)

        input_model = f"models.model_{service_name}_input.Model{pascal_name}Input"
        output_model = f"models.model_{service_name}_output.Model{pascal_name}Output"

        # Create contract using Pydantic model
        contract = ModelContractCompute(
            # Base contract fields
            name=service_name,
            version=self._create_semver(1, 0, 0),
            description=data["description"],
            node_type=EnumNodeType.COMPUTE,
            input_model=input_model,
            output_model=output_model,
            # COMPUTE-specific required fields
            algorithm=algorithm,
            # COMPUTE behavior flags
            deterministic_execution=True,  # Assume pure functions
            memory_optimization_enabled=True,
            intermediate_result_caching=False,  # Disable for POC
        )

        self.logger.info(
            f"Built COMPUTE contract: {service_name} "
            f"with algorithm type: {algorithm.algorithm_type}"
        )

        return contract

    def _build_algorithm_config(self, operations: list[str]) -> ModelAlgorithmConfig:
        """
        Build algorithm configuration from operations.

        Args:
            operations: List of operation descriptions

        Returns:
            Algorithm configuration model
        """
        # Infer algorithm type from operations
        algorithm_type = self._infer_algorithm_type(operations)

        # Build factors (input parameters for the algorithm)
        factors = self._build_algorithm_factors(operations)

        return ModelAlgorithmConfig(
            algorithm_type=algorithm_type,
            factors=factors,
            normalization_method="min_max",
            precision_digits=6,
        )

    def _infer_algorithm_type(self, operations: list[str]) -> str:
        """
        Infer algorithm type from operation descriptions.

        Args:
            operations: List of operation descriptions

        Returns:
            Algorithm type string
        """
        if not operations:
            return "transformation"

        combined = " ".join(operations).lower()

        # Check for specific algorithm patterns
        if any(
            kw in combined for kw in ["calculate", "compute", "sum", "average", "mean"]
        ):
            return "calculation"
        elif any(kw in combined for kw in ["transform", "convert", "map", "filter"]):
            return "transformation"
        elif any(kw in combined for kw in ["validate", "check", "verify", "ensure"]):
            return "validation"
        elif any(
            kw in combined for kw in ["aggregate", "summarize", "group", "combine"]
        ):
            return "aggregation"
        elif any(kw in combined for kw in ["sort", "order", "rank", "prioritize"]):
            return "sorting"
        else:
            return "transformation"  # Default

    def _build_algorithm_factors(
        self, operations: list[str]
    ) -> dict[str, ModelAlgorithmFactorConfig]:
        """
        Build algorithm factors (input parameters).

        Args:
            operations: List of operation descriptions

        Returns:
            Dictionary of algorithm factor configurations with weights summing to 1.0
        """
        factors = {}

        if not operations:
            # No operations, create single default factor with weight 1.0
            factors["input_data"] = ModelAlgorithmFactorConfig(
                factor_name="input_data",
                weight=1.0,
                calculation_method="linear",
                min_value=0.0,
                max_value=1.0,
            )
        else:
            # Create factors from operations with equal weight distribution
            num_factors = min(len(operations), 3)  # Max 3 factors for POC
            weight_per_factor = 1.0 / num_factors

            for i, op in enumerate(operations[:num_factors]):
                factor_name = self._sanitize_name(op, max_length=30)
                factors[factor_name] = ModelAlgorithmFactorConfig(
                    factor_name=factor_name,
                    weight=weight_per_factor,
                    calculation_method="linear",
                    min_value=0.0,
                    max_value=1.0,
                )

        return factors
