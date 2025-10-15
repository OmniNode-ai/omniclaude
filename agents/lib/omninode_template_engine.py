#!/usr/bin/env python3
"""
OmniNode Template Engine

Uses omnibase_core models and contracts to generate OmniNode implementations.
"""

import os
import re
import logging
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from uuid import UUID
from datetime import datetime, timezone

# Import from omnibase_core
from omnibase_core.errors import OnexError, EnumCoreErrorCode
from omnibase_core.enums.enum_node_type import EnumNodeType

# TODO: Add omnibase_spi imports when available
# from omnibase_spi.validation.tool_metadata_validator import ToolMetadataValidator

from .version_config import get_config
from .simple_prd_analyzer import SimplePRDAnalysisResult

logger = logging.getLogger(__name__)

class NodeTemplate:
    """Template for generating OmniNode implementations"""
    
    def __init__(self, node_type: str, template_content: str):
        self.node_type = node_type
        self.template_content = template_content
        self.placeholders = self._extract_placeholders()
    
    def _extract_placeholders(self) -> Set[str]:
        """Extract placeholder variables from template"""
        pattern = r'\{([A-Z_]+)\}'
        return set(re.findall(pattern, self.template_content))
    
    def render(self, context: Dict[str, Any]) -> str:
        """Render template with context variables"""
        rendered = self.template_content
        
        for key, value in context.items():
            placeholder = f"{{{key}}}"
            if placeholder in rendered:
                rendered = rendered.replace(placeholder, str(value))
        
        return rendered

class OmniNodeTemplateEngine:
    """Template engine for generating OmniNode implementations"""
    
    def __init__(self):
        self.config = get_config()
        self.templates_dir = Path(self.config.template_directory)
        # TODO: Initialize validator when omnibase_spi is available
        # self.metadata_validator = ToolMetadataValidator()
        self.logger = logging.getLogger(__name__)
        
        # Load templates
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, NodeTemplate]:
        """Load node templates from filesystem"""
        templates = {}
        
        # Load EFFECT template
        effect_template_path = self.templates_dir / "effect_node_template.py"
        if effect_template_path.exists():
            with open(effect_template_path, 'r') as f:
                templates["EFFECT"] = NodeTemplate("EFFECT", f.read())
        
        # Load COMPUTE template
        compute_template_path = self.templates_dir / "compute_node_template.py"
        if compute_template_path.exists():
            with open(compute_template_path, 'r') as f:
                templates["COMPUTE"] = NodeTemplate("COMPUTE", f.read())
        
        # Load REDUCER template
        reducer_template_path = self.templates_dir / "reducer_node_template.py"
        if reducer_template_path.exists():
            with open(reducer_template_path, 'r') as f:
                templates["REDUCER"] = NodeTemplate("REDUCER", f.read())
        
        # Load ORCHESTRATOR template
        orchestrator_template_path = self.templates_dir / "orchestrator_node_template.py"
        if orchestrator_template_path.exists():
            with open(orchestrator_template_path, 'r') as f:
                templates["ORCHESTRATOR"] = NodeTemplate("ORCHESTRATOR", f.read())
        
        return templates
    
    async def generate_node(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        output_directory: str
    ) -> Dict[str, Any]:
        """
        Generate OmniNode implementation from PRD analysis.
        
        Args:
            analysis_result: PRD analysis result
            node_type: Type of node to generate (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            output_directory: Directory to write generated files
            
        Returns:
            Dictionary with generated files and metadata
            
        Raises:
            OnexError: If generation fails
        """
        try:
            self.logger.info(f"Generating {node_type} node: {microservice_name}")
            
            # Get template for node type
            template = self.templates.get(node_type)
            if not template:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"No template found for node type: {node_type}",
                    details={"available_templates": list(self.templates.keys())}
                )
            
            # Prepare context for template rendering
            context = self._prepare_template_context(
                analysis_result, node_type, microservice_name, domain
            )
            
            # Generate node implementation
            node_content = template.render(context)
            
            # Generate additional files
            generated_files = await self._generate_additional_files(
                analysis_result, node_type, microservice_name, domain, context
            )
            
            # Create output directory structure
            output_path = Path(output_directory)
            node_path = output_path / f"node_{domain}_{microservice_name}_{node_type.lower()}"
            node_path.mkdir(parents=True, exist_ok=True)
            
            # Write main node file
            main_file_path = node_path / "v1_0_0" / "node.py"
            main_file_path.parent.mkdir(exist_ok=True)
            with open(main_file_path, 'w') as f:
                f.write(node_content)
            
            # Write additional files
            for file_path, content in generated_files.items():
                full_path = node_path / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)
            
            # Generate metadata
            metadata = self._generate_node_metadata(
                node_type, microservice_name, domain, analysis_result
            )

            # Build full file paths for generated_files
            full_file_paths = [str(node_path / file_path) for file_path in generated_files.keys()]

            return {
                "node_type": node_type,
                "microservice_name": microservice_name,
                "domain": domain,
                "output_path": str(node_path),
                "main_file": str(main_file_path),
                "generated_files": full_file_paths,
                "metadata": {
                    "session_id": str(analysis_result.session_id),
                    "correlation_id": str(analysis_result.correlation_id),
                    "node_metadata": metadata,
                    "confidence_score": analysis_result.confidence_score,
                    "quality_baseline": analysis_result.quality_baseline,
                },
                "context": context
            }
            
        except Exception as e:
            self.logger.error(f"Node generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Node generation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain
                }
            )
    
    def _prepare_template_context(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str
    ) -> Dict[str, Any]:
        """Prepare context variables for template rendering"""
        
        # Basic context
        context = {
            "DOMAIN": domain,
            "MICROSERVICE_NAME": microservice_name,
            "MICROSERVICE_NAME_PASCAL": self._to_pascal_case(microservice_name),
            "DOMAIN_PASCAL": self._to_pascal_case(domain),
            "NODE_TYPE": node_type,
            "BUSINESS_DESCRIPTION": analysis_result.parsed_prd.description,
            "REPOSITORY_NAME": "omniclaude",  # Default for now
        }
        
        # Add mixin information
        mixins = analysis_result.recommended_mixins
        context["MIXIN_IMPORTS"] = self._generate_mixin_imports(mixins)
        context["MIXIN_INHERITANCE"] = self._generate_mixin_inheritance(mixins)
        context["MIXIN_INITIALIZATION"] = self._generate_mixin_initialization(mixins)
        
        # Add business logic stub
        context["BUSINESS_LOGIC_STUB"] = self._generate_business_logic_stub(
            analysis_result, node_type, microservice_name
        )
        
        # Add operations from decomposition
        operations = self._extract_operations(analysis_result.decomposition_result)
        context["OPERATIONS"] = operations
        
        # Add features
        features = analysis_result.parsed_prd.features[:3]  # Top 3 features
        context["FEATURES"] = features
        
        return context
    
    def _to_pascal_case(self, text: str) -> str:
        """Convert text to PascalCase"""
        return ''.join(word.capitalize() for word in text.replace('_', ' ').replace('-', ' ').split())
    
    def _generate_mixin_imports(self, mixins: List[str]) -> str:
        """Generate mixin import statements"""
        if not mixins:
            return ""
        
        imports = []
        for mixin in mixins:
            imports.append(f"from omnibase_core.mixins.{mixin.lower()} import {mixin}")
        
        return "\n".join(imports)
    
    def _generate_mixin_inheritance(self, mixins: List[str]) -> str:
        """Generate mixin inheritance chain"""
        if not mixins:
            return ""
        
        return ", " + ", ".join(mixins)
    
    def _generate_mixin_initialization(self, mixins: List[str]) -> str:
        """Generate mixin initialization code"""
        # Mixins handle their own initialization via __init__ methods
        # No explicit initialization code needed
        return ""
    
    def _generate_business_logic_stub(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        microservice_name: str
    ) -> str:
        """Generate business logic stub based on analysis"""
        stub = f"        # TODO: Implement {microservice_name} {node_type.lower()} logic\n"
        stub += "        # Based on requirements:\n"
        
        for req in analysis_result.parsed_prd.functional_requirements[:3]:
            stub += f"        # - {req}\n"
        
        stub += "        # External systems:\n"
        for system in analysis_result.external_systems:
            stub += f"        # - {system}\n"
        
        return stub
    
    def _extract_operations(self, decomposition_result) -> List[str]:
        """Extract operations from task decomposition"""
        operations = []
        for task in decomposition_result.tasks[:3]:  # Top 3 tasks
            if isinstance(task, dict):
                operations.append(task.get("title", "Unknown Task"))
            else:
                operations.append(task.title)
        return operations
    
    async def _generate_additional_files(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        context: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generate additional files (models, contracts, manifests, etc.)"""
        files = {}

        # Generate input model
        files["v1_0_0/models/model_{}_input.py".format(microservice_name)] = self._generate_input_model(
            microservice_name, analysis_result
        )

        # Generate output model
        files["v1_0_0/models/model_{}_output.py".format(microservice_name)] = self._generate_output_model(
            microservice_name, analysis_result
        )

        # Generate config model
        files["v1_0_0/models/model_{}_config.py".format(microservice_name)] = self._generate_config_model(
            microservice_name, analysis_result
        )

        # Generate contract model (NEW: Phase 6 enhancement)
        files["v1_0_0/models/model_{}_{}_contract.py".format(microservice_name, node_type.lower())] = self._generate_contract_model(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate enum
        files["v1_0_0/enums/enum_{}_operation_type.py".format(microservice_name)] = self._generate_operation_enum(
            microservice_name, analysis_result
        )

        # Generate contract YAML (UPDATED: Phase 6 enhancement with full ONEX compliance)
        files["v1_0_0/contract.yaml"] = self._generate_contract_yaml(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate node manifest (NEW: Phase 6 enhancement)
        files["node.manifest.yaml"] = self._generate_node_manifest(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate version manifest (NEW: Phase 6 enhancement)
        files["v1_0_0/version.manifest.yaml"] = self._generate_version_manifest(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate __init__.py files
        files["v1_0_0/__init__.py"] = self._generate_version_init()
        files["v1_0_0/models/__init__.py"] = self._generate_models_init(microservice_name, node_type)
        files["v1_0_0/enums/__init__.py"] = self._generate_enums_init(microservice_name)

        return files
    
    def _generate_input_model(self, microservice_name: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Generate input model"""
        pascal_name = self._to_pascal_case(microservice_name)
        
        return f'''#!/usr/bin/env python3
"""
Input model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from omnibase_core.core.node_effect import ModelEffectInput

class Model{pascal_name}Input(ModelEffectInput):
    """Input envelope for {microservice_name} operations"""
    
    # Add node-specific fields here
    operation_type: str = Field(..., description="Type of operation to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Operation parameters")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
'''
    
    def _generate_output_model(self, microservice_name: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Generate output model"""
        pascal_name = self._to_pascal_case(microservice_name)
        
        return f'''#!/usr/bin/env python3
"""
Output model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from omnibase_core.core.node_effect import ModelEffectOutput

class Model{pascal_name}Output(ModelEffectOutput):
    """Output envelope for {microservice_name} operations"""
    
    # Add node-specific fields here
    result_data: Dict[str, Any] = Field(default_factory=dict, description="Operation result data")
    success: bool = Field(..., description="Operation success status")
    error_message: Optional[str] = Field(None, description="Error message if operation failed")
'''
    
    def _generate_config_model(self, microservice_name: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Generate config model"""
        pascal_name = self._to_pascal_case(microservice_name)
        
        return f'''#!/usr/bin/env python3
"""
Configuration model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class Model{pascal_name}Config(BaseModel):
    """Configuration for {microservice_name} node"""
    
    # Add configuration fields here
    timeout_seconds: int = Field(default=30, description="Operation timeout in seconds")
    retry_attempts: int = Field(default=3, description="Number of retry attempts")
    debug_mode: bool = Field(default=False, description="Enable debug logging")
'''
    
    def _generate_operation_enum(self, microservice_name: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Generate operation enum"""
        pascal_name = self._to_pascal_case(microservice_name)
        
        return f'''#!/usr/bin/env python3
"""
Operation type enum for {microservice_name} node
"""

from enum import Enum

class Enum{pascal_name}OperationType(Enum):
    """Operation types for {microservice_name} node"""
    
    # Add operation types here
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
'''
    
    def _generate_contract(self, microservice_name: str, node_type: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Generate YAML contract"""
        return f'''# {microservice_name} {node_type.lower()} contract
version: "1.0.0"
name: "{microservice_name}_{node_type.lower()}"
type: "{node_type.lower()}"
description: "{analysis_result.parsed_prd.description}"

# Contract definition
input_schema:
  type: object
  properties:
    operation_type:
      type: string
      enum: ["create", "read", "update", "delete"]
    parameters:
      type: object
    metadata:
      type: object
  required: ["operation_type"]

output_schema:
  type: object
  properties:
    success:
      type: boolean
    result_data:
      type: object
    error_message:
      type: string
  required: ["success"]

# Mixin requirements
mixins:
{self._generate_mixin_requirements(analysis_result.recommended_mixins)}

# External system dependencies
external_systems:
{self._generate_external_system_requirements(analysis_result.external_systems)}
'''
    
    def _generate_mixin_requirements(self, mixins: List[str]) -> str:
        """Generate mixin requirements for contract"""
        if not mixins:
            return "  - none"
        
        requirements = []
        for mixin in mixins:
            requirements.append(f"  - {mixin}")
        return "\n".join(requirements)
    
    def _generate_external_system_requirements(self, external_systems: List[str]) -> str:
        """Generate external system requirements for contract"""
        if not external_systems:
            return "  - none"
        
        systems = []
        for system in external_systems:
            systems.append(f"  - {system}")
        return "\n".join(systems)
    
    def _generate_version_init(self) -> str:
        """Generate version __init__.py"""
        return '''#!/usr/bin/env python3
"""
Version 1.0.0 exports
"""

from .node import *
from .models import *
from .enums import *
'''
    
    def _generate_models_init(self, microservice_name: str, node_type: str = None) -> str:
        """Generate models __init__.py"""
        base_imports = f'''#!/usr/bin/env python3
"""
Models for {microservice_name}
"""

from .model_{microservice_name}_input import *
from .model_{microservice_name}_output import *
from .model_{microservice_name}_config import *
'''
        # Add contract model import if node_type is provided
        if node_type:
            base_imports += f"from .model_{microservice_name}_{node_type.lower()}_contract import *\n"

        return base_imports
    
    def _generate_enums_init(self, microservice_name: str) -> str:
        """Generate enums __init__.py"""
        return f'''#!/usr/bin/env python3
"""
Enums for {microservice_name}
"""

from .enum_{microservice_name}_operation_type import *
'''

    def _generate_contract_model(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: SimplePRDAnalysisResult,
        context: Dict[str, Any]
    ) -> str:
        """Generate contract model (Python Pydantic) following ONEX patterns"""
        from uuid import uuid4
        from datetime import datetime

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_pascal = node_type.capitalize()
        node_type_lower = node_type.lower()

        # Load contract model template
        template_path = self.templates_dir / "contract_model_template.py"
        if not template_path.exists():
            # Fallback if template doesn't exist yet
            return self._generate_contract_model_fallback(microservice_name, node_type, analysis_result)

        with open(template_path, 'r') as f:
            template_content = f.read()

        # Determine performance fields based on node type
        performance_fields = self._get_performance_fields_for_node_type(node_type)

        # Determine service characteristics
        is_persistent = node_type in ["REDUCER", "ORCHESTRATOR"]
        requires_external_deps = len(analysis_result.external_systems) > 0

        # Render template
        rendered = template_content.format(
            MICROSERVICE_NAME=microservice_name,
            MICROSERVICE_NAME_PASCAL=pascal_name,
            NODE_TYPE=node_type,
            NODE_TYPE_PASCAL=node_type_pascal,
            NODE_TYPE_LOWER=node_type_lower,
            BUSINESS_DESCRIPTION=analysis_result.parsed_prd.description,
            PERFORMANCE_FIELDS=performance_fields,
            IS_PERSISTENT_SERVICE=str(is_persistent).lower(),
            REQUIRES_EXTERNAL_DEPS=str(requires_external_deps).lower()
        )

        return rendered

    def _get_performance_fields_for_node_type(self, node_type: str) -> str:
        """Get performance fields specific to node type"""
        if node_type == "COMPUTE":
            return '''single_operation_max_ms: int = Field(
        default=2000,
        ge=10,
        le=60000,
        description="Maximum milliseconds for single computation operation",
    )'''
        elif node_type == "EFFECT":
            return '''max_response_time_ms: int = Field(
        default=500,
        ge=10,
        le=10000,
        description="Maximum response time in milliseconds for effect operations",
    )'''
        elif node_type == "REDUCER":
            return '''aggregation_window_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        description="Time window in milliseconds for aggregation operations",
    )

    max_aggregation_delay_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Maximum delay allowed for aggregation completion",
    )'''
        elif node_type == "ORCHESTRATOR":
            return '''workflow_timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        description="Maximum workflow execution time in milliseconds",
    )

    coordination_overhead_ms: int = Field(
        default=100,
        ge=10,
        le=5000,
        description="Expected overhead for workflow coordination",
    )'''
        else:
            return '''max_execution_time_ms: int = Field(
        default=1000,
        ge=10,
        le=60000,
        description="Maximum execution time in milliseconds",
    )'''

    def _generate_contract_model_fallback(
        self,
        microservice_name: str,
        node_type: str,
        analysis_result: SimplePRDAnalysisResult
    ) -> str:
        """Fallback contract model generation if template doesn't exist"""
        pascal_name = self._to_pascal_case(microservice_name)
        node_type_pascal = node_type.capitalize()

        return f'''#!/usr/bin/env python3
"""
{pascal_name} {node_type} Contract Model - ONEX Standards Compliant.

VERSION: 1.0.0 - INTERFACE LOCKED FOR CODE GENERATION

{analysis_result.parsed_prd.description}

ZERO TOLERANCE: No Any types allowed in implementation.
"""

from typing import ClassVar
from pydantic import BaseModel, ConfigDict, Field
from omnibase_core.primitives.model_semver import ModelSemVer


class Model{pascal_name}{node_type_pascal}Contract(BaseModel):
    """Contract model for {microservice_name} {node_type} node."""

    INTERFACE_VERSION: ClassVar[ModelSemVer] = ModelSemVer(major=1, minor=0, patch=0)

    contract_version: ModelSemVer = Field(
        default=ModelSemVer(major=1, minor=0, patch=0),
        description="Contract version following semantic versioning",
    )

    node_name: str = Field(
        default="{microservice_name}_{node_type.lower()}",
        description="Unique identifier for this node",
    )

    description: str = Field(
        default="{analysis_result.parsed_prd.description}",
        description="Business description of this node",
    )

    node_type: str = Field(
        default="{node_type}",
        description="ONEX node type",
    )

    model_config = ConfigDict(
        extra="ignore",
        use_enum_values=False,
        validate_assignment=True,
    )
'''

    def _generate_contract_yaml(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: SimplePRDAnalysisResult,
        context: Dict[str, Any]
    ) -> str:
        """Generate comprehensive ONEX-compliant contract YAML"""
        from uuid import uuid4
        from datetime import datetime

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()

        # Build actions list
        actions_list = self._build_actions_list(analysis_result, node_type)

        # Build dependencies list
        dependencies_list = self._build_dependencies_list(analysis_result)

        # Build subcontracts based on node type and mixins
        subcontracts = self._build_subcontracts_list(node_type, analysis_result.recommended_mixins)

        # Build algorithm section (required for COMPUTE nodes)
        algorithm_section = self._build_algorithm_section(node_type, microservice_name)

        # Build performance requirements
        performance_requirements = self._build_performance_requirements(node_type)

        # Determine service characteristics
        is_persistent = "true" if node_type in ["REDUCER", "ORCHESTRATOR"] else "false"
        requires_external_deps = "true" if len(analysis_result.external_systems) > 0 else "false"

        # Build event configuration
        primary_events = self._build_primary_events(node_type, microservice_name)
        event_categories = f'["{domain}", "{node_type_lower}", "generated"]'
        publish_events = "true" if node_type in ["EFFECT", "REDUCER", "ORCHESTRATOR"] else "false"
        subscribe_events = "true" if node_type in ["ORCHESTRATOR"] else "false"

        # Build service resolution
        service_resolution = self._build_service_resolution(analysis_result)

        # Build infrastructure
        infrastructure = self._build_infrastructure(analysis_result)

        # Build constraint definitions
        constraint_definitions = self._build_constraint_definitions(microservice_name, node_type)

        contract_yaml = f'''# {pascal_name} {node_type} - ONEX Contract
# {node_type} node for {analysis_result.parsed_prd.description}

# === REQUIRED ROOT FIELDS ===
contract_version: {{major: 1, minor: 0, patch: 0}}
node_name: "{microservice_name}_{node_type_lower}"
node_version: {{major: 1, minor: 0, patch: 0}}
contract_name: "{microservice_name}_{node_type_lower}_contract"
description: "{analysis_result.parsed_prd.description}"
node_type: "{node_type}"
name: "{microservice_name}_{node_type_lower}"
version: {{major: 1, minor: 0, patch: 0}}
input_model: "Model{pascal_name}Input"
output_model: "Model{pascal_name}Output"

# === NODE CLASSIFICATION ===
# (node_type already defined above)

# === MODEL SPECIFICATIONS ===

{algorithm_section}

tool_specification:
  tool_name: "node_{domain}_{microservice_name}_{node_type_lower}"
  version: {{major: 1, minor: 0, patch: 0}}
  description: "{analysis_result.parsed_prd.description}"
  main_tool_class: "Node{pascal_name}{node_type.capitalize()}"
  container_injection: "ONEXContainer"
  business_logic_pattern: "{node_type_lower}"

# === METADATA ===
metadata:
  tier: 3
  specialization: "{node_type_lower}"
  category: "{domain}"
  architectural_pattern: "node_{node_type_lower}"
  complexity: "medium"

# === SERVICE CONFIGURATION ===
service_configuration:
  is_persistent_service: {is_persistent}
  requires_external_dependencies: {requires_external_deps}

# === INPUT/OUTPUT ===
input_state:
  object_type: "object"
  required: ["operation_type"]
  optional: ["parameters", "metadata", "correlation_id"]

output_state:
  object_type: "object"
  required: ["success", "result_data"]
  optional: ["error_message", "metadata"]

# === ACTIONS ===
actions:
{actions_list}

# === DEPENDENCIES ===
dependencies:
{dependencies_list}

# === PERFORMANCE ===
performance:
{performance_requirements}

# === EVENT TYPE CONFIGURATION ===
event_type:
  primary_events: {primary_events}
  event_categories: {event_categories}
  publish_events: {publish_events}
  subscribe_events: {subscribe_events}
  event_routing: "{domain}"

# === SERVICE RESOLUTION ===
service_resolution:
{service_resolution}

infrastructure:
{infrastructure}

# === ONEX COMPLIANCE ===
contract_driven: true
strong_typing: true
zero_any_types: true
protocol_based: true

# === VALIDATION ===
validation_rules:
  strict_typing_enabled: true
  input_validation_enabled: true
  output_validation_enabled: true
  performance_validation_enabled: true
  constraint_definitions:
{constraint_definitions}

# === SUBCONTRACTS ===
subcontracts:
{subcontracts}

# === DEFINITIONS (Required by ModelContractContent) ===
definitions:
  models: {{}}
  schemas: {{}}
  responses: {{}}
'''

        return contract_yaml

    def _build_actions_list(self, analysis_result: SimplePRDAnalysisResult, node_type: str) -> str:
        """Build actions list for contract"""
        actions = []

        # Extract operations from PRD
        operations = analysis_result.parsed_prd.functional_requirements[:3]

        for idx, req in enumerate(operations, 1):
            # Create action name from requirement
            action_name = self._requirement_to_action_name(req)
            actions.append(f'''  - name: "{action_name}"
    description: "{req}"
    inputs: ["input_data"]
    outputs: ["result"]''')

        # Add standard actions
        actions.append('''  - name: "health_check"
    description: "Check node health status"
    inputs: []
    outputs: ["status"]''')

        return "\n\n".join(actions) if actions else "  []"

    def _requirement_to_action_name(self, requirement: str) -> str:
        """Convert requirement to snake_case action name"""
        # Simple heuristic: take first few words, convert to snake_case
        words = requirement.lower().split()[:3]
        # Remove common words
        words = [w for w in words if w not in ['the', 'a', 'an', 'and', 'or', 'with']]
        return "_".join(words[:3])

    def _build_dependencies_list(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build dependencies list for contract"""
        if not analysis_result.external_systems:
            return "  []"

        deps = []
        for system in analysis_result.external_systems[:3]:
            system_lower = system.lower().replace(" ", "_")
            deps.append(f'''  - name: "{system_lower}"
    type: "external_service"
    class_name: "Protocol{system.replace(' ', '')}"
    module: "omnibase.protocol.protocol_{system_lower}"''')

        return "\n".join(deps)

    def _build_subcontracts_list(self, node_type: str, mixins: List[str]) -> str:
        """Build subcontracts list based on node type and mixins"""
        subcontracts = []

        # Standard subcontracts for all nodes
        subcontracts.extend([
            '''  - path: "../../subcontracts/health_check_subcontract.yaml"
    integration_field: "health_check_configuration"''',
            '''  - path: "../../subcontracts/introspection_subcontract.yaml"
    integration_field: "introspection_configuration"''',
            '''  - path: "../../subcontracts/performance_monitoring_subcontract.yaml"
    integration_field: "performance_monitoring_configuration"''',
            '''  - path: "../../subcontracts/request_response_subcontract.yaml"
    integration_field: "request_response_configuration"'''
        ])

        # Add mixin-specific subcontracts
        if "MixinEventBus" in mixins or "MixinRetry" in mixins:
            subcontracts.append('''  - path: "../../mixins/mixin_error_handling.yaml"
    integration_field: "error_handling_configuration"''')

        return "\n".join(subcontracts)

    def _build_algorithm_section(self, node_type: str, microservice_name: str) -> str:
        """Build algorithm section (required for COMPUTE nodes)"""
        if node_type != "COMPUTE":
            return "# === NODE CONFIGURATION ===\n# No algorithm section required for non-COMPUTE nodes"

        return f'''# === ALGORITHM CONFIGURATION (Required for COMPUTE nodes) ===
algorithm:
  algorithm_type: "{microservice_name}_computation"
  factors:
    primary_computation:
      weight: 0.6
      calculation_method: "primary_algorithm"
      parameters:
        threshold: 0.8
      normalization_enabled: true
      caching_enabled: true
    secondary_computation:
      weight: 0.3
      calculation_method: "secondary_algorithm"
      parameters:
        factor: 1.5
      normalization_enabled: true
      caching_enabled: true
    validation:
      weight: 0.1
      calculation_method: "validation_check"
      parameters:
        strict_mode: true
      normalization_enabled: true
      caching_enabled: false'''

    def _build_performance_requirements(self, node_type: str) -> str:
        """Build performance requirements based on node type"""
        if node_type == "COMPUTE":
            return "  single_operation_max_ms: 2000"
        elif node_type == "EFFECT":
            return "  max_response_time_ms: 500"
        elif node_type == "REDUCER":
            return "  aggregation_window_ms: 1000\n  max_aggregation_delay_ms: 5000"
        elif node_type == "ORCHESTRATOR":
            return "  workflow_timeout_ms: 30000\n  coordination_overhead_ms: 100"
        else:
            return "  max_execution_time_ms: 1000"

    def _build_primary_events(self, node_type: str, microservice_name: str) -> str:
        """Build primary events list"""
        events = []
        if node_type == "EFFECT":
            events = [f"{microservice_name}_created", f"{microservice_name}_updated", f"{microservice_name}_deleted"]
        elif node_type == "COMPUTE":
            events = [f"{microservice_name}_computed", f"{microservice_name}_validated"]
        elif node_type == "REDUCER":
            events = [f"{microservice_name}_aggregated", f"{microservice_name}_reduced"]
        elif node_type == "ORCHESTRATOR":
            events = [f"{microservice_name}_workflow_started", f"{microservice_name}_workflow_completed"]
        else:
            events = [f"{microservice_name}_executed"]

        return f'["{events[0]}", "{events[1] if len(events) > 1 else events[0]}"]'

    def _build_service_resolution(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build service resolution configuration"""
        if "Kafka" in analysis_result.external_systems or "EventBus" in str(analysis_result.recommended_mixins):
            return '''  event_bus:
    protocol: "ProtocolEventBus"
    strategy: "hybrid"
    primary: "kafka"
    fallback: "event_bus_client"
    discovery: "consul"'''
        else:
            return "  # No service resolution required"

    def _build_infrastructure(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build infrastructure configuration"""
        if "Kafka" in analysis_result.external_systems:
            return '''  event_bus: {strategy: "hybrid", primary: "kafka", fallback: "http", consul_discovery: true}'''
        else:
            return "  # No special infrastructure requirements"

    def _build_constraint_definitions(self, microservice_name: str, node_type: str) -> str:
        """Build constraint definitions"""
        return f'''    operation_type: "string type with values [create, read, update, delete]"
    input_data: "dict type required for {microservice_name} operations"
    result_data: "dict type for operation results"'''

    def _generate_node_manifest(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: SimplePRDAnalysisResult,
        context: Dict[str, Any]
    ) -> str:
        """Generate node.manifest.yaml file"""
        from uuid import uuid4
        from datetime import datetime
        import hashlib

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()
        node_uuid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Generate hash (placeholder - in production would hash actual content)
        content_hash = hashlib.sha256(f"{microservice_name}_{node_type}_{now}".encode()).hexdigest()

        # Build capabilities
        capabilities = self._build_capabilities_list(analysis_result, node_type)

        # Build protocols
        protocols = self._build_protocols_list(node_type)

        # Build dependencies for manifest
        dependencies_manifest = self._build_dependencies_manifest(analysis_result)

        # Build test cases
        canonical_test_cases = self._build_canonical_test_cases(microservice_name, node_type)

        # Build external endpoints
        external_endpoints = self._build_external_endpoints(analysis_result)

        # Build audit events
        audit_events = self._build_audit_events(microservice_name, node_type)

        # Build tags
        tags = self._build_tags(domain, node_type, analysis_result)

        # Determine configuration values
        initialization_order = 3
        max_memory_mb = 512
        max_cpu_percent = 40
        timeout_seconds = 120
        min_coverage = 85.0
        processes_sensitive_data = "false"
        data_classification = "internal"
        requires_network_access = "true" if analysis_result.external_systems else "false"

        manifest = f'''schema_version: {{major: 1, minor: 0, patch: 0}}
name: "node_{domain}_{microservice_name}_{node_type_lower}"
uuid: "{node_uuid}"
author: "OmniClaude Code Generation"
created_at: "{now}"
last_modified_at: "{now}"
description: "{analysis_result.parsed_prd.description}"
state_contract: "state_contract://{microservice_name}_{node_type_lower}_schema.json"
lifecycle: "active"
hash: "{content_hash}"
entrypoint:
  type: "python"
  target: "v1_0_0/node.py"
namespace: "omninode.generated.{domain}.node_{microservice_name}_{node_type_lower}"
meta_type: "node"
runtime_language_hint: "python>=3.11"

# === NODE CAPABILITIES ===
capabilities:
{capabilities}

protocols_supported:
{protocols}

dependencies:
{dependencies_manifest}

# === VERSION MANAGEMENT (via x_extensions) ===
x_extensions:
  version_management:
    # Current version information
    current_stable: {{major: 1, minor: 0, patch: 0}}
    current_development: null

    # Version catalog with lifecycle states
    versions:
      v1_0_0:
        version: {{major: 1, minor: 0, patch: 0}}
        status: "active"
        release_date: "{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        breaking_changes: false
        recommended: true
        deprecation_date: null
        end_of_life: null

    # Discovery configuration for services loading this node
    discovery:
      auto_load_strategy: "current_stable"
      fallback_versions: [{{major: 1, minor: 0, patch: 0}}]
      version_directory_pattern: "v{{major}}_{{minor}}_{{patch}}"
      implementation_file: "node.py"
      contract_file: "contract.yaml"
      main_class_name: "Node{pascal_name}{node_type.capitalize()}"

    # Service loading configuration
    service_integration:
      load_as_module: true
      requires_separate_port: false
      initialization_order: {initialization_order}
      shutdown_timeout: 30
      health_check_via_service: true

# === EXECUTION METADATA ===
execution_mode: "async"
execution_constraints:
  max_memory_mb: {max_memory_mb}
  max_cpu_percent: {max_cpu_percent}
  timeout_seconds: {timeout_seconds}

# === TESTING METADATA ===
testing:
  required_ci_tiers:
    - "mock"
    - "integration"
  minimum_coverage_percentage: {min_coverage}
  canonical_test_case_ids:
{canonical_test_cases}

# === SECURITY METADATA ===
data_handling_declaration:
  processes_sensitive_data: {processes_sensitive_data}
  data_classification: "{data_classification}"

security_context:
  requires_network_access: {requires_network_access}
  external_endpoints:
{external_endpoints}

# === LOGGING CONFIGURATION ===
logging_config:
  level: "info"
  format: "json"
  audit_events:
{audit_events}

tags:
{tags}
'''

        return manifest

    def _build_capabilities_list(self, analysis_result: SimplePRDAnalysisResult, node_type: str) -> str:
        """Build capabilities list for manifest"""
        capabilities = []

        # Extract from functional requirements
        for req in analysis_result.parsed_prd.functional_requirements[:3]:
            cap_name = self._requirement_to_action_name(req)
            capabilities.append(f'  - "{cap_name}"')

        # Add node type specific capabilities
        if node_type == "EFFECT":
            capabilities.append('  - "external_io"')
        elif node_type == "COMPUTE":
            capabilities.append('  - "pure_computation"')
        elif node_type == "REDUCER":
            capabilities.append('  - "state_aggregation"')
        elif node_type == "ORCHESTRATOR":
            capabilities.append('  - "workflow_coordination"')

        return "\n".join(capabilities) if capabilities else "  []"

    def _build_protocols_list(self, node_type: str) -> str:
        """Build protocols list for manifest"""
        protocols = []

        if node_type == "EFFECT":
            protocols = ['"ProtocolNodeEffect"', '"ProtocolEventBus"']
        elif node_type == "COMPUTE":
            protocols = ['"ProtocolNodeCompute"']
        elif node_type == "REDUCER":
            protocols = ['"ProtocolNodeReducer"', '"ProtocolEventBus"']
        elif node_type == "ORCHESTRATOR":
            protocols = ['"ProtocolNodeOrchestrator"', '"ProtocolEventBus"', '"ProtocolWorkflow"']

        return "\n  - " + "\n  - ".join(protocols) if protocols else "  []"

    def _build_dependencies_manifest(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build dependencies list for node manifest"""
        if not analysis_result.external_systems:
            return "  []"

        deps = []
        for system in analysis_result.external_systems[:3]:
            system_lower = system.lower().replace(" ", "_")
            deps.append(f'''  - name: "{system_lower}"
    type: "external_service"
    target: "{system_lower}://localhost:5432"
    binding: "runtime_lookup"
    optional: false
    description: "{system} service for data operations"''')

        return "\n".join(deps)

    def _build_canonical_test_cases(self, microservice_name: str, node_type: str) -> str:
        """Build canonical test cases list"""
        test_cases = [
            f'    - "test_{microservice_name}_{node_type.lower()}_basic"',
            f'    - "test_{microservice_name}_{node_type.lower()}_error_handling"',
            f'    - "test_{microservice_name}_{node_type.lower()}_performance"'
        ]
        return "\n".join(test_cases)

    def _build_external_endpoints(self, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build external endpoints list"""
        if not analysis_result.external_systems:
            return "    []"

        endpoints = []
        for system in analysis_result.external_systems[:3]:
            if "postgres" in system.lower() or "database" in system.lower():
                endpoints.append('    - "postgresql://localhost:5432"')
            elif "redis" in system.lower() or "cache" in system.lower():
                endpoints.append('    - "redis://localhost:6379"')
            elif "kafka" in system.lower():
                endpoints.append('    - "kafka://localhost:9092"')

        return "\n".join(endpoints) if endpoints else "    []"

    def _build_audit_events(self, microservice_name: str, node_type: str) -> str:
        """Build audit events list"""
        events = [
            f'    - "{microservice_name}_initialized"',
            f'    - "{microservice_name}_executed"',
            f'    - "{microservice_name}_completed"',
            f'    - "{microservice_name}_error_occurred"'
        ]
        return "\n".join(events)

    def _build_tags(self, domain: str, node_type: str, analysis_result: SimplePRDAnalysisResult) -> str:
        """Build tags list"""
        tags = [
            f'  - "{domain}"',
            f'  - "{node_type.lower()}"',
            '  - "generated"',
            '  - "omniclaude"'
        ]

        # Add keywords from PRD
        for keyword in analysis_result.parsed_prd.extracted_keywords[:3]:
            tags.append(f'  - "{keyword}"')

        return "\n".join(tags)

    def _generate_version_manifest(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: SimplePRDAnalysisResult,
        context: Dict[str, Any]
    ) -> str:
        """Generate version.manifest.yaml file"""
        from datetime import datetime

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()
        release_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        # Determine entry point
        if node_type == "EFFECT":
            entry_point = "execute_effect"
        elif node_type == "COMPUTE":
            entry_point = "execute_compute"
        elif node_type == "REDUCER":
            entry_point = "execute_reduction"
        elif node_type == "ORCHESTRATOR":
            entry_point = "orchestrate_workflow"
        else:
            entry_point = "execute"

        # Configuration values
        min_coverage = 85
        min_memory_mb = 64
        max_memory_mb = 512
        cpu_cores = 2
        event_bus_required = "true" if node_type in ["EFFECT", "REDUCER", "ORCHESTRATOR"] else "false"
        processes_sensitive_data = "false"
        code_coverage = 85
        cyclomatic_complexity = 10
        maintainability_index = 80
        technical_debt_ratio = 0.08

        manifest = f'''# ONEX Version Manifest - {pascal_name} {node_type.capitalize()} v1.0.0
# Tier 3: Version-specific implementation details

# === VERSION IDENTITY ===
version: {{major: 1, minor: 0, patch: 0}}
version_string: {{major: 1, minor: 0, patch: 0}}
status: "active"
release_date: "{release_date}"
security_profile: "SP0_BOOTSTRAP"

# === IMPLEMENTATION ===
implementation:
  contract_file: "contract.yaml"
  main_implementation: "node.py"
  module_init: "__init__.py"

  model_files:
    - "models/model_{microservice_name}_input.py"
    - "models/model_{microservice_name}_output.py"
    - "models/model_{microservice_name}_config.py"
    - "models/model_{microservice_name}_{node_type_lower}_contract.py"

  enum_files:
    - "enums/enum_{microservice_name}_operation_type.py"

  contract_files:
    - "contract.yaml"

# === VALIDATION ===
validation:
  contract_compliance:
    onex_pattern: true
    required_fields: ["contract_version", "node_name", "node_type", "input_model", "output_model"]
    strong_typing: true

  testing_requirements:
    unit_tests: true
    integration_tests: true
    contract_validation: true
    coverage_minimum: {min_coverage}

# === DEPLOYMENT ===
deployment:
  execution_constraints:
    min_memory_mb: {min_memory_mb}
    max_memory_mb: {max_memory_mb}
    cpu_cores: {cpu_cores}

  runtime_requirements:
    python_version: ">=3.11"
    container_support: true
    event_bus_required: {event_bus_required}

# === SECURITY ===
security:
  data_handling:
    input_validation: "strict"
    output_sanitization: true
    sensitive_data: {processes_sensitive_data}

  security_context:
    sp0_compliant: true
    authentication_required: true
    authorization_levels: ["service"]

# === API SURFACE ===
api_surface:
  primary_entry_point: "{entry_point}"
  model_contracts:
    input: "Model{pascal_name}Input"
    output: "Model{pascal_name}Output"
    contract: "Model{pascal_name}{node_type.capitalize()}Contract"

# === QUALITY METRICS ===
quality_metrics:
  code_coverage: {code_coverage}
  cyclomatic_complexity: {cyclomatic_complexity}
  maintainability_index: {maintainability_index}
  technical_debt_ratio: {technical_debt_ratio}
'''

        return manifest

    def _generate_node_metadata(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        analysis_result: SimplePRDAnalysisResult
    ) -> str:
        """Generate OmniNode Tool Metadata for generated node"""
        return f'''# === OmniNode:Tool_Metadata ===
metadata_version: 0.1
name: {microservice_name}_{node_type.lower()}
namespace: omninode.generated.{domain}
version: 1.0.0
type: node
category: generated
description: |
  {analysis_result.parsed_prd.description}
tags: [generated, {node_type.lower()}, {domain}]
author: OmniClaude Code Generation
license: MIT
autoupdate: false
test_suite: true
test_status: pending
classification:
  maturity: generated
  trust_score: {int(analysis_result.confidence_score * 100)}
# === /OmniNode:Tool_Metadata ===
'''
