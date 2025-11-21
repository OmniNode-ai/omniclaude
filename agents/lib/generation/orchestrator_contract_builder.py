"""
ORCHESTRATOR Contract Builder - Type-Safe Contract Generation.

Builds ModelContractOrchestrator instances from parsed prompt data using
Pydantic models for workflow coordination nodes.
"""

import logging
from typing import Any, Dict

from omnibase_core.enums import EnumNodeType
from omnibase_core.models.contracts.model_contract_orchestrator import (
    ModelContractOrchestrator,
)
from omnibase_core.models.contracts.model_performance_requirements import (
    ModelPerformanceRequirements,
)

from .contract_builder import ContractBuilder


logger = logging.getLogger(__name__)


class OrchestratorContractBuilder(ContractBuilder[ModelContractOrchestrator]):
    """
    Build ORCHESTRATOR node contracts using Pydantic models.

    ORCHESTRATOR nodes handle workflow coordination:
    - Multi-step workflows
    - Dependency resolution
    - Lease-based actions
    - Error recovery
    - Event orchestration

    CRITICAL: ORCHESTRATOR nodes coordinate workflows and emit actions via leases.

    Example:
        ```python
        builder = OrchestratorContractBuilder()
        contract = builder.build({
            "node_type": "ORCHESTRATOR",
            "service_name": "order_processor",
            "domain": "business",
            "description": "Orchestrate order processing workflow",
            "operations": ["coordinate steps", "manage failures"],
        })
        yaml_content = builder.to_yaml(contract)
        ```
    """

    def build(self, data: Dict[str, Any]) -> ModelContractOrchestrator:
        """
        Build ORCHESTRATOR contract from parsed data.

        Args:
            data: Parsed prompt data

        Returns:
            Fully populated ModelContractOrchestrator instance

        Raises:
            ModelOnexError: If validation fails
        """
        self.validate_input(data)

        # Build input/output model references
        service_name = data["service_name"]
        pascal_name = self._to_pascal_case(service_name)

        input_model = f"models.model_{service_name}_input.Model{pascal_name}Input"
        output_model = f"models.model_{service_name}_output.Model{pascal_name}Output"

        # Create performance requirements (required for ORCHESTRATOR)
        performance = ModelPerformanceRequirements(
            single_operation_max_ms=10000,  # 10 seconds max per operation
            memory_limit_mb=512,
            cpu_limit_percent=80,
        )

        # Create contract using Pydantic model
        contract = ModelContractOrchestrator(
            # Base contract fields
            name=service_name,
            version=self._create_semver(1, 0, 0),
            description=data["description"],
            node_type=EnumNodeType.ORCHESTRATOR,
            input_model=input_model,
            output_model=output_model,
            performance=performance,  # Required for ORCHESTRATOR
            # ORCHESTRATOR behavior flags
            load_balancing_enabled=True,  # Enable load balancing across workers
            failure_isolation_enabled=True,  # Isolate failures to prevent cascade
            monitoring_enabled=True,  # Enable workflow monitoring
            metrics_collection_enabled=True,  # Collect orchestration metrics
            # Tracking
            correlation_id=self.correlation_id,
        )

        self.logger.info(
            f"Built ORCHESTRATOR contract: {service_name} "
            f"with monitoring and failure isolation enabled"
        )

        return contract
