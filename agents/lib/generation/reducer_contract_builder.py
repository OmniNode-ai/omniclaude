"""
REDUCER Contract Builder - Type-Safe Contract Generation.

Builds ModelContractReducer instances from parsed prompt data using
Pydantic models for state aggregation nodes.
"""

import logging
from typing import Any, Dict

from omnibase_core.enums import EnumNodeType
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer

from .contract_builder import ContractBuilder


logger = logging.getLogger(__name__)


class ReducerContractBuilder(ContractBuilder[ModelContractReducer]):
    """
    Build REDUCER node contracts using Pydantic models.

    REDUCER nodes handle state aggregation and intent emission:
    - Pure state transitions
    - Intent emission (NOT direct execution)
    - Data aggregation
    - State management
    - FSM transitions

    CRITICAL: REDUCER nodes EMIT intents, they do NOT execute effects directly.

    Example:
        ```python
        builder = ReducerContractBuilder()
        contract = builder.build({
            "node_type": "REDUCER",
            "service_name": "order_aggregator",
            "domain": "business",
            "description": "Aggregate order data and emit processing intents",
            "operations": ["aggregate orders", "emit processing intent"],
        })
        yaml_content = builder.to_yaml(contract)
        ```
    """

    def build(self, data: Dict[str, Any]) -> ModelContractReducer:
        """
        Build REDUCER contract from parsed data.

        Args:
            data: Parsed prompt data

        Returns:
            Fully populated ModelContractReducer instance

        Raises:
            ModelOnexError: If validation fails
        """
        self.validate_input(data)

        # Build input/output model references
        service_name = data["service_name"]
        pascal_name = self._to_pascal_case(service_name)

        input_model = f"models.model_{service_name}_input.Model{pascal_name}Input"
        output_model = f"models.model_{service_name}_output.Model{pascal_name}Output"

        # Create contract using Pydantic model
        contract = ModelContractReducer(
            # Base contract fields
            name=service_name,
            version=self._create_semver(1, 0, 0),
            description=data["description"],
            node_type=EnumNodeType.REDUCER,
            input_model=input_model,
            output_model=output_model,
            # REDUCER behavior flags
            order_preserving=False,  # Not required for most cases
            incremental_processing=True,  # Enable streaming aggregation
            result_caching_enabled=True,  # Cache aggregated results
            partial_results_enabled=True,  # Support partial aggregations
            # Tracking
            correlation_id=self.correlation_id,
        )

        self.logger.info(
            f"Built REDUCER contract: {service_name} "
            f"with incremental_processing={contract.incremental_processing}"
        )

        return contract
