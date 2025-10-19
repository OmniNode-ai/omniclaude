#!/usr/bin/env python3
"""
Contract and Subcontract Generation Service

Handles generation of ONEX contracts and subcontracts for node implementations
including input/output schemas, error codes, CLI interfaces, and execution capabilities.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from omni_agent.config.settings import OmniAgentSettings
from omni_agent.workflow.contract_models import (
    ModelContractCapabilities,
    ModelContractCLI,
    ModelContractErrorCode,
    ModelContractSchema,
    ModelGeneratedContract,
)
from pydantic import BaseModel, Field

from ..models import ModelTier

# Lazy import to avoid circular imports
# from ..workflows.smart_responder_chain import SmartResponderChain


class ContractType(Enum):
    """Types of contracts that can be generated."""

    MAIN_CONTRACT = "main_contract"
    SUB_CONTRACT = "sub_contract"
    INTERFACE_CONTRACT = "interface_contract"
    DATA_CONTRACT = "data_contract"


class SchemaComplexity(Enum):
    """Complexity levels for schema generation."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    HIGHLY_COMPLEX = "highly_complex"


@dataclass
class ContractGenerationContext:
    """Context information for contract generation."""

    task_title: str
    task_description: str
    node_type: str
    dependencies: List[Dict[str, Any]]
    method_signatures: List[Dict[str, Any]]
    infrastructure_context: Dict[str, Any]
    project_context: Dict[str, Any]


@dataclass
class GeneratedContract:
    """Represents a generated contract with metadata."""

    contract_type: ContractType
    contract_name: str
    contract_version: str
    contract_content: ModelGeneratedContract
    complexity_score: float
    validation_passed: bool
    generation_metadata: Dict[str, Any]


class ModelContractGenerationRequest(BaseModel):
    """Request model for contract generation."""

    task_title: str = Field(
        ..., description="Title of the task for contract generation"
    )
    task_description: str = Field(..., description="Detailed description of the task")
    node_type: str = Field(
        ..., description="Target node type (COMPUTE, EFFECT, REDUCER, ORCHESTRATOR)"
    )
    dependencies: List[Dict[str, Any]] = Field(
        default_factory=list, description="Analyzed dependencies"
    )
    method_signatures: List[Dict[str, Any]] = Field(
        default_factory=list, description="Required method signatures"
    )
    infrastructure_context: Dict[str, Any] = Field(
        default_factory=dict, description="Infrastructure context"
    )
    project_context: Dict[str, Any] = Field(
        default_factory=dict, description="Project context"
    )
    contract_types: List[str] = Field(
        default_factory=lambda: ["main_contract"],
        description="Types of contracts to generate",
    )
    include_cli_interface: bool = Field(
        default=True, description="Whether to include CLI interface"
    )
    include_capabilities: bool = Field(
        default=True, description="Whether to include execution capabilities"
    )
    validation_level: str = Field(
        default="strict", description="Validation level: basic, standard, strict"
    )


class ModelContractGenerationResponse(BaseModel):
    """Response model for contract generation."""

    success: bool = Field(..., description="Whether contract generation was successful")
    contracts: List[Dict[str, Any]] = Field(
        default_factory=list, description="Generated contracts"
    )
    subcontracts: List[Dict[str, Any]] = Field(
        default_factory=list, description="Generated subcontracts"
    )
    total_contracts: int = Field(0, description="Total number of contracts generated")
    validation_results: Dict[str, Any] = Field(
        default_factory=dict, description="Contract validation results"
    )
    complexity_analysis: Dict[str, Any] = Field(
        default_factory=dict, description="Complexity analysis of generated contracts"
    )
    schema_definitions: Dict[str, Any] = Field(
        default_factory=dict, description="Shared schema definitions"
    )
    error_codes: Dict[str, Any] = Field(
        default_factory=dict, description="Comprehensive error code definitions"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Implementation recommendations"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Contract generation warnings"
    )
    error_message: Optional[str] = Field(
        None, description="Error message if generation failed"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Generation metadata"
    )


class ContractGenerationService:
    """Service for generating ONEX contracts and subcontracts."""

    def __init__(self, settings: Optional[OmniAgentSettings] = None):
        """Initialize the contract generation service."""
        self.settings = settings or OmniAgentSettings()
        self.responder_chain = None  # Lazy initialization
        self.logger = logging.getLogger(__name__)

    def _get_responder_chain(self):
        """Lazy initialization of SmartResponderChain to avoid circular imports."""
        if self.responder_chain is None:
            from ..workflows.smart_responder_chain import SmartResponderChain

            self.responder_chain = SmartResponderChain()
        return self.responder_chain

    async def generate_contracts(
        self, request: ModelContractGenerationRequest
    ) -> ModelContractGenerationResponse:
        """
        Generate comprehensive contracts and subcontracts for node implementation.

        Args:
            request: Contract generation request

        Returns:
            ModelContractGenerationResponse with generated contracts
        """
        try:
            self.logger.info(
                f"Starting contract generation for task: {request.task_title}"
            )

            generation_context = ContractGenerationContext(
                task_title=request.task_title,
                task_description=request.task_description,
                node_type=request.node_type,
                dependencies=request.dependencies,
                method_signatures=request.method_signatures,
                infrastructure_context=request.infrastructure_context,
                project_context=request.project_context,
            )

            # Step 1: Generate main contract
            main_contract = await self._generate_main_contract(
                generation_context, request
            )

            # Step 2: Generate subcontracts
            subcontracts = await self._generate_subcontracts(
                generation_context, main_contract
            )

            # Step 3: Generate shared schema definitions
            schema_definitions = await self._generate_shared_schemas(
                generation_context, main_contract
            )

            # Step 4: Generate comprehensive error codes
            error_codes = await self._generate_error_codes(
                generation_context, main_contract
            )

            # Step 5: Validate generated contracts
            validation_results = await self._validate_contracts(
                main_contract, subcontracts
            )

            # Step 6: Analyze complexity
            complexity_analysis = await self._analyze_contract_complexity(
                main_contract, subcontracts
            )

            # Step 7: Generate recommendations
            recommendations = await self._generate_contract_recommendations(
                generation_context, main_contract, complexity_analysis
            )

            contracts = [self._serialize_contract(main_contract)]
            serialized_subcontracts = [
                self._serialize_contract(sc) for sc in subcontracts
            ]

            response = ModelContractGenerationResponse(
                success=True,
                contracts=contracts,
                subcontracts=serialized_subcontracts,
                total_contracts=len(contracts) + len(serialized_subcontracts),
                validation_results=validation_results,
                complexity_analysis=complexity_analysis,
                schema_definitions=schema_definitions,
                error_codes=error_codes,
                recommendations=recommendations,
                metadata={
                    "generation_timestamp": "2024-01-01T00:00:00Z",  # Would use actual timestamp
                    "node_type": request.node_type,
                    "validation_level": request.validation_level,
                },
            )

            self.logger.info(
                f"Contract generation completed. "
                f"Total contracts: {response.total_contracts}, "
                f"Validation passed: {validation_results.get('overall_passed', False)}"
            )

            return response

        except Exception as e:
            error_msg = f"Contract generation failed: {e}"
            self.logger.error(error_msg)

            return ModelContractGenerationResponse(
                success=False,
                error_message=error_msg,
                metadata={"error_type": type(e).__name__},
            )

    async def _generate_main_contract(
        self,
        context: ContractGenerationContext,
        request: ModelContractGenerationRequest,
    ) -> GeneratedContract:
        """Generate the main contract for the node implementation."""

        prompt = f"""
# ONEX Contract Generation Request

Generate a comprehensive ONEX contract for the following node implementation:

## Node Details:
- **Task**: {context.task_title}
- **Description**: {context.task_description}
- **Node Type**: {context.node_type}

## Dependencies Analysis:
{self._format_dependencies_for_prompt(context.dependencies)}

## Method Signatures:
{self._format_method_signatures_for_prompt(context.method_signatures)}

## Infrastructure Context:
{json.dumps(context.infrastructure_context, indent=2) if context.infrastructure_context else "No infrastructure context"}

## Contract Generation Requirements:

### 1. Contract Metadata
- Contract name following ONEX naming conventions
- Version following semantic versioning
- Comprehensive description and documentation
- Associated documents and references

### 2. Input State Schema
- Complete input validation schema
- Required and optional parameters
- Data type specifications with constraints
- Nested object definitions
- Array specifications with item schemas

### 3. Output State Schema
- Comprehensive output schema definition
- Success response structure
- Partial response handling
- Metadata and pagination support
- Performance metrics inclusion

### 4. Error Code Definitions
- Comprehensive error code catalog
- Business logic errors
- Validation errors
- Infrastructure errors
- Integration errors
- Error severity levels and handling

### 5. CLI Interface (if requested)
- Command-line entry points
- Parameter definitions
- Help text and examples
- Subcommand structure
- Configuration options

### 6. Execution Capabilities
- Supported node types and deployment modes
- Performance constraints and requirements
- Resource requirements and limits
- Scaling characteristics
- Security requirements

## ONEX Contract Format:

Generate a complete OpenAPI 3.0 compatible contract following ONEX standards:

```json
{{
    "openapi": "3.0.0",
    "info": {{
        "title": "NodeUserAuthentication Contract",
        "version": "1.0.0",
        "description": "ONEX contract for user authentication service node",
        "contact": {{
            "name": "Generated by OmniAgent",
            "url": "https://github.com/OmniNode-ai/omniagent"
        }}
    }},
    "associated_documents": {{
        "prd": {{
            "title": "Product Requirements Document",
            "url": "/docs/prd/user-authentication.md"
        }},
        "architecture": {{
            "title": "Architecture Decision Records",
            "url": "/docs/architecture/auth-service-adr.md"
        }}
    }},
    "input_state": {{
        "type": "object",
        "properties": {{
            "credentials": {{
                "type": "object",
                "properties": {{
                    "username": {{"type": "string", "minLength": 3, "maxLength": 50}},
                    "password": {{"type": "string", "minLength": 8, "maxLength": 128}}
                }},
                "required": ["username", "password"]
            }},
            "options": {{
                "type": "object",
                "properties": {{
                    "remember_me": {{"type": "boolean", "default": false}},
                    "session_timeout": {{"type": "integer", "minimum": 300, "maximum": 86400}}
                }}
            }}
        }},
        "required": ["credentials"],
        "additionalProperties": false
    }},
    "output_state": {{
        "type": "object",
        "properties": {{
            "success": {{"type": "boolean"}},
            "user_id": {{"type": "string", "format": "uuid"}},
            "access_token": {{"type": "string"}},
            "refresh_token": {{"type": "string"}},
            "expires_at": {{"type": "string", "format": "date-time"}},
            "user_profile": {{
                "type": "object",
                "properties": {{
                    "username": {{"type": "string"}},
                    "email": {{"type": "string", "format": "email"}},
                    "roles": {{"type": "array", "items": {{"type": "string"}}}}
                }}
            }},
            "metadata": {{
                "type": "object",
                "properties": {{
                    "login_timestamp": {{"type": "string", "format": "date-time"}},
                    "session_id": {{"type": "string", "format": "uuid"}},
                    "login_source": {{"type": "string"}}
                }}
            }}
        }},
        "required": ["success", "user_id", "access_token"],
        "additionalProperties": false
    }},
    "error_codes": {{
        "INVALID_CREDENTIALS": {{
            "code": "AUTH_001",
            "message": "Invalid username or password",
            "severity": "error"
        }},
        "ACCOUNT_LOCKED": {{
            "code": "AUTH_002",
            "message": "Account has been locked due to multiple failed attempts",
            "severity": "error"
        }},
        "VALIDATION_ERROR": {{
            "code": "VAL_001",
            "message": "Input validation failed",
            "severity": "error"
        }}
    }},
    "definitions": {{
        "UserCredentials": {{
            "type": "object",
            "properties": {{
                "username": {{"type": "string"}},
                "password": {{"type": "string"}}
            }}
        }}
    }},
    "cli_interface": {{
        "entrypoint": "onex run user_authentication",
        "commands": [
            {{
                "name": "authenticate",
                "description": "Authenticate user credentials",
                "parameters": [
                    {{"name": "--username", "type": "string", "required": true}},
                    {{"name": "--password", "type": "string", "required": true}}
                ]
            }}
        ]
    }},
    "execution_capabilities": {{
        "supported_node_types": ["COMPUTE"],
        "supported_delivery_modes": ["sync", "async"],
        "performance_constraints": {{
            "max_response_time_ms": 5000,
            "max_concurrent_requests": 1000,
            "memory_limit_mb": 512
        }}
    }}
}}
```

Ensure the contract is complete, valid, and follows ONEX architecture principles.
Focus on practical, implementable schemas that will support robust node development.
"""

        try:
            response, metrics = await self._get_responder_chain().process_request(
                task_prompt=prompt,
                context={"purpose": "ONEX main contract generation"},
                max_tier=ModelTier.TIER_6_LOCAL_HUGE,  # Use more powerful model for contract generation
                enable_consensus=True,
            )

            # Parse contract data
            contract_data = json.loads(response.content)

            # Convert to ModelGeneratedContract
            contract_content = ModelGeneratedContract(
                openapi=contract_data.get("openapi", "3.0.0"),
                info=contract_data["info"],
                associated_documents=contract_data.get("associated_documents"),
                input_state=ModelContractSchema(**contract_data["input_state"]),
                output_state=ModelContractSchema(**contract_data["output_state"]),
                error_codes={
                    code: ModelContractErrorCode(**error_data)
                    for code, error_data in contract_data["error_codes"].items()
                },
                definitions=(
                    {
                        name: ModelContractSchema(**schema_data)
                        for name, schema_data in contract_data.get(
                            "definitions", {}
                        ).items()
                    }
                    if contract_data.get("definitions")
                    else None
                ),
                cli_interface=(
                    ModelContractCLI(**contract_data["cli_interface"])
                    if contract_data.get("cli_interface")
                    else None
                ),
                execution_capabilities=(
                    ModelContractCapabilities(**contract_data["execution_capabilities"])
                    if contract_data.get("execution_capabilities")
                    else None
                ),
            )

            # Calculate complexity score
            complexity_score = self._calculate_contract_complexity(contract_content)

            generated_contract = GeneratedContract(
                contract_type=ContractType.MAIN_CONTRACT,
                contract_name=contract_data["info"]["title"],
                contract_version=contract_data["info"]["version"],
                contract_content=contract_content,
                complexity_score=complexity_score,
                validation_passed=True,  # Will be validated later
                generation_metadata={
                    "generation_metrics": metrics.__dict__ if metrics else {},
                    "prompt_tokens": len(prompt.split()),
                    "response_tokens": len(response.content.split()),
                },
            )

            return generated_contract

        except Exception as e:
            self.logger.error(f"Failed to generate main contract: {e}")
            # Return a minimal contract as fallback
            return self._create_fallback_contract(context)

    async def _generate_subcontracts(
        self, context: ContractGenerationContext, main_contract: GeneratedContract
    ) -> List[GeneratedContract]:
        """Generate subcontracts for complex integrations."""

        subcontracts = []

        # Identify subcontract needs based on dependencies
        complex_deps = [
            dep
            for dep in context.dependencies
            if dep.get("criticality") == "critical"
            and dep.get("dependency_type") == "internal"
        ]

        for dep in complex_deps:
            subcontract = await self._generate_dependency_subcontract(
                context, dep, main_contract
            )
            if subcontract:
                subcontracts.append(subcontract)

        # Generate interface subcontracts for async operations
        async_methods = [
            sig for sig in context.method_signatures if sig.get("is_async", False)
        ]

        if len(async_methods) > 3:  # Generate async interface contract
            async_contract = await self._generate_async_interface_contract(
                context, async_methods
            )
            if async_contract:
                subcontracts.append(async_contract)

        return subcontracts

    async def _generate_dependency_subcontract(
        self,
        context: ContractGenerationContext,
        dependency: Dict[str, Any],
        main_contract: GeneratedContract,
    ) -> Optional[GeneratedContract]:
        """Generate a subcontract for a specific dependency."""

        # This would generate a specialized subcontract for internal service dependencies
        # For now, return a simple structure

        try:
            subcontract_name = f"{dependency['name']}_integration_contract"

            # Create a basic subcontract structure
            basic_info = {
                "title": f"{dependency['name']} Integration Contract",
                "version": "1.0.0",
                "description": f"Subcontract for {dependency['name']} integration",
            }

            # Create basic input/output schemas for the integration
            input_schema = ModelContractSchema(
                type="object",
                properties={
                    "integration_params": {
                        "type": "object",
                        "description": f"Parameters for {dependency['name']} integration",
                    }
                },
                required=["integration_params"],
            )

            output_schema = ModelContractSchema(
                type="object",
                properties={
                    "integration_result": {
                        "type": "object",
                        "description": f"Result from {dependency['name']} integration",
                    }
                },
                required=["integration_result"],
            )

            contract_content = ModelGeneratedContract(
                openapi="3.0.0",
                info=basic_info,
                input_state=input_schema,
                output_state=output_schema,
                error_codes={
                    "INTEGRATION_ERROR": ModelContractErrorCode(
                        code="INT_001",
                        message=f"Integration with {dependency['name']} failed",
                        severity="error",
                    )
                },
            )

            return GeneratedContract(
                contract_type=ContractType.SUB_CONTRACT,
                contract_name=subcontract_name,
                contract_version="1.0.0",
                contract_content=contract_content,
                complexity_score=0.3,  # Subcontracts are generally simpler
                validation_passed=True,
                generation_metadata={
                    "dependency_name": dependency["name"],
                    "integration_pattern": dependency.get(
                        "integration_pattern", "unknown"
                    ),
                },
            )

        except Exception as e:
            self.logger.error(
                f"Failed to generate subcontract for {dependency['name']}: {e}"
            )
            return None

    async def _generate_async_interface_contract(
        self, context: ContractGenerationContext, async_methods: List[Dict[str, Any]]
    ) -> Optional[GeneratedContract]:
        """Generate an interface contract for async operations."""

        # Generate a specialized contract for async operations
        try:
            contract_content = ModelGeneratedContract(
                openapi="3.0.0",
                info={
                    "title": f"{context.task_title} Async Interface Contract",
                    "version": "1.0.0",
                    "description": "Contract for asynchronous operations",
                },
                input_state=ModelContractSchema(
                    type="object",
                    properties={
                        "operation_id": {"type": "string", "format": "uuid"},
                        "async_params": {"type": "object"},
                    },
                    required=["operation_id"],
                ),
                output_state=ModelContractSchema(
                    type="object",
                    properties={
                        "operation_id": {"type": "string", "format": "uuid"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "completed", "failed"],
                        },
                        "result": {"type": "object"},
                    },
                    required=["operation_id", "status"],
                ),
                error_codes={
                    "ASYNC_OPERATION_FAILED": ModelContractErrorCode(
                        code="ASYNC_001",
                        message="Asynchronous operation failed",
                        severity="error",
                    )
                },
            )

            return GeneratedContract(
                contract_type=ContractType.INTERFACE_CONTRACT,
                contract_name=f"{context.task_title}_async_interface",
                contract_version="1.0.0",
                contract_content=contract_content,
                complexity_score=0.4,
                validation_passed=True,
                generation_metadata={
                    "async_method_count": len(async_methods),
                    "interface_type": "async_operations",
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to generate async interface contract: {e}")
            return None

    async def _generate_shared_schemas(
        self, context: ContractGenerationContext, main_contract: GeneratedContract
    ) -> Dict[str, Any]:
        """Generate shared schema definitions."""

        # Extract common patterns from the main contract and create reusable schemas
        shared_schemas = {
            "CommonResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
                "required": ["success"],
            },
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "error": {"type": "boolean", "const": True},
                    "error_code": {"type": "string"},
                    "error_message": {"type": "string"},
                    "error_details": {"type": "object"},
                },
                "required": ["error", "error_code", "error_message"],
            },
        }

        return shared_schemas

    async def _generate_error_codes(
        self, context: ContractGenerationContext, main_contract: GeneratedContract
    ) -> Dict[str, Any]:
        """Generate comprehensive error code definitions."""

        error_codes = {
            # Business logic errors
            "BUSINESS_RULE_VIOLATION": {
                "code": "BIZ_001",
                "message": "Business rule validation failed",
                "severity": "error",
                "category": "business_logic",
            },
            # Validation errors
            "INPUT_VALIDATION_FAILED": {
                "code": "VAL_001",
                "message": "Input validation failed",
                "severity": "error",
                "category": "validation",
            },
            "SCHEMA_VALIDATION_ERROR": {
                "code": "VAL_002",
                "message": "Schema validation error",
                "severity": "error",
                "category": "validation",
            },
            # Infrastructure errors
            "DATABASE_CONNECTION_FAILED": {
                "code": "INF_001",
                "message": "Database connection failed",
                "severity": "error",
                "category": "infrastructure",
            },
            "EXTERNAL_SERVICE_UNAVAILABLE": {
                "code": "INF_002",
                "message": "External service is unavailable",
                "severity": "error",
                "category": "infrastructure",
            },
            # Security errors
            "AUTHENTICATION_FAILED": {
                "code": "SEC_001",
                "message": "Authentication failed",
                "severity": "error",
                "category": "security",
            },
            "AUTHORIZATION_DENIED": {
                "code": "SEC_002",
                "message": "Authorization denied",
                "severity": "error",
                "category": "security",
            },
            # System errors
            "INTERNAL_SERVER_ERROR": {
                "code": "SYS_001",
                "message": "Internal server error occurred",
                "severity": "error",
                "category": "system",
            },
            "RESOURCE_EXHAUSTED": {
                "code": "SYS_002",
                "message": "System resources exhausted",
                "severity": "error",
                "category": "system",
            },
        }

        return error_codes

    async def _validate_contracts(
        self, main_contract: GeneratedContract, subcontracts: List[GeneratedContract]
    ) -> Dict[str, Any]:
        """Validate generated contracts for completeness and correctness."""

        validation_results = {
            "overall_passed": True,
            "main_contract": {"valid": True, "issues": []},
            "subcontracts": [],
            "schema_validation": {"valid": True, "issues": []},
            "consistency_check": {"valid": True, "issues": []},
        }

        # Validate main contract
        main_issues = []

        # Check required fields
        if not main_contract.contract_content.info:
            main_issues.append("Missing contract info section")

        if not main_contract.contract_content.input_state:
            main_issues.append("Missing input state schema")

        if not main_contract.contract_content.output_state:
            main_issues.append("Missing output state schema")

        if not main_contract.contract_content.error_codes:
            main_issues.append("Missing error code definitions")

        validation_results["main_contract"]["issues"] = main_issues
        validation_results["main_contract"]["valid"] = len(main_issues) == 0

        # Validate subcontracts
        for subcontract in subcontracts:
            subcontract_validation = {
                "name": subcontract.contract_name,
                "valid": True,
                "issues": [],
            }

            # Basic subcontract validation
            if not subcontract.contract_content.input_state:
                subcontract_validation["issues"].append("Missing input state schema")
                subcontract_validation["valid"] = False

            validation_results["subcontracts"].append(subcontract_validation)

        # Update overall validation status
        validation_results["overall_passed"] = validation_results["main_contract"][
            "valid"
        ] and all(sc["valid"] for sc in validation_results["subcontracts"])

        return validation_results

    async def _analyze_contract_complexity(
        self, main_contract: GeneratedContract, subcontracts: List[GeneratedContract]
    ) -> Dict[str, Any]:
        """Analyze the complexity of generated contracts."""

        # Calculate complexity metrics
        input_properties = len(
            main_contract.contract_content.input_state.properties or {}
        )
        output_properties = len(
            main_contract.contract_content.output_state.properties or {}
        )
        error_codes = len(main_contract.contract_content.error_codes)
        subcontract_count = len(subcontracts)

        # Simple complexity scoring
        complexity_score = min(
            1.0,
            (
                input_properties * 0.1
                + output_properties * 0.1
                + error_codes * 0.05
                + subcontract_count * 0.2
            )
            / 10,
        )

        return {
            "overall_complexity": complexity_score,
            "main_contract_complexity": main_contract.complexity_score,
            "subcontract_complexity": sum(sc.complexity_score for sc in subcontracts)
            / max(len(subcontracts), 1),
            "metrics": {
                "input_properties": input_properties,
                "output_properties": output_properties,
                "error_codes": error_codes,
                "subcontract_count": subcontract_count,
            },
            "complexity_level": self._categorize_complexity(complexity_score),
        }

    async def _generate_contract_recommendations(
        self,
        context: ContractGenerationContext,
        main_contract: GeneratedContract,
        complexity_analysis: Dict[str, Any],
    ) -> List[str]:
        """Generate implementation recommendations based on contract analysis."""

        recommendations = []

        complexity = complexity_analysis["overall_complexity"]

        if complexity > 0.7:
            recommendations.append(
                "High contract complexity detected - consider breaking into smaller, focused contracts"
            )

        if len(main_contract.contract_content.error_codes) > 15:
            recommendations.append(
                "Large number of error codes - consider grouping related errors and using error categories"
            )

        input_props = complexity_analysis["metrics"]["input_properties"]
        if input_props > 20:
            recommendations.append(
                "Complex input schema - consider using nested objects or optional parameter groups"
            )

        # Node type specific recommendations
        if context.node_type == "COMPUTE":
            recommendations.append(
                "Implement proper timeout handling and resource management for compute operations"
            )
        elif context.node_type == "EFFECT":
            recommendations.append(
                "Ensure idempotent operations and proper rollback mechanisms for side effects"
            )

        return recommendations

    def _calculate_contract_complexity(self, contract: ModelGeneratedContract) -> float:
        """Calculate complexity score for a contract."""

        factors = {
            "input_properties": len(contract.input_state.properties or {}),
            "output_properties": len(contract.output_state.properties or {}),
            "error_codes": len(contract.error_codes),
            "has_cli": 1 if contract.cli_interface else 0,
            "has_capabilities": 1 if contract.execution_capabilities else 0,
        }

        # Simple complexity calculation
        complexity = min(
            1.0,
            (
                factors["input_properties"] * 0.05
                + factors["output_properties"] * 0.05
                + factors["error_codes"] * 0.03
                + factors["has_cli"] * 0.1
                + factors["has_capabilities"] * 0.1
            ),
        )

        return complexity

    def _categorize_complexity(self, score: float) -> str:
        """Categorize complexity score into human-readable levels."""
        if score < 0.3:
            return "simple"
        elif score < 0.5:
            return "moderate"
        elif score < 0.7:
            return "complex"
        else:
            return "highly_complex"

    def _format_dependencies_for_prompt(
        self, dependencies: List[Dict[str, Any]]
    ) -> str:
        """Format dependencies for inclusion in prompts."""
        if not dependencies:
            return "No dependencies analyzed"

        formatted = []
        for dep in dependencies[:10]:  # Limit to first 10 for prompt size
            formatted.append(
                f"- **{dep.get('name', 'Unknown')}**: {dep.get('purpose', 'No purpose specified')} "
                f"(Criticality: {dep.get('criticality', 'unknown')})"
            )

        if len(dependencies) > 10:
            formatted.append(f"... and {len(dependencies) - 10} more dependencies")

        return "\n".join(formatted)

    def _format_method_signatures_for_prompt(
        self, signatures: List[Dict[str, Any]]
    ) -> str:
        """Format method signatures for inclusion in prompts."""
        if not signatures:
            return "No method signatures analyzed"

        formatted = []
        for sig in signatures[:8]:  # Limit to first 8 for prompt size
            formatted.append(
                f"- **{sig.get('method_name', 'unknown')}**: {sig.get('return_type', 'unknown')} "
                f"({'async' if sig.get('is_async') else 'sync'})"
            )

        if len(signatures) > 8:
            formatted.append(f"... and {len(signatures) - 8} more method signatures")

        return "\n".join(formatted)

    def _create_fallback_contract(
        self, context: ContractGenerationContext
    ) -> GeneratedContract:
        """Create a minimal fallback contract when generation fails."""

        # Create basic contract structure
        basic_info = {
            "title": f"Node{context.task_title.replace(' ', '')}",
            "version": "1.0.0",
            "description": f"Fallback contract for {context.task_title}",
        }

        input_schema = ModelContractSchema(
            type="object",
            properties={
                "input": {"type": "object", "description": "Task input parameters"}
            },
            required=["input"],
        )

        output_schema = ModelContractSchema(
            type="object",
            properties={
                "result": {"type": "object", "description": "Task execution result"},
                "success": {
                    "type": "boolean",
                    "description": "Execution success indicator",
                },
            },
            required=["result", "success"],
        )

        contract_content = ModelGeneratedContract(
            openapi="3.0.0",
            info=basic_info,
            input_state=input_schema,
            output_state=output_schema,
            error_codes={
                "EXECUTION_ERROR": ModelContractErrorCode(
                    code="ERR_001", message="Task execution failed", severity="error"
                )
            },
        )

        return GeneratedContract(
            contract_type=ContractType.MAIN_CONTRACT,
            contract_name=basic_info["title"],
            contract_version=basic_info["version"],
            contract_content=contract_content,
            complexity_score=0.2,
            validation_passed=False,
            generation_metadata={"fallback": True},
        )

    def _serialize_contract(self, contract: GeneratedContract) -> Dict[str, Any]:
        """Serialize a GeneratedContract for response."""
        return {
            "contract_type": contract.contract_type.value,
            "contract_name": contract.contract_name,
            "contract_version": contract.contract_version,
            "contract_content": contract.contract_content.dict(),
            "complexity_score": contract.complexity_score,
            "validation_passed": contract.validation_passed,
            "generation_metadata": contract.generation_metadata,
        }


# Factory function for service instantiation
def create_contract_generation_service(
    settings: Optional[OmniAgentSettings] = None,
) -> ContractGenerationService:
    """Create and return a ContractGenerationService instance."""
    return ContractGenerationService(settings)
