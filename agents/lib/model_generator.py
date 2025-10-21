#!/usr/bin/env python3
"""
Model Generator for Phase 4 - Autonomous Code Generation

Generates Pydantic models for ONEX-compliant services from PRD analysis.
Supports input models, output models, configuration models, and field inference.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from omnibase_core.errors import EnumCoreErrorCode, OnexError

logger = logging.getLogger(__name__)


@dataclass
class ModelField:
    """Represents a field in a Pydantic model"""

    name: str
    type_hint: str
    default_value: Optional[str] = None
    description: str = ""
    field_validator: Optional[str] = None
    is_required: bool = True


@dataclass
class GeneratedModel:
    """Represents a generated Pydantic model"""

    model_name: str
    model_type: str  # 'input', 'output', 'config'
    fields: List[ModelField]
    imports: List[str]
    validators: List[str] = field(default_factory=list)
    class_config: Optional[Dict[str, Any]] = None


@dataclass
class ModelGenerationResult:
    """Result of model generation"""

    session_id: UUID
    correlation_id: UUID
    service_name: str
    input_model: Optional[GeneratedModel] = None
    output_model: Optional[GeneratedModel] = None
    config_model: Optional[GeneratedModel] = None
    input_model_code: str = ""
    output_model_code: str = ""
    config_model_code: str = ""
    quality_score: float = 0.0
    onex_compliant: bool = False
    violations: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)


class ModelGenerator:
    """
    Model Generator for ONEX-compliant Pydantic models.

    Generates input models, output models, and configuration models
    from PRD analysis results with strong typing and ONEX compliance.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Type mapping for common field patterns
        # ORDER MATTERS: More specific patterns first, then general patterns
        self.type_inference_map = {
            # IDs and identifiers (specific before general)
            r".*_id$": "UUID",
            r"^id$": "UUID",
            r"correlation_id": "UUID",
            r"session_id": "UUID",
            # Timestamps (specific before general)
            r".*_at$": "datetime",
            r"timestamp": "datetime",
            r"created": "datetime",
            r"updated": "datetime",
            # Scores and rates (must come before bool patterns to catch success_rate)
            r".*_score$": "float",
            r".*_rate$": "float",
            r".*_ratio$": "float",
            r"confidence": "float",
            # Boolean flags (after numeric patterns to avoid false matches)
            r"^is_.*": "bool",
            r"^has_.*": "bool",
            r"^can_.*": "bool",
            r"^should_.*": "bool",
            r".*_enabled$": "bool",
            r"^success$": "bool",  # Changed to match exactly "success" only
            # Counts and numbers
            r".*_count$": "int",
            r".*_number$": "int",
            r".*_size$": "int",
            r".*_limit$": "int",
            r".*_timeout$": "int",
            r".*_seconds$": "int",
            r"port": "int",
            # Collections
            r".*_list$": "List[str]",
            r".*_items$": "List[Dict[str, Any]]",
            r"tags": "List[str]",
            r"errors": "List[str]",
            r"warnings": "List[str]",
            # Metadata and data
            r"metadata": "Dict[str, str]",
            r".*_data$": "Dict[str, Any]",
            r"result_data": "Dict[str, Any]",
            r"request_data": "Dict[str, Any]",
            # String defaults
            r".*_type$": "str",
            r".*_name$": "str",
            r".*_url$": "str",
            r"message": "str",
            r"error": "str",
            r"description": "str",
        }

    async def generate_all_models(
        self,
        service_name: str,
        prd_analysis: Any,  # SimplePRDAnalysisResult
        session_id: Optional[UUID] = None,
        correlation_id: Optional[UUID] = None,
    ) -> ModelGenerationResult:
        """
        Generate all models (input, output, config) concurrently.

        Args:
            service_name: Name of the service (e.g., "UserAuthentication")
            prd_analysis: PRD analysis result from SimplePRDAnalyzer
            session_id: Optional session identifier
            correlation_id: Optional correlation identifier

        Returns:
            ModelGenerationResult with all generated models
        """
        session_id = session_id or uuid4()
        correlation_id = correlation_id or uuid4()

        self.logger.info(
            f"Starting model generation for {service_name} (session: {session_id})"
        )

        try:
            # Generate all models concurrently
            input_model_task = self.generate_input_model(service_name, prd_analysis)
            output_model_task = self.generate_output_model(service_name, prd_analysis)
            config_model_task = self.generate_config_model(service_name, prd_analysis)

            input_model, output_model, config_model = await asyncio.gather(
                input_model_task, output_model_task, config_model_task
            )

            # Generate code from models
            input_code = self._generate_model_code(input_model)
            output_code = self._generate_model_code(output_model)
            config_code = self._generate_model_code(config_model)

            # Validate ONEX compliance
            quality_score, onex_compliant, violations = await self.validate_model_code(
                input_code, output_code, config_code
            )

            result = ModelGenerationResult(
                session_id=session_id,
                correlation_id=correlation_id,
                service_name=service_name,
                input_model=input_model,
                output_model=output_model,
                config_model=config_model,
                input_model_code=input_code,
                output_model_code=output_code,
                config_model_code=config_code,
                quality_score=quality_score,
                onex_compliant=onex_compliant,
                violations=violations,
            )

            self.logger.info(
                f"Model generation completed for {service_name} "
                f"(quality: {quality_score:.2f}, compliant: {onex_compliant})"
            )

            return result

        except Exception as e:
            self.logger.error(f"Model generation failed for {service_name}: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Model generation failed: {str(e)}",
                details={"service_name": service_name, "session_id": str(session_id)},
            )

    async def generate_input_model(
        self, service_name: str, prd_analysis: Any
    ) -> GeneratedModel:
        """
        Generate Pydantic input model from PRD analysis.

        Args:
            service_name: Service name (e.g., "UserAuthentication")
            prd_analysis: PRD analysis result

        Returns:
            GeneratedModel for input
        """
        self.logger.info(f"Generating input model for {service_name}")

        # Infer fields from functional requirements
        inferred_fields = self.infer_model_fields(
            prd_analysis.parsed_prd.functional_requirements,
            prd_analysis.parsed_prd.technical_details,
            model_type="input",
        )

        # Always include standard input fields
        standard_fields = [
            ModelField(
                name="operation_type",
                type_hint="str",  # Will reference enum
                description=f"Type of {service_name} operation to perform",
                is_required=True,
            ),
            ModelField(
                name="correlation_id",
                type_hint="UUID",
                default_value="Field(default_factory=uuid4)",
                description="Unique identifier for request correlation",
                is_required=False,
            ),
            ModelField(
                name="session_id",
                type_hint="Optional[UUID]",
                default_value="None",
                description="Optional session identifier",
                is_required=False,
            ),
        ]

        # Combine standard fields with inferred fields
        all_fields = standard_fields + inferred_fields

        # Add metadata field
        all_fields.append(
            ModelField(
                name="metadata",
                type_hint="Optional[Dict[str, str]]",
                default_value="None",
                description="Optional metadata for the request",
                is_required=False,
            )
        )

        # Add created_at timestamp
        all_fields.append(
            ModelField(
                name="created_at",
                type_hint="datetime",
                default_value="Field(default_factory=lambda: datetime.now(timezone.utc))",
                description="Timestamp when the request was created",
                is_required=False,
            )
        )

        # Define required imports
        imports = [
            "from pydantic import BaseModel, Field",
            "from typing import Optional, Dict, Any, List",
            "from uuid import UUID, uuid4",
            "from datetime import datetime, timezone",
        ]

        # Create class config with example
        class_config = {
            "json_schema_extra": {
                "example": {
                    "operation_type": "create",
                    "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
                    "session_id": "123e4567-e89b-12d3-a456-426614174001",
                    "metadata": {"source": "api", "version": "1.0"},
                }
            }
        }

        model = GeneratedModel(
            model_name=f"Model{service_name}Input",
            model_type="input",
            fields=all_fields,
            imports=imports,
            class_config=class_config,
        )

        return model

    async def generate_output_model(
        self, service_name: str, prd_analysis: Any
    ) -> GeneratedModel:
        """
        Generate Pydantic output model from PRD analysis.

        Args:
            service_name: Service name
            prd_analysis: PRD analysis result

        Returns:
            GeneratedModel for output
        """
        self.logger.info(f"Generating output model for {service_name}")

        # Infer fields from success criteria
        inferred_fields = self.infer_model_fields(
            prd_analysis.parsed_prd.success_criteria,
            prd_analysis.parsed_prd.features,
            model_type="output",
        )

        # Standard output fields
        standard_fields = [
            ModelField(
                name="success",
                type_hint="bool",
                description="Whether the operation succeeded",
                is_required=True,
            ),
            ModelField(
                name="correlation_id",
                type_hint="UUID",
                description="Correlation identifier from input",
                is_required=True,
            ),
        ]

        # Combine with inferred fields
        all_fields = standard_fields + inferred_fields

        # Add error field
        all_fields.append(
            ModelField(
                name="error",
                type_hint="Optional[str]",
                default_value="None",
                description="Error message if operation failed",
                is_required=False,
            )
        )

        # Add metadata field
        all_fields.append(
            ModelField(
                name="metadata",
                type_hint="Optional[Dict[str, str]]",
                default_value="None",
                description="Optional metadata for the response",
                is_required=False,
            )
        )

        # Add completed_at timestamp
        all_fields.append(
            ModelField(
                name="completed_at",
                type_hint="datetime",
                default_value="Field(default_factory=lambda: datetime.now(timezone.utc))",
                description="Timestamp when the operation completed",
                is_required=False,
            )
        )

        imports = [
            "from pydantic import BaseModel, Field",
            "from typing import Optional, Dict, Any, List",
            "from uuid import UUID",
            "from datetime import datetime, timezone",
        ]

        class_config = {
            "json_schema_extra": {
                "example": {
                    "success": True,
                    "correlation_id": "123e4567-e89b-12d3-a456-426614174000",
                    "result_data": {"status": "completed"},
                    "metadata": {"processing_time_ms": 150},
                }
            }
        }

        model = GeneratedModel(
            model_name=f"Model{service_name}Output",
            model_type="output",
            fields=all_fields,
            imports=imports,
            class_config=class_config,
        )

        return model

    async def generate_config_model(
        self, service_name: str, prd_analysis: Any
    ) -> GeneratedModel:
        """
        Generate Pydantic configuration model from PRD analysis.

        Args:
            service_name: Service name
            prd_analysis: PRD analysis result

        Returns:
            GeneratedModel for configuration
        """
        self.logger.info(f"Generating config model for {service_name}")

        # Infer fields from technical details
        inferred_fields = self.infer_model_fields(
            prd_analysis.parsed_prd.technical_details, [], model_type="config"
        )

        # Standard configuration fields
        standard_fields = [
            ModelField(
                name="timeout_seconds",
                type_hint="int",
                default_value="30",
                description="Operation timeout in seconds",
                is_required=False,
            ),
            ModelField(
                name="retry_attempts",
                type_hint="int",
                default_value="3",
                description="Number of retry attempts on failure",
                is_required=False,
            ),
            ModelField(
                name="cache_enabled",
                type_hint="bool",
                default_value="True",
                description="Whether caching is enabled",
                is_required=False,
            ),
            ModelField(
                name="log_level",
                type_hint="str",
                default_value='"INFO"',
                description="Logging level for the service",
                is_required=False,
            ),
        ]

        # Combine with inferred fields
        all_fields = standard_fields + inferred_fields

        imports = [
            "from pydantic import BaseModel, Field",
            "from typing import Optional, Dict, Any, List",
        ]

        class_config = {
            "json_schema_extra": {
                "example": {
                    "timeout_seconds": 30,
                    "retry_attempts": 3,
                    "cache_enabled": True,
                    "log_level": "INFO",
                }
            }
        }

        model = GeneratedModel(
            model_name=f"Model{service_name}Config",
            model_type="config",
            fields=all_fields,
            imports=imports,
            class_config=class_config,
        )

        return model

    def infer_model_fields(
        self, requirements: List[str], additional_context: List[str], model_type: str
    ) -> List[ModelField]:
        """
        Infer model fields from PRD requirements using pattern matching.

        Args:
            requirements: List of requirements to analyze
            additional_context: Additional context for inference
            model_type: Type of model ('input', 'output', 'config')

        Returns:
            List of inferred ModelField objects
        """
        fields = []

        # Combine all text for analysis
        all_text = " ".join(requirements + additional_context).lower()

        # Extract potential field names from text
        field_candidates = self._extract_field_candidates(all_text)

        for candidate in field_candidates:
            # Infer type for this field
            field_type = self._infer_field_type(candidate)

            # Determine if field is required (more strict for input)
            is_required = model_type == "input" and not candidate.startswith(
                "optional_"
            )

            # Create field
            field = ModelField(
                name=candidate,
                type_hint=field_type,
                default_value=(
                    "None" if not is_required and "Optional" not in field_type else None
                ),
                description=f"{candidate.replace('_', ' ').title()}",
                is_required=is_required,
            )

            fields.append(field)

        return fields

    def _extract_field_candidates(self, text: str) -> List[str]:
        """Extract potential field names from text using keyword patterns"""
        candidates = set()

        # Common patterns for different model types
        patterns = [
            r"\b(user_id|username|email|password)\b",
            r"\b(api_key|token|secret)\b",
            r"\b(data|payload|body)\b",
            r"\b(status|state|result)\b",
            r"\b(message|error|warning)\b",
            r"\b(limit|offset|page_size)\b",
            r"\b(filter|query|search)\b",
            r"\b(url|endpoint|path)\b",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            candidates.update(matches)

        # Add result_data for output models if not empty
        if candidates:
            candidates.add("result_data")

        return sorted(list(candidates))[:5]  # Limit to 5 inferred fields

    def _infer_field_type(self, field_name: str) -> str:
        """
        Infer Python type hint for a field based on its name.

        Args:
            field_name: Name of the field

        Returns:
            Python type hint string
        """
        # Check against type inference patterns
        for pattern, type_hint in self.type_inference_map.items():
            if re.match(pattern, field_name, re.IGNORECASE):
                return type_hint

        # Default to string for unknown fields
        return "str"

    def _generate_model_code(self, model: GeneratedModel) -> str:
        """
        Generate Python code from a GeneratedModel.

        Args:
            model: GeneratedModel to convert to code

        Returns:
            Python source code string
        """
        lines = []

        # Add docstring header
        lines.append('"""')
        lines.append(f"{model.model_name} - ONEX {model.model_type.upper()} Model")
        lines.append("")
        lines.append(f"Generated Pydantic model for {model.model_type} operations.")
        lines.append('"""')
        lines.append("")

        # Add imports
        for import_line in sorted(set(model.imports)):
            lines.append(import_line)
        lines.append("")
        lines.append("")

        # Add class definition
        lines.append(f"class {model.model_name}(BaseModel):")
        lines.append('    """')
        lines.append(f"    {model.model_type.title()} model for operations.")
        lines.append('    """')
        lines.append("")

        # Add fields
        for model_field in model.fields:
            # Add field docstring as comment
            if model_field.description:
                lines.append(f"    # {model_field.description}")

            # Build field definition
            if model_field.default_value:
                field_def = f"    {model_field.name}: {model_field.type_hint} = {model_field.default_value}"
            else:
                field_def = f"    {model_field.name}: {model_field.type_hint}"

            lines.append(field_def)

        # Add class config if present
        if model.class_config:
            lines.append("")
            lines.append("    class Config:")
            for key, value in model.class_config.items():
                lines.append(f"        {key} = {repr(value)}")

        return "\n".join(lines)

    async def validate_model_code(
        self, input_code: str, output_code: str, config_code: str
    ) -> Tuple[float, bool, List[str]]:
        """
        Validate generated model code for ONEX compliance.

        Args:
            input_code: Generated input model code
            output_code: Generated output model code
            config_code: Generated config model code

        Returns:
            Tuple of (quality_score, onex_compliant, violations)
        """
        violations = []
        quality_score = 1.0

        # Check 1: No bare 'Any' types (should be Dict[str, Any] or List[Any])
        for code, model_type in [
            (input_code, "input"),
            (output_code, "output"),
            (config_code, "config"),
        ]:
            # Look for ": Any" which indicates bare Any usage
            if re.search(r":\s*Any\s*(?:=|$)", code):
                violations.append(
                    f"{model_type} model uses bare 'Any' type (should use Dict[str, Any] or List[Any])"
                )
                quality_score -= 0.15

        # Check 2: All models inherit from BaseModel
        for code, model_type in [
            (input_code, "input"),
            (output_code, "output"),
            (config_code, "config"),
        ]:
            if "class Model" not in code or "(BaseModel)" not in code:
                violations.append(f"{model_type} model does not inherit from BaseModel")
                quality_score -= 0.2

        # Check 3: Docstrings present
        for code, model_type in [
            (input_code, "input"),
            (output_code, "output"),
            (config_code, "config"),
        ]:
            if '"""' not in code:
                violations.append(f"{model_type} model missing docstrings")
                quality_score -= 0.1

        # Check 4: Required fields present in input/output
        if "correlation_id" not in input_code:
            violations.append("input model missing correlation_id field")
            quality_score -= 0.1

        if "success" not in output_code:
            violations.append("output model missing success field")
            quality_score -= 0.1

        # Check 5: Imports are complete
        for code, model_type in [
            (input_code, "input"),
            (output_code, "output"),
            (config_code, "config"),
        ]:
            if "from pydantic import" not in code:
                violations.append(f"{model_type} model missing pydantic imports")
                quality_score -= 0.15

        # Ensure quality score doesn't go below 0
        quality_score = max(0.0, quality_score)

        # ONEX compliant if quality score >= 0.7 and no critical violations
        onex_compliant = quality_score >= 0.7 and len(violations) <= 3

        return quality_score, onex_compliant, violations
