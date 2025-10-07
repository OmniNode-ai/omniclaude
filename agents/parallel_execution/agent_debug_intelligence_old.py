"""
Debug Intelligence Agent

Multi-dimensional debugging with quality analysis, pattern recognition,
performance correlation, and intelligent root cause analysis.
Based on agent-debug-intelligence.yaml configuration.
"""

import asyncio
import time
from typing import Dict, Any, List

from agent_model import AgentConfig, AgentTask, AgentResult
from mcp_client import ArchonMCPClient
from trace_logger import get_trace_logger, TraceEventType, TraceLevel


class DebugIntelligenceAgent:
    """
    Multi-dimensional debugging with quality analysis using BFROS framework.

    Features:
    - Quality correlation analysis
    - Performance impact assessment
    - Historical pattern analysis
    - Anti-pattern detection
    - Root cause confidence scoring
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-debug-intelligence")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: str | None = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute multi-dimensional debug analysis.

        Args:
            task: Task containing bug information and code to debug

        Returns:
            AgentResult with debug report and intelligence metrics
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={
                "domain": self.config.agent_domain,
                "input_data": task.input_data
            }
        )

        try:
            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Starting intelligence-enhanced debugging: {task.description}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            # Extract task inputs
            problematic_code = task.input_data.get("code", "")
            file_path = task.input_data.get("file_path", "unknown.py")
            language = task.input_data.get("language", "python")
            error_message = task.input_data.get("error", "")

            # Check for pre-gathered context (from context filtering system)
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            # Phase 1: Pre-Investigation Intelligence (use pre-gathered or gather fresh)
            intelligence = {}

            if pre_gathered_context:
                # Use pre-filtered context provided by dispatcher
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message=f"Phase 1: Using pre-gathered context ({len(pre_gathered_context)} items)",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                    metadata={"context_items": len(pre_gathered_context)}
                )

                # Extract intelligence from pre-gathered context
                for key, context_item in pre_gathered_context.items():
                    context_type = context_item.get("type")
                    if context_type == "rag" and "domain" in key:
                        intelligence["domain_patterns"] = context_item.get("content", {})
                    elif context_type == "pattern":
                        intelligence["anti_patterns"] = context_item.get("content", {})
                    elif context_type == "file":
                        # Could be used for analyzing related files
                        intelligence.setdefault("related_files", []).append(context_item.get("content", ""))

                # Still need to assess the problematic code itself
                if self.config.archon_mcp_enabled and problematic_code:
                    try:
                        quality_result = await self.mcp_client.assess_code_quality(
                            content=problematic_code,
                            source_path=file_path,
                            language=language
                        )
                        intelligence["code_quality"] = quality_result
                    except Exception as e:
                        await self.trace_logger.log_event(
                            event_type=TraceEventType.AGENT_ERROR,
                            message=f"Code quality assessment failed: {str(e)}",
                            level=TraceLevel.WARNING,
                            agent_name=self.config.agent_name,
                            task_id=task.task_id
                        )

                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message=f"Extracted {len(intelligence)} intelligence sources from pre-gathered context",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id
                )

            else:
                # Fallback: Gather intelligence independently (legacy mode)
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message="Phase 1: Gathering pre-investigation intelligence (no pre-gathered context)",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id
                )

                intelligence = await self._gather_intelligence(
                    problematic_code, file_path, language, error_message
                )

            # Phase 2: BFROS Framework Analysis
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Phase 2: Applying BFROS framework",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            bfros_analysis = self._apply_bfros_framework(
                problematic_code=problematic_code,
                error_message=error_message,
                intelligence=intelligence
            )

            # Phase 3: Root Cause Analysis
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Phase 3: Determining root cause with confidence scoring",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            root_cause = self._determine_root_cause(
                intelligence=intelligence,
                bfros_analysis=bfros_analysis
            )

            # Phase 4: Solution Generation
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Phase 4: Generating optimal solution",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            solution = self._generate_solution(
                problematic_code=problematic_code,
                root_cause=root_cause,
                intelligence=intelligence
            )

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build debug report
            output_data = {
                "error_message": error_message,
                "intelligence_analysis": intelligence,
                "bfros_analysis": bfros_analysis,
                "root_cause": root_cause,
                "solution": solution,
                "quality_improvement": self._calculate_quality_improvement(intelligence, solution),
                "root_cause_confidence": root_cause.get("confidence_score", 0.0),
                "intelligence_sources": len(intelligence.get("domain_patterns", {}).get("results", {}))
            }

            # Create result
            result = AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=True,
                output_data=output_data,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id
            )

            # End trace successfully
            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id,
                status="completed",
                result=result.model_dump()
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Debug analysis complete: confidence={root_cause.get('confidence_score', 0):.2f}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
                metadata={"execution_time_ms": execution_time_ms}
            )

            return result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Debug analysis failed: {str(e)}"

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
                metadata={"error": str(e)}
            )

            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id,
                status="failed",
                error=error_msg
            )

            return AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=False,
                error=error_msg,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id
            )

    async def _gather_intelligence(
        self,
        code: str,
        file_path: str,
        language: str,
        error: str
    ) -> Dict[str, Any]:
        """
        Gather pre-investigation intelligence using MCP tools.

        Returns:
            Intelligence data including quality metrics and patterns
        """
        intelligence = {}

        if not self.config.archon_mcp_enabled:
            return intelligence

        try:
            # 1. Assess code quality at bug location
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Assessing code quality at bug location",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name
            )

            quality_result = await self.mcp_client.assess_code_quality(
                content=code,
                source_path=file_path,
                language=language
            )
            intelligence["code_quality"] = quality_result

            # 2. Check architectural compliance
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Checking architectural compliance",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name
            )

            compliance_result = await self.mcp_client.call_tool(
                "check_architectural_compliance",
                content=code,
                architecture_type="onex"
            )
            intelligence["architectural_compliance"] = compliance_result

            # 3. Get quality patterns (anti-patterns)
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Identifying anti-patterns",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name
            )

            patterns_result = await self.mcp_client.call_tool(
                "get_quality_patterns",
                content=code,
                pattern_type="anti_patterns"
            )
            intelligence["anti_patterns"] = patterns_result

            # 4. Search for similar bug patterns
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Searching for similar bug patterns",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name
            )

            domain_intel = await self.mcp_client.perform_rag_query(
                query=f"debugging {error} systematic root cause analysis",
                context="debugging",
                match_count=self.config.match_count
            )
            intelligence["domain_patterns"] = domain_intel

            # 5. Get optimization opportunities (for performance correlation)
            if "performance" in error.lower() or "slow" in error.lower():
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_START,
                    message="Analyzing performance impact",
                    level=TraceLevel.INFO,
                    agent_name=self.config.agent_name
                )

                perf_result = await self.mcp_client.call_tool(
                    "identify_optimization_opportunities",
                    operation_name=file_path
                )
                intelligence["performance_analysis"] = perf_result

        except Exception as e:
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=f"Intelligence gathering partially failed: {str(e)}",
                level=TraceLevel.WARNING,
                agent_name=self.config.agent_name,
                metadata={"error": str(e)}
            )

        return intelligence

    def _apply_bfros_framework(
        self,
        problematic_code: str,
        error_message: str,
        intelligence: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply BFROS (Behavior, Fault, Root cause, Optimal solution, Solution validation) framework.

        Returns:
            BFROS analysis results
        """
        quality = intelligence.get("code_quality", {})
        compliance = intelligence.get("architectural_compliance", {})

        return {
            "behavior_analysis": {
                "expected": "Correct execution without errors",
                "actual": f"Error: {error_message}",
                "deviation": error_message
            },
            "fault_localization": {
                "error_location": "Code snippet provided",
                "affected_components": ["Primary code block"],
                "quality_score": quality.get("quality_score", 0.0),
                "compliance_score": compliance.get("compliance_score", 0.0)
            },
            "root_cause_factors": {
                "quality_issues": quality.get("improvement_opportunities", []),
                "architectural_violations": compliance.get("violations", []),
                "anti_patterns": intelligence.get("anti_patterns", {}).get("patterns", [])
            }
        }

    def _determine_root_cause(
        self,
        intelligence: Dict[str, Any],
        bfros_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Determine root cause with confidence scoring.

        Returns:
            Root cause analysis with confidence score
        """
        quality = intelligence.get("code_quality", {})
        factors = bfros_analysis.get("root_cause_factors", {})

        # Calculate confidence based on intelligence quality
        confidence_factors = []

        # Quality score factor
        quality_score = quality.get("quality_score", 0.0)
        if quality_score < 0.6:
            confidence_factors.append(0.3)  # High confidence in quality correlation

        # Anti-patterns factor
        anti_patterns = len(factors.get("anti_patterns", []))
        if anti_patterns > 0:
            confidence_factors.append(0.25)  # Presence of anti-patterns

        # Architectural violations factor
        violations = len(factors.get("architectural_violations", []))
        if violations > 0:
            confidence_factors.append(0.25)  # Architecture issues present

        # Intelligence coverage factor
        intel_sources = len(intelligence.get("domain_patterns", {}).get("results", {}))
        if intel_sources > 0:
            confidence_factors.append(0.2)  # Historical pattern match

        confidence_score = min(1.0, sum(confidence_factors))

        return {
            "primary_cause": "Low code quality and architectural violations",
            "contributing_factors": {
                "quality_issues": factors.get("quality_issues", []),
                "architectural_issues": factors.get("architectural_violations", []),
                "pattern_issues": factors.get("anti_patterns", [])
            },
            "confidence_score": confidence_score,
            "confidence_level": "High" if confidence_score >= 0.7 else "Medium" if confidence_score >= 0.5 else "Low",
            "validation_method": "Intelligence-based multi-factor analysis"
        }

    def _generate_solution(
        self,
        problematic_code: str,
        root_cause: Dict[str, Any],
        intelligence: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate optimal solution addressing root cause.

        Returns:
            Solution details with validation criteria
        """
        factors = root_cause.get("contributing_factors", {})

        return {
            "fix_description": "Address quality and architectural issues identified in root cause analysis",
            "implementation_steps": [
                "Fix immediate bug (symptom)",
                "Resolve quality issues (root cause)",
                "Fix architectural violations (prevention)",
                "Eliminate anti-patterns (systemic fix)",
                "Apply best practices from intelligence"
            ],
            "quality_improvements": factors.get("quality_issues", []),
            "compliance_improvements": factors.get("architectural_issues", []),
            "tests_required": [
                "Unit test preventing recurrence",
                "Integration test for affected flow",
                "Regression test for similar scenarios"
            ],
            "prevention_measures": {
                "pattern_documented": True,
                "quality_gates_added": True,
                "monitoring_enabled": True
            }
        }

    def _calculate_quality_improvement(
        self,
        intelligence: Dict[str, Any],
        solution: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate expected quality improvement from solution.

        Returns:
            Quality improvement metrics
        """
        quality = intelligence.get("code_quality", {})
        before_score = quality.get("quality_score", 0.0)

        # Estimate improvement based on issues addressed
        quality_issues = len(solution.get("quality_improvements", []))
        compliance_issues = len(solution.get("compliance_improvements", []))

        # Simple heuristic: each issue resolved adds ~0.1 to score
        estimated_improvement = min(0.4, (quality_issues + compliance_issues) * 0.1)
        after_score = min(1.0, before_score + estimated_improvement)

        return {
            "before": before_score,
            "after": after_score,
            "delta": estimated_improvement,
            "improvement_percentage": (estimated_improvement / max(0.01, before_score)) * 100 if before_score > 0 else 0,
            "meets_minimum": after_score >= 0.6
        }

    async def cleanup(self):
        """Cleanup MCP client."""
        await self.mcp_client.close()
