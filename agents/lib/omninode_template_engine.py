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
from datetime import datetime

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
        if not mixins:
            return ""
        
        init_code = []
        for mixin in mixins:
            if mixin == "MixinEventBus":
                init_code.append("        self._event_bus = EventBus()")
            elif mixin == "MixinCaching":
                init_code.append("        self._cache = Cache()")
            elif mixin == "MixinHealthCheck":
                init_code.append("        self._health_checker = HealthChecker()")
            # Add more mixin initializations as needed
        
        return "\n".join(init_code)
    
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
        """Generate additional files (models, contracts, etc.)"""
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
        
        # Generate enum
        files["v1_0_0/enums/enum_{}_operation_type.py".format(microservice_name)] = self._generate_operation_enum(
            microservice_name, analysis_result
        )
        
        # Generate contract
        files["v1_0_0/contracts/{}_{}_contract.yaml".format(microservice_name, node_type.lower())] = self._generate_contract(
            microservice_name, node_type, analysis_result
        )
        
        # Generate __init__.py files
        files["v1_0_0/__init__.py"] = self._generate_version_init()
        files["v1_0_0/models/__init__.py"] = self._generate_models_init(microservice_name)
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
    
    def _generate_models_init(self, microservice_name: str) -> str:
        """Generate models __init__.py"""
        return f'''#!/usr/bin/env python3
"""
Models for {microservice_name}
"""

from .model_{microservice_name}_input import *
from .model_{microservice_name}_output import *
from .model_{microservice_name}_config import *
'''
    
    def _generate_enums_init(self, microservice_name: str) -> str:
        """Generate enums __init__.py"""
        return f'''#!/usr/bin/env python3
"""
Enums for {microservice_name}
"""

from .enum_{microservice_name}_operation_type import *
'''
    
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
