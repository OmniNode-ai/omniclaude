"""
Code Generation Agent for Autonomous OmniNode Code Generation

Wraps the CodegenWorkflow to enable integration with the dispatch_runner
parallel execution framework. Supports both full PRD-based generation and
single node generation.

Integration: Phase 2.5 of dispatch_runner workflow (between Task Architecture and Context Filtering)
"""

import asyncio
import time
import sys
from typing import Any, Dict, Optional

# Import from parallel_execution package
from agents.parallel_execution.agent_model import AgentConfig, AgentTask, AgentResult
from agents.parallel_execution.agent_registry import register_agent
from agents.parallel_execution.trace_logger import get_trace_logger, TraceEventType, TraceLevel

# Import code generation components
try:
    from agents.lib.codegen_workflow import CodegenWorkflow, CodegenWorkflowResult
    from agents.lib.codegen_config import CodegenConfig

    CODEGEN_AVAILABLE = True
except ImportError as e:
    CODEGEN_AVAILABLE = False
    print(f"[CodeGenerator] Warning: Code generation unavailable: {e}", file=sys.stderr)


# ============================================================================
# Agent Implementation
# ============================================================================


@register_agent(
    agent_name="code-generator",
    agent_type="generator",
    capabilities=["prd_analysis", "node_generation", "contract_generation", "model_generation", "quality_validation"],
    description="Autonomous OmniNode code generation from PRD or specifications",
)
class CodeGeneratorAgent:
    """
    Autonomous code generation agent for OmniNode implementations.

    Supports two generation modes:
    1. Full PRD Analysis: Analyze PRD → Generate multiple nodes
    2. Single Node: Generate specific node type from business description

    Integration:
    - Phase 2.5 of dispatch_runner (between Task Architecture and Context Filtering)
    - Event-driven architecture with Kafka support
    - Database persistence for session and artifact tracking
    - Quality validation with configurable thresholds
    """

    def __init__(self):
        """Initialize code generation agent with configuration and dependencies."""
        # Config is optional - create default if not found
        try:
            self.config = AgentConfig.load("agent-code-generator")
        except (FileNotFoundError, Exception):
            # Create minimal default config
            self.config = AgentConfig(
                agent_name="agent-code-generator",
                agent_domain="code_generation",
                agent_purpose="Generate OmniNode implementations from PRD or specifications",
            )

        self.trace_logger = get_trace_logger()
        self._current_trace_id: Optional[str] = None

        # Initialize code generation workflow
        if CODEGEN_AVAILABLE:
            self.codegen_workflow = CodegenWorkflow()
            self.codegen_config = CodegenConfig()
        else:
            self.codegen_workflow = None
            self.codegen_config = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute code generation task.

        Supports two input modes:

        Mode 1: Full PRD Analysis
        input_data = {
            "prd_content": str,           # Required: PRD markdown content
            "output_directory": str,       # Required: Where to write files
            "workspace_context": dict,     # Optional: Additional context
            "generation_mode": "prd"       # Optional: Explicit mode
        }

        Mode 2: Single Node Generation
        input_data = {
            "node_type": str,              # Required: EFFECT/COMPUTE/REDUCER/ORCHESTRATOR
            "microservice_name": str,      # Required: Microservice name
            "domain": str,                 # Required: Domain name
            "business_description": str,   # Required: What the node does
            "output_directory": str,       # Required: Where to write files
            "generation_mode": "single"    # Optional: Explicit mode
        }

        Args:
            task: AgentTask with input_data containing generation parameters

        Returns:
            AgentResult with generation results, file paths, and quality metrics

        Raises:
            Returns AgentResult with success=False on error
        """
        start_time = time.time()

        # Check availability
        if not CODEGEN_AVAILABLE:
            return AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=False,
                error="Code generation components unavailable (missing dependencies)",
                execution_time_ms=0,
            )

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name, task_id=task.task_id, metadata={"using_codegen_workflow": True}
        )

        try:
            # Extract input parameters
            input_data = task.input_data or {}
            generation_mode = input_data.get("generation_mode", "auto")

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Code generation task assigned (mode: {generation_mode})",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Detect generation mode if auto
            if generation_mode == "auto":
                generation_mode = self._detect_generation_mode(input_data)

            # Execute generation based on mode
            if generation_mode == "prd":
                result = await self._generate_from_prd(task, input_data)
            elif generation_mode == "single":
                result = await self._generate_single_node(task, input_data)
            else:
                raise ValueError(f"Unknown generation mode: {generation_mode}")

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            await self.trace_logger.end_agent_trace(trace_id=self._current_trace_id, status="completed", result=result)

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Code generation complete: {result.get('summary', 'N/A')}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=True,
                output_data=result,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Code generation failed: {str(e)}"

            await self.trace_logger.end_agent_trace(trace_id=self._current_trace_id, status="failed", error=error_msg)

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

    def _detect_generation_mode(self, input_data: Dict[str, Any]) -> str:
        """
        Detect generation mode from input data.

        PRD mode: Has 'prd_content' field
        Single mode: Has 'node_type', 'microservice_name', 'domain', 'business_description'

        Args:
            input_data: Task input data

        Returns:
            "prd" or "single"

        Raises:
            ValueError: If mode cannot be determined
        """
        has_prd = "prd_content" in input_data
        has_node_spec = all(
            key in input_data for key in ["node_type", "microservice_name", "domain", "business_description"]
        )

        if has_prd:
            return "prd"
        elif has_node_spec:
            return "single"
        else:
            raise ValueError(
                "Cannot detect generation mode. "
                "Provide either 'prd_content' (PRD mode) or "
                "'node_type'/'microservice_name'/'domain'/'business_description' (single mode)"
            )

    async def _generate_from_prd(self, task: AgentTask, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate code from full PRD analysis.

        Args:
            task: Agent task
            input_data: Input parameters with prd_content

        Returns:
            Dictionary with generation results
        """
        await self.trace_logger.log_event(
            event_type=TraceEventType.AGENT_START,
            message="Starting PRD-based code generation",
            level=TraceLevel.INFO,
            agent_name=self.config.agent_name,
            task_id=task.task_id,
        )

        # Extract parameters
        prd_content = input_data["prd_content"]
        output_directory = input_data["output_directory"]
        workspace_context = input_data.get("workspace_context")

        # Execute workflow
        workflow_result: CodegenWorkflowResult = await self.codegen_workflow.generate_from_prd(
            prd_content=prd_content, output_directory=output_directory, workspace_context=workspace_context
        )

        if not workflow_result.success:
            raise Exception(workflow_result.error_message or "Unknown workflow error")

        # Build output data
        output_data = {
            "generation_mode": "prd",
            "session_id": str(workflow_result.session_id),
            "correlation_id": str(workflow_result.correlation_id),
            "summary": f"Generated {len(workflow_result.generated_nodes)} nodes, {workflow_result.total_files} files",
            "generated_nodes": workflow_result.generated_nodes,
            "total_files": workflow_result.total_files,
            "output_directory": output_directory,
            "prd_analysis": {
                "title": workflow_result.prd_analysis.parsed_prd.title,
                "description": workflow_result.prd_analysis.parsed_prd.description,
                "node_type_hints": workflow_result.prd_analysis.node_type_hints,
                "recommended_mixins": workflow_result.prd_analysis.recommended_mixins,
                "confidence_score": workflow_result.prd_analysis.confidence_score,
                "quality_baseline": workflow_result.prd_analysis.quality_baseline,
            },
            "statistics": {
                "nodes_generated": len(workflow_result.generated_nodes),
                "total_files": workflow_result.total_files,
                "node_types": list(set(node.get("node_type") for node in workflow_result.generated_nodes)),
            },
        }

        return output_data

    async def _generate_single_node(self, task: AgentTask, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate single node from specifications.

        Args:
            task: Agent task
            input_data: Input parameters with node specifications

        Returns:
            Dictionary with generation results
        """
        await self.trace_logger.log_event(
            event_type=TraceEventType.AGENT_START,
            message="Starting single node generation",
            level=TraceLevel.INFO,
            agent_name=self.config.agent_name,
            task_id=task.task_id,
        )

        # Extract parameters
        node_type = input_data["node_type"]
        microservice_name = input_data["microservice_name"]
        domain = input_data["domain"]
        business_description = input_data["business_description"]
        output_directory = input_data["output_directory"]

        # Execute single node generation
        node_result = await self.codegen_workflow.generate_single_node(
            node_type=node_type,
            microservice_name=microservice_name,
            domain=domain,
            business_description=business_description,
            output_directory=output_directory,
        )

        # Build output data
        output_data = {
            "generation_mode": "single",
            "summary": f"Generated {node_type} node: {microservice_name}",
            "node_type": node_type,
            "microservice_name": microservice_name,
            "domain": domain,
            "generated_files": node_result.get("generated_files", []),
            "output_directory": output_directory,
            "statistics": {
                "nodes_generated": 1,
                "total_files": len(node_result.get("generated_files", [])) + 1,
                "node_types": [node_type],
            },
        }

        return output_data

    async def cleanup(self):
        """Cleanup resources."""
        # CodegenWorkflow handles its own cleanup
        pass


# ============================================================================
# Parallel Code Generator (for testing and parallel execution)
# ============================================================================


class ParallelCodeGenerator:
    """
    Wrapper for parallel code generation.

    This class provides a simple interface for parallel code generation
    used by integration tests and parallel execution frameworks.
    """

    def __init__(self, max_workers: int = 4):
        """
        Initialize parallel code generator.

        Args:
            max_workers: Maximum number of parallel workers
        """
        self.max_workers = max_workers
        self.agent = CodeGeneratorAgent()

    async def generate_parallel(self, tasks: list[AgentTask]) -> list[AgentResult]:
        """
        Generate code for multiple tasks in parallel.

        Args:
            tasks: List of agent tasks to execute

        Returns:
            List of agent results
        """
        # Simple sequential execution for now
        # TODO: Implement true parallel execution with asyncio.gather
        results = []
        for task in tasks:
            result = await self.agent.execute(task)
            results.append(result)
        return results

    async def cleanup(self):
        """Cleanup resources."""
        await self.agent.cleanup()


# ============================================================================
# Example Usage
# ============================================================================


async def main():
    """Example usage of code generator agent."""
    agent = CodeGeneratorAgent()

    # Example 1: PRD-based generation
    print("\n" + "=" * 80)
    print("Example 1: PRD-Based Generation")
    print("=" * 80)

    prd_task = AgentTask(
        task_id="codegen-prd-001",
        description="Generate OmniNode implementation from PRD",
        agent_name="agent-code-generator",
        input_data={
            "prd_content": """
# User Authentication Microservice

## Overview
Implement a user authentication service using OmniNode architecture.

## Functional Requirements
- User registration with email validation
- Secure password hashing and storage
- JWT token generation for authenticated sessions
- Token validation and refresh

## Technical Details
- PostgreSQL database for user storage
- Redis cache for session tokens
- Email service integration for verification
            """,
            "output_directory": "/tmp/generated_auth_service",
            "workspace_context": {"project_type": "microservice", "language": "python"},
        },
    )

    result = await agent.execute(prd_task)
    print("\nPRD Generation Result:")
    print(f"Success: {result.success}")
    if result.success:
        output = result.output_data
        print(f"Session ID: {output['session_id']}")
        print(f"Summary: {output['summary']}")
        print(f"Nodes Generated: {output['statistics']['nodes_generated']}")
        print(f"Total Files: {output['statistics']['total_files']}")
    else:
        print(f"Error: {result.error}")

    # Example 2: Single node generation
    print("\n" + "=" * 80)
    print("Example 2: Single Node Generation")
    print("=" * 80)

    single_task = AgentTask(
        task_id="codegen-single-001",
        description="Generate single Effect node",
        agent_name="agent-code-generator",
        input_data={
            "node_type": "EFFECT",
            "microservice_name": "payment",
            "domain": "transactions",
            "business_description": "Process payment transactions via Stripe API",
            "output_directory": "/tmp/generated_payment_node",
        },
    )

    result = await agent.execute(single_task)
    print("\nSingle Node Generation Result:")
    print(f"Success: {result.success}")
    if result.success:
        output = result.output_data
        print(f"Summary: {output['summary']}")
        print(f"Node Type: {output['node_type']}")
        print(f"Total Files: {output['statistics']['total_files']}")
    else:
        print(f"Error: {result.error}")

    await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
