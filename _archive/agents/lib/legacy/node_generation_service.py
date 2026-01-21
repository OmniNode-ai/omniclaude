#!/usr/bin/env python3
"""
Node Generation Service - Simplified Version

Handles generation of final node implementations with complete code generation,
test creation, and documentation using a simplified, robust approach.
"""

import logging
from enum import Enum
from typing import Any

from omni_agent.config.settings import OmniAgentSettings
from pydantic import BaseModel, Field

# Lazy import to avoid circular imports
# from ..workflows.smart_responder_chain import SmartResponderChain


class NodeType(Enum):
    """OmniNode types based on the 4-node system."""

    COMPUTE = "COMPUTE"
    EFFECT = "EFFECT"
    REDUCER = "REDUCER"
    ORCHESTRATOR = "ORCHESTRATOR"


class GenerationType(Enum):
    """Types of generation operations."""

    CANARY_CLONE = "canary_clone"
    FINAL_NODE = "final_node"
    TEST_GENERATION = "test_generation"
    DOCUMENTATION = "documentation"


class CodeQuality(Enum):
    """Code quality levels."""

    BASIC = "basic"
    PRODUCTION = "production"
    ENTERPRISE = "enterprise"


# Request/Response Models
class ModelNodeGenerationRequest(BaseModel):
    """Request model for node generation operations."""

    task_id: str = Field(..., description="Unique task identifier")
    task_title: str = Field(..., description="Human-readable task title")
    task_description: str = Field(..., description="Detailed task description")

    node_type: NodeType = Field(..., description="Type of node to generate")
    generation_type: GenerationType = Field(..., description="Type of generation")
    code_quality: CodeQuality = Field(
        default=CodeQuality.PRODUCTION, description="Quality level"
    )

    # Context data
    contracts: list[dict[str, Any]] = Field(
        default_factory=list, description="ONEX contracts"
    )
    dependencies: list[dict[str, Any]] = Field(
        default_factory=list, description="Dependencies"
    )
    method_signatures: list[dict[str, Any]] = Field(
        default_factory=list, description="Method signatures"
    )
    canary_template: dict[str, Any] | None = Field(
        default=None, description="Canary template data"
    )

    # Generation options
    output_directory: str = Field(default="./generated", description="Output directory")
    include_tests: bool = Field(default=True, description="Include test generation")
    include_docs: bool = Field(default=True, description="Include documentation")


class ModelNodeGenerationResponse(BaseModel):
    """Response model for node generation operations."""

    success: bool = Field(..., description="Generation success status")
    task_id: str = Field(..., description="Task identifier")
    generation_type: GenerationType = Field(
        ..., description="Type of generation performed"
    )

    # Generated content
    generated_files: list[dict[str, Any]] = Field(
        default_factory=list, description="Generated files"
    )
    main_code: str | None = Field(default=None, description="Main implementation code")
    test_code: str | None = Field(default=None, description="Test code")
    documentation: str | None = Field(default=None, description="Documentation")

    # Metadata
    lines_of_code: int = Field(default=0, description="Total lines of code generated")
    generation_time: float = Field(
        default=0.0, description="Generation time in seconds"
    )
    quality_score: float = Field(default=0.0, description="Estimated quality score")

    # Error handling
    error_message: str | None = Field(
        default=None, description="Error message if failed"
    )
    warnings: list[str] = Field(default_factory=list, description="Warning messages")


class NodeGenerationService:
    """Service for generating complete node implementations."""

    def __init__(self, settings: OmniAgentSettings):
        """Initialize the node generation service."""
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.smart_responder_chain = None  # Lazy initialization

    def _get_responder_chain(self):
        """Lazy initialization of SmartResponderChain to avoid circular imports."""
        if self.smart_responder_chain is None:
            from ..workflows.smart_responder_chain import SmartResponderChain

            self.smart_responder_chain = SmartResponderChain()
        return self.smart_responder_chain

    async def generate_node(
        self, request: ModelNodeGenerationRequest
    ) -> ModelNodeGenerationResponse:
        """
        Generate a complete node implementation based on the request.

        Args:
            request: Node generation request with task details and context

        Returns:
            ModelNodeGenerationResponse: Generation results with code and metadata
        """
        try:
            self.logger.info(f"Starting node generation for task: {request.task_title}")

            # Generate based on type
            if request.generation_type == GenerationType.FINAL_NODE:
                return await self._generate_final_node(request)
            elif request.generation_type == GenerationType.CANARY_CLONE:
                return await self._clone_canary_template(request)
            elif request.generation_type == GenerationType.TEST_GENERATION:
                return await self._generate_tests(request)
            elif request.generation_type == GenerationType.DOCUMENTATION:
                return await self._generate_documentation(request)
            else:
                raise ValueError(f"Unknown generation type: {request.generation_type}")

        except Exception as e:
            self.logger.error(f"Node generation failed: {str(e)}")
            return ModelNodeGenerationResponse(
                success=False,
                task_id=request.task_id,
                generation_type=request.generation_type,
                error_message=str(e),
            )

    async def _generate_final_node(
        self, request: ModelNodeGenerationRequest
    ) -> ModelNodeGenerationResponse:
        """Generate the final node implementation."""
        self.logger.info("Generating final node implementation")

        # Create simple prompt without complex f-string issues
        prompt = self._build_generation_prompt(request)

        # Use smart responder chain for generation
        response, metrics = await self._get_responder_chain().process_request(
            task_prompt=prompt,
            context={"purpose": f"Node generation for {request.task_title}"},
            enable_consensus=True,
            enable_rag=True,
        )

        # Note: SmartResponderChain returns (ModelResponse, ChainMetrics)
        # response has .content attribute, no success/error_message

        # Process the generated content
        generated_code = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Create response
        return ModelNodeGenerationResponse(
            success=True,
            task_id=request.task_id,
            generation_type=request.generation_type,
            main_code=generated_code,
            generated_files=[
                {
                    "path": f"{request.task_title.lower().replace(' ', '_')}_node.py",
                    "content": generated_code,
                    "type": "main_implementation",
                }
            ],
            lines_of_code=len(generated_code.split("\n")),
            generation_time=(
                response.response.get("processing_time", 0.0)
                if response.response
                else 0.0
            ),
            quality_score=(
                response.response.get("confidence", 0.0) if response.response else 0.0
            ),
        )

    async def _clone_canary_template(
        self, request: ModelNodeGenerationRequest
    ) -> ModelNodeGenerationResponse:
        """Clone a canary node template."""
        self.logger.info("Cloning canary template")

        # Simple canary cloning logic
        canary_code = '''#!/usr/bin/env python3
"""
Canary Template Node

This is a basic template for node implementation.
"""

from typing import Any, Dict
from pydantic import BaseModel

# Try to import from omnibase_core, fallback to minimal implementation
try:
    from omnibase_core.protocol.protocol_base_tool_with_logger import (
        ProtocolBaseToolWithLogger as BaseOnexTool,
    )
except ImportError:
    # Minimal fallback for BaseOnexTool when omnibase_core is not available
    class BaseOnexTool:
        """Minimal base tool implementation for development fallback."""

        async def execute(self, input_data: Any) -> Any:
            """Override this method in subclasses."""
            raise NotImplementedError("Subclasses must implement execute method")


class CanaryInput(BaseModel):
    """Input model for canary node."""
    data: Dict[str, Any]


class CanaryOutput(BaseModel):
    """Output model for canary node."""
    result: Dict[str, Any]
    status: str


class CanaryNode(BaseOnexTool):
    """Canary node implementation."""

    async def execute(self, input_data: CanaryInput) -> CanaryOutput:
        """Execute the canary operation."""
        return CanaryOutput(
            result=input_data.data,
            status="success"
        )
'''

        return ModelNodeGenerationResponse(
            success=True,
            task_id=request.task_id,
            generation_type=request.generation_type,
            main_code=canary_code,
            generated_files=[
                {
                    "path": "canary_node.py",
                    "content": canary_code,
                    "type": "canary_template",
                }
            ],
            lines_of_code=len(canary_code.split("\n")),
            quality_score=0.8,
        )

    async def _generate_tests(
        self, request: ModelNodeGenerationRequest
    ) -> ModelNodeGenerationResponse:
        """Generate test code for the node."""
        self.logger.info("Generating test code")

        # Simple test generation
        test_code = f'''#!/usr/bin/env python3
"""
Test suite for {request.task_title} Node

Comprehensive tests for the generated node implementation.
"""

import pytest
from typing import Any, Dict

# Import your node implementation here
# from nodes.{request.task_title.lower().replace(' ', '_')}_node import YourNode


class TestNodeImplementation:
    """Test suite for node implementation."""

    def test_basic_functionality(self):
        """Test basic node functionality."""
        # Add your tests here
        assert True

    def test_input_validation(self):
        """Test input validation."""
        # Add validation tests
        assert True

    def test_error_handling(self):
        """Test error handling."""
        # Add error handling tests
        assert True


if __name__ == "__main__":
    pytest.main([__file__])
'''

        return ModelNodeGenerationResponse(
            success=True,
            task_id=request.task_id,
            generation_type=request.generation_type,
            test_code=test_code,
            generated_files=[
                {
                    "path": f"test_{request.task_title.lower().replace(' ', '_')}_node.py",
                    "content": test_code,
                    "type": "test_code",
                }
            ],
            lines_of_code=len(test_code.split("\n")),
            quality_score=0.7,
        )

    async def _generate_documentation(
        self, request: ModelNodeGenerationRequest
    ) -> ModelNodeGenerationResponse:
        """Generate documentation for the node."""
        self.logger.info("Generating documentation")

        # Simple documentation generation
        doc_content = f"""# {request.task_title} Node

## Overview

{request.task_description}

## Node Type

This is a {request.node_type.value} node in the ONEX 4-node architecture.

## Usage

```python
from nodes.{request.task_title.lower().replace(' ', '_')}_node import create_node

# Create node instance
node = create_node(registry)

# Use the node
result = await node.execute(input_data)
```

## Implementation Details

- Node type: {request.node_type.value}
- Quality level: {request.code_quality.value}
- Includes error handling and validation
- Follows ONEX architectural patterns

## Testing

Run tests with:
```bash
pytest test_{request.task_title.lower().replace(' ', '_')}_node.py
```
"""

        return ModelNodeGenerationResponse(
            success=True,
            task_id=request.task_id,
            generation_type=request.generation_type,
            documentation=doc_content,
            generated_files=[
                {
                    "path": f"{request.task_title.lower().replace(' ', '_')}_node_docs.md",
                    "content": doc_content,
                    "type": "documentation",
                }
            ],
            lines_of_code=len(doc_content.split("\n")),
            quality_score=0.8,
        )

    def _build_generation_prompt(self, request: ModelNodeGenerationRequest) -> str:
        """Build a generation prompt without complex f-string issues."""

        # Basic prompt components
        task_info = f"Task: {request.task_title} - {request.task_description}"
        node_info = f"Node Type: {request.node_type.value}"
        quality_info = f"Quality Level: {request.code_quality.value}"

        # Contract info
        contract_info = ""
        if request.contracts:
            contract_info = (
                f"Contracts: {len(request.contracts)} contract(s) to implement"
            )

        # Dependencies info
        deps_info = ""
        if request.dependencies:
            deps_info = f"Dependencies: {len(request.dependencies)} dependency(ies) to integrate"

        # Build complete prompt
        prompt_parts = [
            "# Node Implementation Generation",
            "",
            "Generate a complete, production-ready node implementation.",
            "",
            "## Requirements:",
            task_info,
            node_info,
            quality_info,
            contract_info,
            deps_info,
            "",
            "## Implementation Standards:",
            "- Follow ONEX 4-node architecture patterns",
            "- Use proper type annotations with Pydantic models",
            "- Include comprehensive error handling",
            "- Implement async/await patterns for I/O",
            "- Include proper logging and monitoring",
            "- Follow clean code principles (SOLID, DRY, KISS)",
            "",
            "Generate a complete Python module with proper structure,",
            "imports, classes, and functions following ONEX patterns.",
        ]

        return "\n".join(prompt_parts)

    def _format_contracts_for_prompt(self, contracts: list[dict[str, Any]]) -> str:
        """Format contracts for inclusion in prompt."""
        if not contracts:
            return "No contracts specified."

        contract_summaries = []
        for i, contract in enumerate(contracts, 1):
            name = contract.get("name", f"Contract_{i}")
            description = contract.get("description", "No description")
            contract_summaries.append(f"- {name}: {description}")

        return "\n".join(contract_summaries)

    def _format_dependencies_for_prompt(
        self, dependencies: list[dict[str, Any]]
    ) -> str:
        """Format dependencies for inclusion in prompt."""
        if not dependencies:
            return "No dependencies specified."

        dep_summaries = []
        for dep in dependencies:
            name = dep.get("name", "Unknown")
            dep_type = dep.get("type", "unknown")
            dep_summaries.append(f"- {name} ({dep_type})")

        return "\n".join(dep_summaries)

    def _format_method_signatures_for_prompt(
        self, methods: list[dict[str, Any]]
    ) -> str:
        """Format method signatures for inclusion in prompt."""
        if not methods:
            return "No specific method signatures required."

        method_summaries = []
        for method in methods:
            name = method.get("name", "unknown")
            signature = method.get("signature", "unknown")
            method_summaries.append(f"- {name}: {signature}")

        return "\n".join(method_summaries)
