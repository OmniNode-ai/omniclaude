"""
Pydantic AI-based Contract-Driven Code Generator Agent

Generates ONEX-compliant code using LLM intelligence with structured outputs.
"""

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agent_model import AgentConfig, AgentResult, AgentTask
from mcp_client import ArchonMCPClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from trace_logger import TraceEventType, TraceLevel, get_trace_logger

# Add agents/lib to path for execution logger
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from agent_execution_mixin import AgentExecutionMixin

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass  # python-dotenv already installed via poetry


# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================


class ONEXNodeCode(BaseModel):
    """Structured output for ONEX node generation following canonical patterns."""

    node_name: str = Field(
        description="Full node class name (e.g., NodePostgreSQLAdapterEffect)"
    )
    node_type: str = Field(
        description="ONEX node type (Effect, Compute, Reducer, Orchestrator)"
    )
    contract_name: str = Field(
        description="Contract model class name (e.g., ModelContractPostgreSQLAdapterEffect)"
    )

    # Contract model - ONE unified contract, not separate Input/Output
    contract_model_code: str = Field(
        description="Complete contract model code inheriting from ModelContractBase"
    )

    # Subcontracts if needed
    subcontracts_code: list[str] = Field(
        default_factory=list, description="Additional subcontract models if needed"
    )

    # Node implementation
    node_class_code: str = Field(
        description="Complete node class implementation inheriting from NodeEffect/NodeCompute/etc"
    )

    # Dependencies and metadata
    imports: list[str] = Field(
        description="Required import statements from omnibase_core"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="External dependencies needed"
    )
    onex_compliance_notes: str = Field(
        description="Notes on ONEX architectural compliance"
    )


class CodeGenerationContext(BaseModel):
    """Context information for code generation."""

    task_description: str
    node_name: str
    node_type: str
    language: str = "python"
    intelligence_summary: str = ""
    pre_gathered_context: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Dependencies for Pydantic AI Agent
# ============================================================================


@dataclass
class AgentDeps:
    """Dependencies passed to agent tools."""

    task: AgentTask
    config: AgentConfig
    mcp_client: ArchonMCPClient
    trace_logger: Any
    trace_id: Optional[str]
    intelligence: Dict[str, Any]


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

# System prompt for ONEX-compliant code generation following canonical patterns
ONEX_SYSTEM_PROMPT = """You are an expert ONEX architecture code generator following canonical patterns from omniarchon examples.

**CANONICAL ONEX PATTERNS (from omniarchon documentation):**

1. **ONE Contract Model** (not separate Input/Output):
   - Class: ModelContract<Name><Type> (e.g., ModelContractPostgreSQLAdapterEffect)
   - Inherits: ModelContractBase from omnibase_core
   - Contains all I/O configs, transaction settings, retry policies
   - Example fields: io_operations, transaction_management, retry_policies, external_services

2. **Node Inherits from Base Class**:
   - Class: Node<Name><Type> (e.g., NodePostgreSQLAdapterEffect)
   - Inherits: NodeEffect (for Effect nodes) from omnibase_core.core.node_effect
   - Constructor: def __init__(self, container: ONEXContainer)
   - Main method: async def process(self, input_data: ModelEffectInput) -> ModelEffectOutput
   - Container injection for services

3. **Required Imports from omnibase_core**:
   ```python
   from omnibase_core.core.contracts.model_contract_effect import ModelContractEffect
   from omnibase_core.core.node_effect import NodeEffect
   from omnibase_core.core.onex_container import ONEXContainer
   from omnibase_core.core.errors.core_errors import CoreErrorCode, OnexError
   from omnibase_core.core.common_types import ModelScalarValue
   from omnibase_core.models.rsd.model_contract_base import ModelContractBase
   ```

4. **File Structure**:
   - Contract model at top
   - Subcontracts if needed (e.g., ModelIOOperationConfig, ModelTransactionConfig)
   - Node class inheriting from NodeEffect
   - No separate Input/Output models

5. **Node Implementation**:
   - Initialize with super().__init__(container)
   - Implement process() method with transaction management
   - Use circuit breaker, retry logic, security assessment
   - Strong typing with Pydantic - NO Any types

**Your Task:**
Generate production-quality ONEX code that:
1. Follows canonical patterns from omniarchon examples EXACTLY
2. ONE unified contract model (not separate Input/Output)
3. Node inherits from proper base class (NodeEffect, NodeCompute, etc.)
4. Uses omnibase_core imports
5. Includes complete implementation (not TODO placeholders)
6. Has proper error handling with OnexError
7. Uses container injection pattern
8. Includes transaction management, retry logic, circuit breaker

Generate code that matches the EXACT node name and follows canonical patterns."""

# Create the Pydantic AI agent
code_generator_agent = Agent[AgentDeps, ONEXNodeCode](
    "google-gla:gemini-2.5-flash",  # Latest Gemini Flash model
    deps_type=AgentDeps,
    output_type=ONEXNodeCode,
    system_prompt=ONEX_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@code_generator_agent.tool
async def get_intelligence_context(ctx: RunContext[AgentDeps]) -> str:
    """Get gathered intelligence and context for code generation.

    Returns: Summary of available patterns, examples, and context
    """
    deps = ctx.deps
    intelligence = deps.intelligence

    context_summary = []

    # Add domain patterns
    if "domain_patterns" in intelligence:
        context_summary.append("**Domain Patterns Available:**")
        context_summary.append(str(intelligence["domain_patterns"])[:1000])

    # Add pattern examples
    if "pattern_examples" in intelligence:
        context_summary.append("\n**Pattern Examples:**")
        context_summary.append(str(intelligence["pattern_examples"])[:1000])

    # Add implementation patterns
    if "implementation_patterns" in intelligence:
        context_summary.append("\n**Implementation Patterns:**")
        context_summary.append(str(intelligence["implementation_patterns"])[:1000])

    # Add context files
    if "context_files" in intelligence:
        context_summary.append(
            f"\n**Context Files:** {len(intelligence['context_files'])} available"
        )

    return (
        "\n".join(context_summary)
        if context_summary
        else "No intelligence context available"
    )


@code_generator_agent.tool
async def get_onex_standards(ctx: RunContext[AgentDeps]) -> str:
    """Get ONEX architectural standards and patterns.

    Returns: ONEX architecture guidelines
    """
    return """
**ONEX Node Types:**
- **Effect**: External I/O (database, API, file system) - Node<Name>Effect
- **Compute**: Pure computation/transformation - Node<Name>Compute
- **Reducer**: Aggregation, state reduction - Node<Name>Reducer
- **Orchestrator**: Workflow coordination - Node<Name>Orchestrator

**Standard Pattern:**
```python
from pydantic import BaseModel, Field

class <NodeName>Input(BaseModel):
    # Input fields with validation
    pass

class <NodeName>Output(BaseModel):
    # Output fields with validation
    pass

class Node<Name><Type>:
    async def execute(self, input_data: <NodeName>Input) -> <NodeName>Output:
        # Implementation
        pass
```

**Best Practices:**
- Always use async/await for I/O
- Validate all inputs/outputs
- Handle errors gracefully
- Use clear, descriptive names
- Include docstrings
"""


@code_generator_agent.tool
async def validate_node_name(ctx: RunContext[AgentDeps], node_name: str) -> str:
    """Validate that node name follows ONEX conventions.

    Args:
        node_name: The node class name to validate

    Returns: Validation result or correction suggestion
    """
    if not node_name.startswith("Node"):
        return f"❌ Node name must start with 'Node' (got: {node_name})"

    if not any(
        node_name.endswith(t) for t in ["Effect", "Compute", "Reducer", "Orchestrator"]
    ):
        return f"❌ Node name must end with Effect/Compute/Reducer/Orchestrator (got: {node_name})"

    return f"✅ Node name '{node_name}' follows ONEX conventions"


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


class CoderAgent(AgentExecutionMixin):
    """
    Pydantic AI-based contract-driven code generation agent.

    Generates ONEX-compliant code using LLM intelligence with structured outputs.
    """

    def __init__(self):
        # Initialize execution logging mixin
        super().__init__(agent_name="contract-driven-generator")

        self.config = AgentConfig.load("agent-contract-driven-generator")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute code generation using Pydantic AI agent with execution logging.

        Args:
            task: Task containing generation requirements

        Returns:
            AgentResult with generated code
        """
        # Execute with automatic execution logging
        return await self.execute_with_logging(
            task=task,
            execute_fn=self._execute_impl,
        )

    async def _execute_impl(self, task: AgentTask) -> AgentResult:
        """
        Internal implementation of code generation.

        Args:
            task: Task containing generation requirements

        Returns:
            AgentResult with generated code
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"using_pydantic_ai": True},
        )

        try:
            # Extract task inputs
            node_type = task.input_data.get("node_type", "Compute")
            node_name = task.input_data.get("node_name", "UnknownNode")
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Generating {node_type} node: {node_name}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Log progress: gathering intelligence
            await self.log_progress("gathering_intelligence", 20)

            # Gather intelligence
            intelligence = await self._gather_intelligence(task, pre_gathered_context)

            # Log progress: intelligence gathered
            await self.log_progress("intelligence_gathered", 40)

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                mcp_client=self.mcp_client,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
                intelligence=intelligence,
            )

            # Build generation prompt
            prompt = self._build_generation_prompt(task, node_name, node_type)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI code generator",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Log progress: generating code
            await self.log_progress("generating_code", 60)

            result = await code_generator_agent.run(prompt, deps=deps)
            generated_output: ONEXNodeCode = result.output

            # Log progress: code generated
            await self.log_progress("code_generated", 80)

            # Assemble final code
            final_code = self._assemble_code(generated_output)

            # Log progress: validating
            await self.log_progress("validating", 90)

            # Validate quality
            quality_metrics = await self._validate_quality(
                final_code, node_type, node_name
            )

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "generated_code": final_code,
                "node_type": node_type,
                "node_name": generated_output.node_name,
                "dependencies": generated_output.dependencies,
                "intelligence_gathered": intelligence,
                "quality_metrics": quality_metrics,
                "quality_score": quality_metrics.get("quality_score", 0.0),
                "lines_generated": len(final_code.split("\n")),
                "validation_passed": quality_metrics.get("quality_score", 0.0) >= 0.7,
                "onex_compliance_notes": generated_output.onex_compliance_notes,
                "pydantic_ai_metadata": {
                    "model_used": "gemini-1.5-flash",
                    "structured_output": True,
                    "tools_available": 3,
                },
            }

            # Create result
            agent_result = AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=True,
                output_data=output_data,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id,
            )

            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id,
                status="completed",
                result=agent_result.model_dump(),
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Code generation complete: {len(final_code)} chars, quality={quality_metrics.get('quality_score', 0):.2f}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Code generation failed: {str(e)}"

            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id, status="failed", error=error_msg
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=False,
                error=error_msg,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id,
            )

    async def _gather_intelligence(
        self, task: AgentTask, pre_gathered_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gather intelligence from context or MCP."""
        intelligence = {}

        if pre_gathered_context:
            # Use pre-gathered context
            for key, context_item in pre_gathered_context.items():
                context_type = context_item.get("type")
                if context_type == "rag" and "domain" in key:
                    intelligence["domain_patterns"] = context_item.get("content", {})
                elif context_type == "pattern":
                    intelligence["pattern_examples"] = context_item.get("content", {})
                elif context_type == "file":
                    intelligence.setdefault("context_files", []).append(
                        context_item.get("content", "")
                    )
        elif self.config.archon_mcp_enabled:
            # Gather fresh intelligence
            try:
                domain_intel = await self.mcp_client.perform_rag_query(
                    query=self.config.domain_query or "ONEX architecture patterns",
                    context="architecture",
                    match_count=3,
                )
                intelligence["domain_patterns"] = domain_intel
            except Exception as e:
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_ERROR,
                    message=f"Intelligence gathering failed (continuing): {str(e)}",
                    level=TraceLevel.WARNING,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                )

        return intelligence

    def _build_generation_prompt(
        self, task: AgentTask, node_name: str, node_type: str
    ) -> str:
        """Build detailed generation prompt for LLM."""
        return f"""Generate a complete ONEX {node_type} node with these specifications:

**Node Name:** {node_name}
**Node Type:** {node_type}
**Task Description:** {task.description}

**Requirements:**
- Use EXACT node name: {node_name}
- Follow ONEX architecture patterns
- Generate complete, production-ready code
- Include proper Pydantic models
- Use async/await appropriately
- Add comprehensive documentation
- Handle errors gracefully

**Additional Context:**
{task.input_data.get('additional_context', 'None provided')}

Use the available tools to:
1. Get intelligence context for implementation patterns
2. Get ONEX standards for compliance
3. Validate node name follows conventions

Generate complete, high-quality code that solves the specific problem described."""

    def _assemble_code(self, output: ONEXNodeCode) -> str:
        """Assemble final ONEX code following canonical patterns."""
        code_parts = []

        # Header with ONEX compliance notes
        code_parts.append(
            f'"""\n{output.node_name} - ONEX {output.node_type} Node\n\n{output.onex_compliance_notes}\n"""'
        )
        code_parts.append("")

        # Imports from omnibase_core
        code_parts.extend(output.imports)
        code_parts.append("")

        # Contract model (ONE unified model, not separate Input/Output)
        code_parts.append(
            "# ============================================================================"
        )
        code_parts.append("# Contract Model")
        code_parts.append(
            "# ============================================================================"
        )
        code_parts.append("")
        code_parts.append(output.contract_model_code)
        code_parts.append("")

        # Subcontracts if needed
        if output.subcontracts_code:
            code_parts.append(
                "# ============================================================================"
            )
            code_parts.append("# Subcontract Models")
            code_parts.append(
                "# ============================================================================"
            )
            code_parts.append("")
            for subcontract in output.subcontracts_code:
                code_parts.append(subcontract)
                code_parts.append("")

        # Node implementation inheriting from base class
        code_parts.append(
            "# ============================================================================"
        )
        code_parts.append("# Node Implementation")
        code_parts.append(
            "# ============================================================================"
        )
        code_parts.append("")
        code_parts.append(output.node_class_code)

        return "\n".join(code_parts)

    async def _validate_quality(
        self, code: str, node_type: str, node_name: str
    ) -> Dict[str, Any]:
        """Validate code quality via Archon MCP."""
        try:
            quality_result = await self.mcp_client.assess_code_quality(
                content=code, source_path=f"{node_name}.py", language="python"
            )
            return quality_result
        except Exception as e:
            return {"success": False, "quality_score": 0.0, "error": str(e)}

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, "close"):
            await self.mcp_client.close()
