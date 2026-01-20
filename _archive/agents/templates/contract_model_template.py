#!/usr/bin/env python3
"""
{MICROSERVICE_NAME_PASCAL} {NODE_TYPE} Contract Model - ONEX Standards Compliant.

VERSION: 1.0.0 - INTERFACE LOCKED FOR CODE GENERATION

STABILITY GUARANTEE:
- All fields, methods, and validators are stable interfaces
- New optional fields may be added in minor versions only
- Existing fields cannot be removed or have types/constraints changed

Generated contract model for {MICROSERVICE_NAME} {NODE_TYPE} node providing:
- Strong typing and validation
- ONEX architectural compliance
- Integration with subcontracts and mixins
- Performance and quality requirements

{BUSINESS_DESCRIPTION}

ZERO TOLERANCE: No Any types allowed in implementation.
"""

from typing import ClassVar, Self

from omnibase_core.errors.error_codes import EnumCoreErrorCode
from omnibase_core.errors.model_onex_error import ModelOnexError
from omnibase_core.models.common.model_error_context import ModelErrorContext
from omnibase_core.models.common.model_schema_value import ModelSchemaValue
from omnibase_core.primitives.model_semver import ModelSemVer
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model{MICROSERVICE_NAME_PASCAL}{NODE_TYPE_PASCAL}Contract(BaseModel):
    """
    Contract model for {MICROSERVICE_NAME} {NODE_TYPE} node.

    Comprehensive contract configuration providing strong typing, validation,
    and ONEX compliance following established patterns.

    ZERO TOLERANCE: No Any types allowed in implementation.
    """

    # Interface version for code generation stability
    INTERFACE_VERSION: ClassVar[ModelSemVer] = ModelSemVer(major=1, minor=0, patch=0)

    # Core contract configuration
    contract_version: ModelSemVer = Field(
        default=ModelSemVer(major=1, minor=0, patch=0),
        description="Contract version following semantic versioning",
    )

    node_name: str = Field(
        default="{MICROSERVICE_NAME}_{NODE_TYPE_LOWER}",
        description="Unique identifier for this node",
    )

    node_version: ModelSemVer = Field(
        default=ModelSemVer(major=1, minor=0, patch=0),
        description="Node implementation version",
    )

    contract_name: str = Field(
        default="{MICROSERVICE_NAME}_{NODE_TYPE_LOWER}_contract",
        description="Contract identifier",
    )

    description: str = Field(
        default="{BUSINESS_DESCRIPTION}",
        description="Business description of this node",
    )

    node_type: str = Field(
        default="{NODE_TYPE}",
        description="ONEX node type: EFFECT, COMPUTE, REDUCER, or ORCHESTRATOR",
    )

    input_model: str = Field(
        default="Model{MICROSERVICE_NAME_PASCAL}Input",
        description="Input model class name",
    )

    output_model: str = Field(
        default="Model{MICROSERVICE_NAME_PASCAL}Output",
        description="Output model class name",
    )

    # Performance requirements ({NODE_TYPE_LOWER} specific)
    {PERFORMANCE_FIELDS}

    # Service configuration
    is_persistent_service: bool = Field(
        default={IS_PERSISTENT_SERVICE},
        description="Whether this service maintains persistent state",
    )

    requires_external_dependencies: bool = Field(
        default={REQUIRES_EXTERNAL_DEPS},
        description="Whether this service requires external dependencies",
    )

    # ONEX compliance flags
    contract_driven: bool = Field(
        default=True,
        description="Whether this node follows contract-driven development",
    )

    strong_typing: bool = Field(
        default=True,
        description="Whether strong typing is enforced",
    )

    zero_any_types: bool = Field(
        default=True,
        description="Whether Any types are prohibited",
    )

    protocol_based: bool = Field(
        default=True,
        description="Whether protocol-based interfaces are used",
    )

    @model_validator(mode="after")
    def validate_contract_configuration(self) -> Self:
        """
        Comprehensive validation of contract configuration.

        Validates:
        - node_type is one of allowed values
        - Contract version matches node version
        - Required fields are properly configured
        """
        # Validate node_type is one of allowed values
        allowed_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
        if self.node_type not in allowed_types:
            msg = f"node_type must be one of {{allowed_types}}, got '{{self.node_type}}'"
            raise ModelOnexError(
                message=msg,
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                details=ModelErrorContext.with_context(
                    {{
                        "error_type": ModelSchemaValue.from_value("valueerror"),
                        "validation_context": ModelSchemaValue.from_value(
                            "model_validation",
                        ),
                        "field": ModelSchemaValue.from_value("node_type"),
                        "allowed_values": ModelSchemaValue.from_value(
                            allowed_types
                        ),
                    }},
                ),
            )

        # Validate input and output models are specified
        if not self.input_model or not self.output_model:
            msg = "Both input_model and output_model must be specified"
            raise ModelOnexError(
                message=msg,
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                details=ModelErrorContext.with_context(
                    {{
                        "error_type": ModelSchemaValue.from_value("valueerror"),
                        "validation_context": ModelSchemaValue.from_value(
                            "model_validation",
                        ),
                        "field": ModelSchemaValue.from_value("input_model/output_model"),
                    }},
                ),
            )

        return self

    model_config = ConfigDict(
        extra="ignore",  # Allow extra fields from YAML contracts
        use_enum_values=False,  # Keep enum objects, don't convert to strings
        validate_assignment=True,  # Validate on attribute assignment
    )
