"""
Contract Builder Factory - Builder Selection by Node Type.

Provides factory pattern for creating appropriate contract builders
based on ONEX node type.
"""

import logging
from typing import Type
from uuid import UUID

from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError
from omnibase_core.models.common.model_error_context import ModelErrorContext
from omnibase_core.models.common.model_schema_value import ModelSchemaValue

from .compute_contract_builder import ComputeContractBuilder
from .contract_builder import ContractBuilder
from .effect_contract_builder import EffectContractBuilder
from .orchestrator_contract_builder import OrchestratorContractBuilder
from .reducer_contract_builder import ReducerContractBuilder


logger = logging.getLogger(__name__)


class ContractBuilderFactory:
    """
    Factory for creating contract builders by node type.

    Provides centralized builder selection, registration, and validation
    for all ONEX node types.

    Example:
        ```python
        # Create builder for EFFECT node
        builder = ContractBuilderFactory.create("EFFECT")
        contract = builder.build(parsed_data)

        # Register custom builder
        ContractBuilderFactory.register("CUSTOM", CustomContractBuilder)
        ```
    """

    # Registry of builders by node type
    _builders: dict[str, Type[ContractBuilder]] = {
        "EFFECT": EffectContractBuilder,
        "COMPUTE": ComputeContractBuilder,
        "REDUCER": ReducerContractBuilder,
        "ORCHESTRATOR": OrchestratorContractBuilder,
    }

    @classmethod
    def create(
        cls, node_type: str, correlation_id: UUID | None = None
    ) -> ContractBuilder:
        """
        Create contract builder for specified node type.

        Args:
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            correlation_id: Optional correlation ID for tracking

        Returns:
            Contract builder instance for the specified type

        Raises:
            ModelOnexError: If node type not supported
        """
        # Normalize node type to uppercase
        node_type = node_type.upper()

        if node_type not in cls._builders:
            supported = ", ".join(sorted(cls._builders.keys()))
            raise ModelOnexError(
                message=f"Unsupported node type: {node_type}",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                details=ModelErrorContext.with_context(
                    {
                        "node_type": ModelSchemaValue.from_value(node_type),
                        "supported_types": ModelSchemaValue.from_value(supported),
                    }
                ),
            )

        builder_class = cls._builders[node_type]
        builder = builder_class(correlation_id=correlation_id)

        logger.info(f"Created {node_type} contract builder: {builder_class.__name__}")
        return builder

    @classmethod
    def register(cls, node_type: str, builder_class: Type[ContractBuilder]) -> None:
        """
        Register custom contract builder for node type.

        Allows extending the factory with custom builder implementations.

        Args:
            node_type: Node type to register
            builder_class: Builder class to use for this type

        Raises:
            ModelOnexError: If builder_class is not a valid ContractBuilder
        """
        if not issubclass(builder_class, ContractBuilder):
            raise ModelOnexError(
                message="Builder class must inherit from ContractBuilder",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                details=ModelErrorContext.with_context(
                    {
                        "builder_class": ModelSchemaValue.from_value(
                            builder_class.__name__
                        ),
                        "expected_base": ModelSchemaValue.from_value("ContractBuilder"),
                    }
                ),
            )

        node_type = node_type.upper()
        cls._builders[node_type] = builder_class
        logger.info(
            f"Registered custom builder for {node_type}: {builder_class.__name__}"
        )

    @classmethod
    def supported_types(cls) -> list[str]:
        """
        Get list of supported node types.

        Returns:
            List of supported node type strings
        """
        return sorted(cls._builders.keys())

    @classmethod
    def is_supported(cls, node_type: str) -> bool:
        """
        Check if node type is supported.

        Args:
            node_type: Node type to check

        Returns:
            True if node type has a registered builder
        """
        return node_type.upper() in cls._builders
