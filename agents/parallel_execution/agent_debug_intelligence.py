"""
Pydantic AI-based Debug Intelligence Agent

Multi-dimensional debugging with LLM-powered analysis, quality correlation,
pattern recognition, and root cause identification.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_model import AgentConfig, AgentResult, AgentTask
from agent_registry import register_agent
from mcp_client import ArchonMCPClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from trace_logger import TraceEventType, TraceLevel, get_trace_logger

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


class BFROSAnalysis(BaseModel):
    """BFROS Framework Analysis."""

    behavior_expected: str = Field(description="Expected behavior")
    behavior_actual: str = Field(description="Actual observed behavior")
    behavior_deviation: str = Field(description="Deviation from expected")
    fault_location: str = Field(description="Where the fault manifests")
    fault_components: List[str] = Field(description="Affected components")
    root_cause_description: str = Field(description="Primary root cause")
    contributing_factors: List[str] = Field(description="Contributing factors")


class RootCauseAnalysis(BaseModel):
    """Root cause determination with confidence."""

    primary_cause: str = Field(description="Primary root cause identified")
    contributing_factors: List[str] = Field(description="Secondary factors")
    confidence_score: float = Field(
        description="Confidence score 0.0-1.0", ge=0.0, le=1.0
    )
    confidence_level: str = Field(description="High/Medium/Low confidence")
    validation_method: str = Field(description="How confidence was determined")
    quality_correlation: bool = Field(description="Whether quality issues correlate")
    pattern_matches: List[str] = Field(
        default_factory=list, description="Matching historical patterns"
    )


class DebugSolution(BaseModel):
    """Solution addressing root cause."""

    fix_description: str = Field(description="Description of the fix")
    implementation_steps: List[str] = Field(description="Step-by-step implementation")
    fixed_code: str = Field(description="Corrected code snippet")
    quality_improvements: List[str] = Field(description="Quality improvements made")
    tests_required: List[str] = Field(description="Tests needed for validation")
    prevention_measures: List[str] = Field(description="Measures to prevent recurrence")
    estimated_quality_improvement: float = Field(
        description="Expected quality score improvement", ge=0.0, le=1.0
    )


class DebugAnalysis(BaseModel):
    """Complete debug analysis output."""

    error_summary: str = Field(description="Summary of the error")
    bfros_analysis: BFROSAnalysis = Field(description="BFROS framework analysis")
    root_cause: RootCauseAnalysis = Field(description="Root cause determination")
    solution: DebugSolution = Field(description="Proposed solution")
    intelligence_sources_used: int = Field(
        description="Number of intelligence sources consulted"
    )
    analysis_completeness: float = Field(
        description="Completeness score 0.0-1.0", ge=0.0, le=1.0
    )


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
    problematic_code: str
    error_message: str


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

DEBUG_SYSTEM_PROMPT = """You are an expert debugging analyst with deep knowledge of systematic root cause analysis.

**Your Expertise:**
- BFROS Framework (Behavior, Fault, Root cause, Optimal solution, Solution validation)
- Multi-dimensional debugging (quality, architecture, performance, patterns)
- Root cause analysis with confidence scoring
- Intelligent solution generation

**Your Task:**
Analyze the problematic code and error to:
1. Apply BFROS framework systematically
2. Determine root cause with high confidence
3. Generate optimal solution with quality improvements
4. Provide implementation steps and prevention measures

**Analysis Requirements:**
- Use intelligence from quality assessments and pattern recognition
- Correlate quality scores with bug manifestation
- Identify anti-patterns and architectural violations
- Calculate confidence scores based on evidence
- Generate complete, runnable fixed code
- Include comprehensive test requirements

**Quality Standards:**
- Confidence scores must be evidence-based
- Solutions must address root cause, not symptoms
- Fixed code must be production-ready
- Prevention measures must be specific and actionable

Analyze thoroughly using available tools and generate complete debug analysis."""

# Create the Pydantic AI agent
debug_intelligence_agent = Agent[AgentDeps, DebugAnalysis](
    "google-gla:gemini-2.5-flash",  # Latest Gemini Flash model
    deps_type=AgentDeps,
    output_type=DebugAnalysis,
    system_prompt=DEBUG_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@debug_intelligence_agent.tool
async def get_code_quality_intelligence(ctx: RunContext[AgentDeps]) -> str:
    """Get code quality assessment and intelligence for the problematic code.

    Returns: Summary of quality metrics, anti-patterns, and architectural compliance
    """
    deps = ctx.deps
    intelligence = deps.intelligence

    quality_summary = []

    # Code quality assessment
    if "code_quality" in intelligence:
        quality = intelligence["code_quality"]
        quality_summary.append("**Code Quality Assessment:**")
        quality_summary.append(
            f"- Quality Score: {quality.get('quality_score', 0.0):.2f}"
        )
        quality_summary.append(
            f"- Architectural Compliance: {quality.get('onex_compliance', 0.0):.2f}"
        )

        if "improvement_opportunities" in quality:
            quality_summary.append("- Improvement Opportunities:")
            for opp in quality.get("improvement_opportunities", [])[:3]:
                quality_summary.append(f"  • {opp}")

    # Anti-patterns
    if "anti_patterns" in intelligence:
        patterns = intelligence["anti_patterns"]
        quality_summary.append("\n**Anti-Patterns Detected:**")
        pattern_list = (
            patterns.get("patterns", []) if isinstance(patterns, dict) else []
        )
        for pattern in pattern_list[:3]:
            quality_summary.append(f"- {pattern}")

    # Architectural compliance
    if "architectural_compliance" in intelligence:
        compliance = intelligence["architectural_compliance"]
        quality_summary.append("\n**Architectural Compliance:**")
        quality_summary.append(
            f"- Compliance Score: {compliance.get('compliance_score', 0.0):.2f}"
        )
        violations = compliance.get("violations", [])
        if violations:
            quality_summary.append("- Violations:")
            for violation in violations[:3]:
                quality_summary.append(f"  • {violation}")

    return (
        "\n".join(quality_summary)
        if quality_summary
        else "No quality intelligence available"
    )


@debug_intelligence_agent.tool
async def get_bfros_standards(ctx: RunContext[AgentDeps]) -> str:
    """Get BFROS framework standards and debugging methodology.

    Returns: BFROS framework guidelines
    """
    return """
**BFROS Framework for Systematic Debugging:**

1. **Behavior Analysis:**
   - Expected: What should happen
   - Actual: What is happening
   - Deviation: Gap analysis

2. **Fault Localization:**
   - Where the error manifests
   - Affected components
   - Quality/compliance correlation

3. **Root Cause Determination:**
   - Primary cause (not symptom)
   - Contributing factors
   - Confidence scoring based on:
     * Quality score < 0.6 → +0.3 confidence
     * Anti-patterns present → +0.25 confidence
     * Architectural violations → +0.25 confidence
     * Historical patterns match → +0.2 confidence

4. **Optimal Solution:**
   - Address root cause
   - Fix quality issues
   - Resolve architectural violations
   - Eliminate anti-patterns

5. **Solution Validation:**
   - Unit tests for recurrence prevention
   - Integration tests for affected flows
   - Regression tests for similar scenarios
   - Quality gate compliance
"""


@debug_intelligence_agent.tool
async def get_debug_patterns(ctx: RunContext[AgentDeps]) -> str:
    """Get historical debug patterns and similar bug resolutions.

    Returns: Similar patterns and resolutions from knowledge base
    """
    deps = ctx.deps
    intelligence = deps.intelligence

    patterns_summary = []

    # Domain patterns from RAG
    if "domain_patterns" in intelligence:
        domain = intelligence["domain_patterns"]
        patterns_summary.append("**Historical Debug Patterns:**")

        # Extract synthesis insights
        if isinstance(domain, dict) and "synthesis" in domain:
            synthesis = domain["synthesis"]
            if "key_findings" in synthesis:
                patterns_summary.append("Key Findings:")
                for finding in synthesis["key_findings"][:3]:
                    patterns_summary.append(f"- {finding}")

            if "patterns_identified" in synthesis:
                patterns_summary.append("\nPatterns Identified:")
                for pattern in synthesis["patterns_identified"][:3]:
                    patterns_summary.append(f"- {pattern}")

    # Performance patterns if available
    if "performance_analysis" in intelligence:
        perf = intelligence["performance_analysis"]
        patterns_summary.append("\n**Performance Patterns:**")
        if isinstance(perf, dict):
            patterns_summary.append(
                f"- Optimization opportunities identified: {len(perf.get('opportunities', []))}"
            )

    return (
        "\n".join(patterns_summary)
        if patterns_summary
        else "No historical patterns available"
    )


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


@register_agent(
    agent_name="debug",
    agent_type="debug",
    capabilities=[
        "debug_analysis",
        "root_cause_analysis",
        "bfros_analysis",
        "solution_generation",
    ],
    description="Multi-dimensional debug intelligence agent",
)
class DebugIntelligenceAgent:
    """
    Pydantic AI-based debug intelligence agent.

    Provides multi-dimensional debugging with LLM-powered root cause analysis.
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-debug-intelligence")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute debug analysis using Pydantic AI agent.

        Args:
            task: Task containing bug information and code

        Returns:
            AgentResult with debug analysis
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
            problematic_code = task.input_data.get("code", "")
            file_path = task.input_data.get("file_path", "unknown.py")
            language = task.input_data.get("language", "python")
            error_message = task.input_data.get("error", "")
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Debugging: {error_message[:100]}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Gather intelligence
            intelligence = await self._gather_intelligence(
                task,
                problematic_code,
                file_path,
                language,
                error_message,
                pre_gathered_context,
            )

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                mcp_client=self.mcp_client,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
                intelligence=intelligence,
                problematic_code=problematic_code,
                error_message=error_message,
            )

            # Build analysis prompt
            prompt = self._build_analysis_prompt(task, problematic_code, error_message)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI debug analyzer",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            result = await debug_intelligence_agent.run(prompt, deps=deps)
            debug_output: DebugAnalysis = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "error_message": error_message,
                "error_summary": debug_output.error_summary,
                "bfros_analysis": debug_output.bfros_analysis.model_dump(),
                "root_cause": debug_output.root_cause.model_dump(),
                "solution": debug_output.solution.model_dump(),
                "intelligence_analysis": intelligence,
                "quality_improvement": {
                    "before": intelligence.get("code_quality", {}).get(
                        "quality_score", 0.0
                    ),
                    "after": intelligence.get("code_quality", {}).get(
                        "quality_score", 0.0
                    )
                    + debug_output.solution.estimated_quality_improvement,
                    "delta": debug_output.solution.estimated_quality_improvement,
                },
                "root_cause_confidence": debug_output.root_cause.confidence_score,
                "intelligence_sources": debug_output.intelligence_sources_used,
                "analysis_completeness": debug_output.analysis_completeness,
                "pydantic_ai_metadata": {
                    "model_used": "gemini-2.5-flash",
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
                message=f"Debug analysis complete: confidence={debug_output.root_cause.confidence_score:.2f}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Debug analysis failed: {str(e)}"

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
        self,
        task: AgentTask,
        code: str,
        file_path: str,
        language: str,
        error: str,
        pre_gathered_context: Dict[str, Any],
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
                    intelligence["anti_patterns"] = context_item.get("content", {})
                elif context_type == "file":
                    intelligence.setdefault("related_files", []).append(
                        context_item.get("content", "")
                    )

        # Always assess the problematic code itself
        if self.config.archon_mcp_enabled and code:
            try:
                # Code quality assessment
                quality_result = await self.mcp_client.assess_code_quality(
                    content=code, source_path=file_path, language=language
                )
                intelligence["code_quality"] = quality_result

                # Architectural compliance check
                compliance_result = await self.mcp_client.call_tool(
                    "check_architectural_compliance",
                    content=code,
                    architecture_type="onex",
                )
                intelligence["architectural_compliance"] = compliance_result

                # Anti-patterns detection
                patterns_result = await self.mcp_client.call_tool(
                    "get_quality_patterns", content=code, pattern_type="anti_patterns"
                )
                intelligence["anti_patterns"] = patterns_result

                # Historical patterns if not pre-gathered
                if not pre_gathered_context:
                    domain_intel = await self.mcp_client.perform_rag_query(
                        query=f"debugging {error} systematic root cause analysis",
                        context="debugging",
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

    def _build_analysis_prompt(self, task: AgentTask, code: str, error: str) -> str:
        """Build detailed analysis prompt for LLM."""
        return f"""Analyze this bug using systematic debugging methodology:

**Error:**
{error}

**Problematic Code:**
```python
{code}
```

**Task Description:**
{task.description}

**Your Analysis Must Include:**

1. **BFROS Framework Application:**
   - Behavior: Expected vs actual
   - Fault: Location and components
   - Root Cause: Primary cause with contributing factors
   - Optimal Solution: Complete fix addressing root cause
   - Solution Validation: Tests and prevention

2. **Root Cause Determination:**
   - Calculate confidence score using quality correlation
   - Identify pattern matches from historical data
   - Provide evidence-based validation method

3. **Solution Generation:**
   - Generate complete, runnable fixed code
   - List specific implementation steps
   - Include comprehensive test requirements
   - Specify prevention measures

Use available tools to:
1. Get code quality intelligence for correlation analysis
2. Get BFROS standards for systematic approach
3. Get debug patterns for historical context

Provide complete, actionable debug analysis with high confidence scoring."""

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, "close"):
            await self.mcp_client.close()
