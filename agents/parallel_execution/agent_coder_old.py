"""
Contract-Driven Code Generator Agent

Generates ONEX-compliant code from contracts with quality validation.
Based on agent-contract-driven-generator.yaml configuration.
"""

import time
from typing import Dict, Any

from agent_model import AgentConfig, AgentTask, AgentResult
from mcp_client import ArchonMCPClient
from trace_logger import get_trace_logger, TraceEventType, TraceLevel


class CoderAgent:
    """
    Contract-driven code generation specialist using ONEX generation pipeline.

    Features:
    - Contract-driven code generation
    - Quality-assured generation with intelligence checks
    - Post-generation validation
    - Template learning
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-contract-driven-generator")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: str | None = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute contract-driven code generation task.

        Args:
            task: Task containing contract and generation requirements

        Returns:
            AgentResult with generated code and quality metrics
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"domain": self.config.agent_domain, "input_data": task.input_data},
        )

        try:
            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Starting contract-driven code generation: {task.description}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Extract task inputs
            contract = task.input_data.get("contract", {})
            node_type = task.input_data.get("node_type", "Compute")
            language = task.input_data.get("language", "python")

            # Check for pre-gathered context (from context filtering system)
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            # Phase 1: Intelligence gathering (use pre-gathered or gather fresh)
            intelligence = {}

            if pre_gathered_context:
                # Use pre-filtered context provided by dispatcher
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message=f"Phase 1: Using pre-gathered context ({len(pre_gathered_context)} items)",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                    metadata={"context_items": len(pre_gathered_context)},
                )

                # Extract intelligence from pre-gathered context
                for key, context_item in pre_gathered_context.items():
                    context_type = context_item.get("type")
                    if context_type == "rag" and "domain" in key:
                        intelligence["domain_patterns"] = context_item.get("content", {})
                    elif context_type == "pattern":
                        intelligence["pattern_examples"] = context_item.get("content", {})
                    elif context_type == "file":
                        intelligence.setdefault("context_files", []).append(context_item.get("content", ""))

                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message=f"Extracted {len(intelligence)} intelligence sources from pre-gathered context",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                )

            elif self.config.archon_mcp_enabled:
                # Fallback: Gather intelligence independently (legacy mode)
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message="Phase 1: Gathering intelligence (no pre-gathered context available)",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                )

                try:
                    # Gather domain-specific intelligence
                    domain_intel = await self.mcp_client.perform_rag_query(
                        query=self.config.domain_query or "contract-driven development patterns",
                        context="api_development",
                        match_count=self.config.match_count,
                    )
                    intelligence["domain_patterns"] = domain_intel

                    # Gather implementation intelligence
                    impl_intel = await self.mcp_client.perform_rag_query(
                        query=self.config.implementation_query or "API contract validation",
                        context="api_development",
                        match_count=self.config.match_count,
                    )
                    intelligence["implementation_patterns"] = impl_intel

                    await self.trace_logger.log_event(
                        event_type=TraceEventType.AGENT_START,
                        message=f"Gathered intelligence: {len(intelligence)} sources",
                        level=TraceLevel.INFO,
                        agent_name=self.config.agent_name,
                        task_id=task.task_id,
                        metadata={"intelligence_count": len(intelligence)},
                    )

                except Exception as e:
                    await self.trace_logger.log_event(
                        event_type=TraceEventType.AGENT_ERROR,
                        message=f"Intelligence gathering failed (continuing): {str(e)}",
                        level=TraceLevel.WARNING,
                        agent_name=self.config.agent_name,
                        task_id=task.task_id,
                    )

            # Phase 2: Generate code from contract
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Phase 2: Generating ONEX-compliant code",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            generated_code = self._generate_code_from_contract(
                contract=contract, node_type=node_type, intelligence=intelligence
            )

            # Phase 3: Quality validation
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Phase 3: Validating generated code quality",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            quality_metrics = {}
            if self.config.archon_mcp_enabled:
                try:
                    # Assess code quality
                    quality_result = await self.mcp_client.assess_code_quality(
                        content=generated_code, source_path=f"generated_{node_type.lower()}.py", language=language
                    )
                    quality_metrics = quality_result

                    await self.trace_logger.log_event(
                        event_type=TraceEventType.AGENT_START,
                        message=f"Quality validation complete: score={quality_metrics.get('quality_score', 0):.2f}",
                        level=TraceLevel.INFO,
                        agent_name=self.config.agent_name,
                        task_id=task.task_id,
                        metadata=quality_metrics,
                    )

                except Exception as e:
                    await self.trace_logger.log_event(
                        event_type=TraceEventType.AGENT_ERROR,
                        message=f"Quality validation failed (continuing): {str(e)}",
                        level=TraceLevel.WARNING,
                        agent_name=self.config.agent_name,
                        task_id=task.task_id,
                    )

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "generated_code": generated_code,
                "node_type": node_type,
                "contract": contract,
                "intelligence_gathered": intelligence,
                "quality_metrics": quality_metrics,
                "quality_score": quality_metrics.get("quality_score", 0.0),
                "lines_generated": len(generated_code.split("\n")),
                "validation_passed": quality_metrics.get("quality_score", 0.0) >= 0.7,
            }

            # Create result
            result = AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=True,
                output_data=output_data,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id,
            )

            # End trace successfully
            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id, status="completed", result=result.model_dump()
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Code generation complete: {len(generated_code)} chars, quality={quality_metrics.get('quality_score', 0):.2f}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
                metadata={"execution_time_ms": execution_time_ms},
            )

            return result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Code generation failed: {str(e)}"

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
                metadata={"error": str(e)},
            )

            await self.trace_logger.end_agent_trace(trace_id=self._current_trace_id, status="failed", error=error_msg)

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=False,
                error=error_msg,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id,
            )

    def _generate_code_from_contract(
        self, contract: Dict[str, Any], node_type: str, intelligence: Dict[str, Any]
    ) -> str:
        """
        Generate ONEX-compliant code from contract specification.

        Args:
            contract: Contract specification
            node_type: ONEX node type (Effect, Compute, Reducer, Orchestrator)
            intelligence: Gathered intelligence for generation

        Returns:
            Generated Python code
        """
        # Extract contract details
        contract_name = contract.get("name", "UnknownContract")
        input_model = contract.get("input_model", {})
        output_model = contract.get("output_model", {})
        description = contract.get("description", "")

        # Generate ONEX node code
        code_parts = []

        # Header
        code_parts.append('"""')
        code_parts.append(f"{contract_name} - ONEX {node_type} Node")
        code_parts.append("")
        code_parts.append(description)
        code_parts.append('"""')
        code_parts.append("")
        code_parts.append("from typing import Any, Dict")
        code_parts.append("from pydantic import BaseModel, Field")
        code_parts.append("")

        # Input model
        code_parts.append("")
        code_parts.append(f"class {contract_name}Input(BaseModel):")
        code_parts.append(f'    """Input model for {contract_name}."""')
        if input_model:
            for field_name, field_spec in input_model.items():
                field_type = field_spec.get("type", "Any")
                field_desc = field_spec.get("description", "")
                code_parts.append(f'    {field_name}: {field_type} = Field(description="{field_desc}")')
        else:
            code_parts.append("    pass")

        # Output model
        code_parts.append("")
        code_parts.append("")
        code_parts.append(f"class {contract_name}Output(BaseModel):")
        code_parts.append(f'    """Output model for {contract_name}."""')
        if output_model:
            for field_name, field_spec in output_model.items():
                field_type = field_spec.get("type", "Any")
                field_desc = field_spec.get("description", "")
                code_parts.append(f'    {field_name}: {field_type} = Field(description="{field_desc}")')
        else:
            code_parts.append("    pass")

        # Node implementation
        code_parts.append("")
        code_parts.append("")
        code_parts.append(f"class Node{contract_name}{node_type}:")
        code_parts.append('    """')
        code_parts.append(f"    ONEX {node_type} node for {contract_name}.")
        code_parts.append("    ")
        code_parts.append(f"    {description}")
        code_parts.append('    """')
        code_parts.append("")
        code_parts.append(f"    async def execute(self, input_data: {contract_name}Input) -> {contract_name}Output:")
        code_parts.append('        """')
        code_parts.append(f"        Execute {node_type.lower()} operation.")
        code_parts.append("        ")
        code_parts.append("        Args:")
        code_parts.append("            input_data: Validated input model")
        code_parts.append("        ")
        code_parts.append("        Returns:")
        code_parts.append("            Validated output model")
        code_parts.append('        """')
        code_parts.append(f"        # TODO: Implement {node_type.lower()} logic")
        code_parts.append(f"        # Intelligence gathered: {len(intelligence)} sources")
        code_parts.append("        ")
        code_parts.append("        # Placeholder implementation")
        code_parts.append(f"        return {contract_name}Output()")

        return "\n".join(code_parts)

    async def cleanup(self):
        """Cleanup MCP client."""
        await self.mcp_client.close()
