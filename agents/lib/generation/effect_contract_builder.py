"""
EFFECT Contract Builder - Type-Safe Contract Generation.

Builds ModelContractEffect instances from parsed prompt data using
Pydantic models instead of string concatenation.
"""

import logging
from typing import Any, Dict, List
from uuid import uuid4

from omnibase_core.enums import EnumNodeType
from omnibase_core.models.contracts.model_backup_config import ModelBackupConfig
from omnibase_core.models.contracts.model_contract_effect import ModelContractEffect
from omnibase_core.models.contracts.model_effect_retry_config import (
    ModelEffectRetryConfig,
)
from omnibase_core.models.contracts.model_external_service_config import (
    ModelExternalServiceConfig,
)
from omnibase_core.models.contracts.model_io_operation_config import (
    ModelIOOperationConfig,
)
from omnibase_core.models.contracts.model_transaction_config import (
    ModelTransactionConfig,
)

from .contract_builder import ContractBuilder


logger = logging.getLogger(__name__)


class EffectContractBuilder(ContractBuilder[ModelContractEffect]):
    """
    Build EFFECT node contracts using Pydantic models.

    EFFECT nodes handle external I/O and side effects:
    - API calls
    - Database operations
    - File I/O
    - Message queues
    - External service integrations

    Example:
        ```python
        builder = EffectContractBuilder()
        contract = builder.build({
            "node_type": "EFFECT",
            "service_name": "postgres_writer",
            "domain": "infrastructure",
            "description": "Write data to PostgreSQL database",
            "operations": ["create records", "update data"],
            "external_systems": ["PostgreSQL"],
        })
        yaml_content = builder.to_yaml(contract)
        ```
    """

    def build(self, data: Dict[str, Any]) -> ModelContractEffect:
        """
        Build EFFECT contract from parsed data.

        Args:
            data: Parsed prompt data

        Returns:
            Fully populated ModelContractEffect instance

        Raises:
            ModelOnexError: If validation fails
        """
        self.validate_input(data)

        # Build I/O operations from functional requirements
        io_operations = self._build_io_operations(data.get("operations", []))

        # Build external services configuration
        external_services = self._build_external_services(
            data.get("external_systems", [])
        )

        # Build input/output model references
        service_name = data["service_name"]
        pascal_name = self._to_pascal_case(service_name)

        input_model = f"models.model_{service_name}_input.Model{pascal_name}Input"
        output_model = f"models.model_{service_name}_output.Model{pascal_name}Output"

        # Create contract using Pydantic model
        contract = ModelContractEffect(
            # Base contract fields
            name=service_name,
            version=self._create_semver(1, 0, 0),
            description=data["description"],
            node_type=EnumNodeType.EFFECT,
            input_model=input_model,
            output_model=output_model,
            # EFFECT-specific required fields
            io_operations=io_operations,
            # EFFECT-specific optional fields with defaults
            transaction_management=ModelTransactionConfig(),
            retry_policies=ModelEffectRetryConfig(),
            external_services=external_services,
            backup_config=ModelBackupConfig(),
            # EFFECT behavior flags
            idempotent_operations=self._detect_idempotent_operations(
                data.get("operations", [])
            ),
            side_effect_logging_enabled=True,
            audit_trail_enabled=True,
            consistency_validation_enabled=True,
            # Tracking
            correlation_id=self.correlation_id,
            execution_id=uuid4(),
        )

        self.logger.info(
            f"Built EFFECT contract: {data['service_name']} "
            f"with {len(io_operations)} I/O operations"
        )

        return contract

    def _build_io_operations(
        self, operations: List[str]
    ) -> List[ModelIOOperationConfig]:
        """
        Build I/O operation configurations from operation descriptions.

        Args:
            operations: List of operation descriptions

        Returns:
            List of I/O operation configuration models
        """
        if not operations:
            # Default operation if none specified
            operations = ["perform_operation"]

        io_ops = []
        for op_desc in operations[:5]:  # Max 5 operations for POC
            op_type = self._infer_operation_type(op_desc)

            io_ops.append(
                ModelIOOperationConfig(
                    operation_type=op_type,
                    atomic=True,
                    backup_enabled=op_type in ["write", "delete", "update"],
                    timeout_seconds=30,
                    validation_enabled=True,
                )
            )

        return io_ops

    def _build_external_services(
        self, external_systems: List[str]
    ) -> List[ModelExternalServiceConfig]:
        """
        Build external service configurations.

        Args:
            external_systems: List of external system names

        Returns:
            List of external service configuration models
        """
        services = []

        for system in external_systems[:3]:  # Max 3 for POC
            services.append(
                ModelExternalServiceConfig(
                    service_name=self._sanitize_name(system),
                    service_type=self._infer_service_type(system),
                    required=True,
                    timeout_seconds=30,
                    retry_enabled=True,
                )
            )

        return services

    def _infer_operation_type(self, description: str) -> str:
        """
        Infer I/O operation type from description.

        Args:
            description: Operation description

        Returns:
            Operation type string (read, write, update, delete)
        """
        desc_lower = description.lower()

        # Check for specific patterns
        if any(
            kw in desc_lower for kw in ["create", "insert", "add", "write", "store"]
        ):
            return "write"
        elif any(
            kw in desc_lower for kw in ["read", "get", "fetch", "load", "query", "list"]
        ):
            return "read"
        elif any(
            kw in desc_lower for kw in ["update", "modify", "change", "edit", "patch"]
        ):
            return "update"
        elif any(kw in desc_lower for kw in ["delete", "remove", "drop", "destroy"]):
            return "delete"
        else:
            # Default to write for side effects
            return "write"

    def _infer_service_type(self, system_name: str) -> str:
        """
        Infer external service type from system name.

        Args:
            system_name: Name of external system

        Returns:
            Service type string
        """
        system_lower = system_name.lower()

        if any(
            kw in system_lower for kw in ["postgres", "mysql", "database", "db", "sql"]
        ):
            return "database"
        elif any(kw in system_lower for kw in ["api", "rest", "http", "endpoint"]):
            return "api"
        elif any(kw in system_lower for kw in ["redis", "cache", "memcached"]):
            return "cache"
        elif any(kw in system_lower for kw in ["kafka", "queue", "rabbit", "sqs"]):
            return "message_queue"
        elif any(kw in system_lower for kw in ["s3", "storage", "blob", "file"]):
            return "storage"
        else:
            return "external_service"

    def _detect_idempotent_operations(self, operations: List[str]) -> bool:
        """
        Detect if operations are idempotent.

        Args:
            operations: List of operation descriptions

        Returns:
            True if all operations appear to be idempotent
        """
        if not operations:
            return True

        # Operations are idempotent if they're all reads or deletes
        op_types = [self._infer_operation_type(op) for op in operations]
        return all(op in ["read", "delete"] for op in op_types)
