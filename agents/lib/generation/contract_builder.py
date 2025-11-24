"""
Contract Builder Base Class - ONEX Contract Generation.

Provides abstract base class for building type-safe ONEX contracts using
omnibase_core Pydantic models. Replaces string-based contract generation
with structured, validated contract objects.
"""

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generic, TypeVar
from uuid import UUID, uuid4

from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError
from omnibase_core.models.common.model_error_context import ModelErrorContext
from omnibase_core.models.common.model_schema_value import ModelSchemaValue
from omnibase_core.models.contracts.model_contract_base import ModelContractBase
from omnibase_core.primitives.model_semver import ModelSemVer


logger = logging.getLogger(__name__)

# Type variable for contract types
T_Contract = TypeVar("T_Contract", bound=ModelContractBase)


class ContractBuilder(ABC, Generic[T_Contract]):
    """
    Abstract base class for building ONEX contracts using Pydantic models.

    Provides common functionality for contract generation across all node types:
    - Input validation
    - YAML serialization via .to_yaml()
    - Helper methods for common contract fields
    - Type-safe contract building

    Type Parameters:
        T_Contract: Specific contract model type (Effect, Compute, Reducer, Orchestrator)

    Example:
        ```python
        class EffectContractBuilder(ContractBuilder[ModelContractEffect]):
            def build(self, data: Dict[str, Any]) -> ModelContractEffect:
                return ModelContractEffect(
                    name=data["service_name"],
                    version=ModelSemVer(major=1, minor=0, patch=0),
                    description=data["description"],
                    node_type=EnumNodeType.EFFECT,
                    # ... populate all required fields
                )
        ```
    """

    def __init__(self, correlation_id: UUID | None = None) -> None:
        """
        Initialize contract builder.

        Args:
            correlation_id: Optional correlation ID for tracking
        """
        self.correlation_id = correlation_id or uuid4()
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def build(self, data: Dict[str, Any]) -> T_Contract:
        """
        Build contract from parsed prompt data.

        Args:
            data: Parsed prompt data containing:
                - node_type: str (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
                - service_name: str (snake_case service name)
                - domain: str (domain classification)
                - description: str (business description)
                - operations: List[str] (functional requirements)
                - features: List[str] (top features)
                - confidence: float (parsing confidence 0-1)
                - external_systems: List[str] (optional)

        Returns:
            Fully populated contract model instance

        Raises:
            ModelOnexError: If required fields missing or validation fails
        """
        pass

    def validate_input(self, data: Dict[str, Any]) -> None:
        """
        Validate input data has all required fields.

        Args:
            data: Input data dictionary

        Raises:
            ModelOnexError: If required fields missing
        """
        required = ["node_type", "service_name", "domain", "description"]
        missing = [f for f in required if f not in data or not data[f]]

        if missing:
            raise ModelOnexError(
                message=f"Missing required fields for contract building: {', '.join(missing)}",
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                details=ModelErrorContext.with_context(
                    {
                        "missing_fields": ModelSchemaValue.from_value(missing),
                        "provided_fields": ModelSchemaValue.from_value(
                            list(data.keys())
                        ),
                    }
                ),
            )

    def to_yaml(self, contract: T_Contract, output_path: Path | None = None) -> str:
        """
        Generate YAML from contract using Pydantic .to_yaml() method.

        Args:
            contract: Populated contract model
            output_path: Optional path to write YAML file

        Returns:
            YAML string representation

        Raises:
            ModelOnexError: If YAML generation fails
        """
        try:
            # Use Pydantic model's to_yaml() method
            yaml_content = contract.to_yaml()

            # Write to file if path provided
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(yaml_content)
                self.logger.info(f"Contract YAML written to {output_path}")

            return yaml_content

        except Exception as e:
            raise ModelOnexError(
                message=f"Failed to generate YAML from contract: {str(e)}",
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                details=ModelErrorContext.with_context(
                    {
                        "contract_type": ModelSchemaValue.from_value(
                            contract.__class__.__name__
                        ),
                        "error": ModelSchemaValue.from_value(str(e)),
                    }
                ),
            )

    def _create_semver(
        self, major: int = 1, minor: int = 0, patch: int = 0
    ) -> ModelSemVer:
        """Create semantic version for contract."""
        return ModelSemVer(major=major, minor=minor, patch=patch)

    def _to_snake_case(self, text: str) -> str:
        """Convert text to snake_case."""
        # Remove special characters
        text = re.sub(r"[^\w\s-]", "", text)
        # Replace whitespace and hyphens with underscores
        text = re.sub(r"[-\s]+", "_", text)
        # Convert to lowercase
        return text.lower()

    def _to_pascal_case(self, text: str) -> str:
        """Convert text to PascalCase."""
        # Remove special characters
        text = re.sub(r"[^\w\s-]", "", text)
        # Split on whitespace and hyphens
        words = re.split(r"[-\s_]+", text)
        # Capitalize each word
        return "".join(word.capitalize() for word in words if word)

    def _sanitize_name(self, name: str, max_length: int = 50) -> str:
        """
        Sanitize name for use in contracts.

        Args:
            name: Input name
            max_length: Maximum length for sanitized name

        Returns:
            Sanitized snake_case name
        """
        sanitized = self._to_snake_case(name)
        return sanitized[:max_length]
