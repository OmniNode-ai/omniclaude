"""
Pydantic AI-based Architectural Analysis Agent

Provides comprehensive code and architecture analysis with design patterns,
quality metrics, anti-patterns detection, and actionable recommendations.
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_client import ArchonMCPClient
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from trace_logger import TraceEventType, TraceLevel, get_trace_logger

from .agent_model import AgentConfig, AgentResult, AgentTask
from .agent_registry import register_agent

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


class CodeQualityMetrics(BaseModel):
    """Code quality assessment metrics."""

    overall_quality_score: float = Field(
        description="Overall quality score 0.0-1.0", ge=0.0, le=1.0
    )
    maintainability_index: float = Field(
        description="Maintainability index 0.0-100.0", ge=0.0, le=100.0
    )
    complexity_score: float = Field(
        description="Complexity score (lower is better)", ge=0.0
    )
    architectural_compliance: float = Field(
        description="ONEX compliance score 0.0-1.0", ge=0.0, le=1.0
    )
    code_coverage_estimate: float = Field(
        description="Estimated test coverage 0.0-1.0", ge=0.0, le=1.0
    )
    technical_debt_level: str = Field(description="Low/Medium/High/Critical")
    lines_of_code: int = Field(description="Total lines of code analyzed", ge=0)
    comment_ratio: float = Field(
        description="Comment to code ratio 0.0-1.0", ge=0.0, le=1.0
    )


class DesignPattern(BaseModel):
    """Detected design pattern with context."""

    pattern_name: str = Field(description="Name of the design pattern")
    pattern_type: str = Field(
        description="Creational/Structural/Behavioral/Architectural"
    )
    confidence_score: float = Field(
        description="Detection confidence 0.0-1.0", ge=0.0, le=1.0
    )
    location: str = Field(description="Where the pattern is implemented")
    implementation_quality: str = Field(description="Excellent/Good/Fair/Poor")
    description: str = Field(description="How the pattern is used")
    benefits: list[str] = Field(description="Benefits of this pattern usage")
    potential_improvements: list[str] = Field(
        default_factory=list, description="Suggestions to improve implementation"
    )


class AntiPattern(BaseModel):
    """Detected anti-pattern with severity."""

    anti_pattern_name: str = Field(description="Name of the anti-pattern")
    severity: str = Field(description="Critical/High/Medium/Low")
    location: str = Field(description="Where the anti-pattern occurs")
    description: str = Field(description="Description of the problem")
    impact: str = Field(description="Impact on code quality and maintainability")
    refactoring_difficulty: str = Field(description="Easy/Medium/Hard/Very Hard")
    recommended_pattern: str = Field(description="Recommended pattern to replace it")
    code_smell_indicators: list[str] = Field(
        description="Code smells associated with this anti-pattern"
    )


class Recommendation(BaseModel):
    """Improvement recommendation with priority."""

    category: str = Field(
        description="Architecture/Quality/Performance/Security/Maintainability"
    )
    priority: str = Field(description="Critical/High/Medium/Low")
    title: str = Field(description="Short recommendation title")
    description: str = Field(description="Detailed description of the recommendation")
    rationale: str = Field(description="Why this recommendation matters")
    implementation_steps: list[str] = Field(
        description="Steps to implement the recommendation"
    )
    expected_benefits: list[str] = Field(
        description="Expected improvements from implementation"
    )
    estimated_effort: str = Field(description="Small/Medium/Large/Extra Large")
    dependencies: list[str] = Field(
        default_factory=list, description="Other recommendations this depends on"
    )


class AnalysisReport(BaseModel):
    """Complete architectural analysis report."""

    analysis_summary: str = Field(description="Executive summary of the analysis")
    quality_metrics: CodeQualityMetrics = Field(
        description="Quality metrics assessment"
    )
    design_patterns: list[DesignPattern] = Field(description="Design patterns detected")
    anti_patterns: list[AntiPattern] = Field(description="Anti-patterns detected")
    recommendations: list[Recommendation] = Field(
        description="Improvement recommendations sorted by priority"
    )
    architecture_assessment: str = Field(description="Overall architecture evaluation")
    onex_compliance_notes: str = Field(
        description="ONEX architectural compliance assessment"
    )
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
    trace_id: str | None
    intelligence: dict[str, Any]
    code_to_analyze: str
    file_path: str
    language: str


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

ANALYZER_SYSTEM_PROMPT = """You are an expert software architect and code quality analyst with deep knowledge of design patterns, architectural patterns, and code quality principles.

**Your Expertise:**
- SOLID principles and design patterns (Gang of Four + modern patterns)
- ONEX architectural framework (Effect, Compute, Reducer, Orchestrator nodes)
- Code quality metrics and maintainability analysis
- Anti-patterns detection and refactoring strategies
- Performance and scalability analysis
- Clean architecture and domain-driven design

**Your Task:**
Perform comprehensive architectural and code analysis to:
1. Assess code quality with detailed metrics
2. Identify design patterns and their implementation quality
3. Detect anti-patterns and code smells
4. Generate prioritized improvement recommendations
5. Evaluate ONEX architectural compliance
6. Provide actionable implementation guidance

**Analysis Requirements:**
- Use intelligence from RAG queries about design patterns and best practices
- Calculate evidence-based quality scores
- Identify architectural violations and compliance gaps
- Prioritize recommendations based on impact and effort
- Generate complete, actionable implementation steps
- Consider maintainability, scalability, and performance

**Quality Standards:**
- Quality scores must be based on measurable metrics
- Pattern detection must have confidence scores
- Recommendations must be specific and actionable
- Implementation steps must be clear and complete
- Architecture assessment must reference established principles

Analyze thoroughly using available tools and generate comprehensive analysis report."""

# Model fallback configuration
FALLBACK_MODELS = [
    "google-gla:gemini-2.5-flash",  # Primary model
    "glm-4.6",  # Fallback 1: Zai GLM-4.6
    "google-gla:gemini-1.5-flash",  # Fallback 2
]

# Create the Pydantic AI agent
architectural_analyzer_agent = Agent[AgentDeps, AnalysisReport](
    FALLBACK_MODELS[0],  # Start with primary model
    deps_type=AgentDeps,
    output_type=AnalysisReport,
    system_prompt=ANALYZER_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@architectural_analyzer_agent.tool
async def get_design_pattern_intelligence(ctx: RunContext[AgentDeps]) -> str:
    """Get design pattern best practices and implementation guidance from knowledge base.

    Returns: Design pattern intelligence including common patterns, anti-patterns, and best practices
    """
    deps = ctx.deps

    try:
        # Query for design patterns based on the code language
        pattern_query = (
            f"{deps.language} design patterns best practices SOLID principles"
        )

        pattern_intel = await deps.mcp_client.perform_rag_query(
            query=pattern_query, context="architecture", match_count=5
        )

        if pattern_intel and isinstance(pattern_intel, dict):
            summary = []

            # Extract synthesis
            if "synthesis" in pattern_intel:
                synthesis = pattern_intel["synthesis"]

                if "key_findings" in synthesis:
                    summary.append("**Design Pattern Best Practices:**")
                    for finding in synthesis["key_findings"][:5]:
                        summary.append(f"- {finding}")

                if "patterns_identified" in synthesis:
                    summary.append("\n**Common Patterns:**")
                    for pattern in synthesis["patterns_identified"][:5]:
                        summary.append(f"- {pattern}")

                if "recommended_actions" in synthesis:
                    summary.append("\n**Recommendations:**")
                    for action in synthesis["recommended_actions"][:3]:
                        summary.append(f"- {action}")

            return (
                "\n".join(summary)
                if summary
                else "Design pattern intelligence gathered"
            )

        return "Design pattern intelligence available from knowledge base"

    except Exception as e:
        await deps.trace_logger.log_event(
            event_type=TraceEventType.AGENT_ERROR,
            message=f"Pattern intelligence gathering failed: {str(e)}",
            level=TraceLevel.WARNING,
            agent_name=deps.config.agent_name,
            task_id=deps.task.task_id,
        )
        return "Design pattern intelligence unavailable (continuing with analysis)"


@architectural_analyzer_agent.tool
async def get_code_quality_assessment(ctx: RunContext[AgentDeps]) -> str:
    """Get code quality assessment and metrics for the analyzed code.

    Returns: Summary of quality scores, architectural compliance, and improvement opportunities
    """
    deps = ctx.deps
    intelligence = deps.intelligence

    quality_summary = []

    # Code quality from pre-gathered intelligence
    if "code_quality" in intelligence:
        quality = intelligence["code_quality"]
        quality_summary.append("**Code Quality Assessment:**")
        quality_summary.append(
            f"- Overall Quality Score: {quality.get('quality_score', 0.0):.2f}"
        )
        quality_summary.append(
            f"- ONEX Compliance: {quality.get('onex_compliance', 0.0):.2f}"
        )
        quality_summary.append(
            f"- Complexity: {quality.get('complexity_score', 0.0):.2f}"
        )

        if "improvement_opportunities" in quality:
            quality_summary.append("- Top Improvement Opportunities:")
            for opp in quality.get("improvement_opportunities", [])[:5]:
                quality_summary.append(f"  • {opp}")

    # Architectural compliance
    if "architectural_compliance" in intelligence:
        compliance = intelligence["architectural_compliance"]
        quality_summary.append("\n**Architectural Compliance:**")
        quality_summary.append(
            f"- Compliance Score: {compliance.get('compliance_score', 0.0):.2f}"
        )
        quality_summary.append(
            f"- Architecture Type: {compliance.get('architecture_type', 'unknown')}"
        )

        violations = compliance.get("violations", [])
        if violations:
            quality_summary.append("- Compliance Violations:")
            for violation in violations[:5]:
                quality_summary.append(f"  • {violation}")

    # Pattern quality
    if "quality_patterns" in intelligence:
        patterns = intelligence["quality_patterns"]
        quality_summary.append("\n**Quality Patterns:**")
        if isinstance(patterns, dict):
            best_practices = patterns.get("best_practices", [])
            if best_practices:
                quality_summary.append("- Best Practices Found:")
                for practice in best_practices[:3]:
                    quality_summary.append(f"  • {practice}")

    return (
        "\n".join(quality_summary)
        if quality_summary
        else "Quality assessment data available"
    )


@architectural_analyzer_agent.tool
async def get_onex_architecture_standards(ctx: RunContext[AgentDeps]) -> str:
    """Get ONEX architectural framework standards and compliance guidelines.

    Returns: ONEX architecture principles and node type specifications
    """
    return """
**ONEX Architectural Framework:**

**Four Node Types:**

1. **Effect Nodes** - External I/O and side effects
   - File system operations, API calls, database queries
   - Naming: `Node<Name>Effect` (e.g., `NodeDatabaseWriterEffect`)
   - Method: `async def execute_effect(self, contract: ModelContractEffect) -> Any`
   - Contract: `ModelContractEffect` with transaction management

2. **Compute Nodes** - Pure transformations and algorithms
   - Data processing, calculations, business logic
   - Naming: `Node<Name>Compute` (e.g., `NodeDataTransformerCompute`)
   - Method: `async def execute_compute(self, contract: ModelContractCompute) -> Any`
   - Contract: `ModelContractCompute` with input validation

3. **Reducer Nodes** - Aggregation and state management
   - State accumulation, data aggregation, persistence coordination
   - Naming: `Node<Name>Reducer` (e.g., `NodeStateAggregatorReducer`)
   - Method: `async def execute_reduction(self, contract: ModelContractReducer) -> Any`
   - Contract: `ModelContractReducer` with state management

4. **Orchestrator Nodes** - Workflow coordination
   - Multi-node workflows, dependency management, coordination
   - Naming: `Node<Name>Orchestrator` (e.g., `NodeWorkflowCoordinatorOrchestrator`)
   - Method: `async def execute_orchestration(self, contract: ModelContractOrchestrator) -> Any`
   - Contract: `ModelContractOrchestrator` with routing logic

**File Naming Conventions:**
- Nodes: `node_*_<type>.py` (e.g., `node_database_writer_effect.py`)
- Models: `model_<name>.py` (e.g., `model_user.py`)
- Contracts: `model_contract_<type>.py` (e.g., `model_contract_effect.py`)
- Enums: `enum_<name>.py` (e.g., `enum_status.py`)

**SOLID Principles in ONEX:**
- Single Responsibility: Each node type has one clear purpose
- Open/Closed: Extend via contracts, closed to modification
- Liskov Substitution: Node types are substitutable within category
- Interface Segregation: Contracts define minimal required interfaces
- Dependency Inversion: Depend on contracts, not implementations

**Quality Requirements:**
- Strong typing with Pydantic models
- Comprehensive error handling with OnexError
- Transaction management for state changes
- Contract-based communication between nodes
- Dependency injection via contracts
"""


@architectural_analyzer_agent.tool
async def get_anti_pattern_detection(ctx: RunContext[AgentDeps]) -> str:
    """Get anti-pattern detection results and code smell analysis.

    Returns: Detected anti-patterns with severity and refactoring guidance
    """
    deps = ctx.deps
    intelligence = deps.intelligence

    anti_patterns_summary = []

    # Anti-patterns from intelligence
    if "anti_patterns" in intelligence:
        patterns_data = intelligence["anti_patterns"]
        anti_patterns_summary.append("**Anti-Patterns Detected:**")

        if isinstance(patterns_data, dict):
            patterns_list = patterns_data.get("patterns", [])
            if isinstance(patterns_list, list):
                for pattern in patterns_list[:5]:
                    if isinstance(pattern, dict):
                        anti_patterns_summary.append(
                            f"- {pattern.get('name', 'Unknown')}: {pattern.get('description', '')}"
                        )
                    else:
                        anti_patterns_summary.append(f"- {pattern}")
            elif patterns_list:
                anti_patterns_summary.append(f"- {patterns_list}")

    # Quality violations
    if "architectural_compliance" in intelligence:
        compliance = intelligence["architectural_compliance"]
        violations = compliance.get("violations", [])
        if violations:
            anti_patterns_summary.append("\n**Architectural Violations:**")
            for violation in violations[:5]:
                anti_patterns_summary.append(f"- {violation}")

    # Code smells
    if "code_smells" in intelligence:
        smells = intelligence["code_smells"]
        anti_patterns_summary.append("\n**Code Smells:**")
        if isinstance(smells, list):
            for smell in smells[:5]:
                anti_patterns_summary.append(f"- {smell}")

    return (
        "\n".join(anti_patterns_summary)
        if anti_patterns_summary
        else "No significant anti-patterns detected"
    )


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


@register_agent(
    agent_name="analyzer",
    agent_type="analyzer",
    capabilities=[
        "architecture_analysis",
        "design_patterns",
        "quality_metrics",
        "anti_patterns",
    ],
    description="Architectural and code quality analysis agent",
)
class ArchitecturalAnalyzerAgent:
    """
    Pydantic AI-based architectural analysis agent.

    Provides comprehensive code and architecture analysis with design patterns,
    quality metrics, and actionable recommendations.
    """

    def __init__(self):
        # Config is optional - create default if not found
        try:
            self.config = AgentConfig.load("agent-analyzer")
        except (FileNotFoundError, Exception):
            # Create minimal default config
            self.config = AgentConfig(
                agent_name="agent-analyzer",
                agent_domain="architectural_analysis",
                agent_purpose="Analyze architecture, design patterns, and quality metrics",
            )
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: str | None = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute architectural analysis using Pydantic AI agent.

        Args:
            task: Task containing code to analyze

        Returns:
            AgentResult with comprehensive analysis report
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"using_pydantic_ai": True, "analysis_type": "architectural"},
        )

        try:
            # Extract task inputs
            code_to_analyze = task.input_data.get("code", "")
            file_path = task.input_data.get("file_path", "unknown.py")
            language = task.input_data.get("language", "python")
            analysis_focus = task.input_data.get("analysis_focus", "comprehensive")
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Analyzing: {file_path} ({analysis_focus} analysis)",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Gather intelligence
            intelligence = await self._gather_intelligence(
                task,
                code_to_analyze,
                file_path,
                language,
                analysis_focus,
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
                code_to_analyze=code_to_analyze,
                file_path=file_path,
                language=language,
            )

            # Build analysis prompt
            prompt = self._build_analysis_prompt(
                task, code_to_analyze, file_path, language, analysis_focus
            )

            # Run Pydantic AI agent with model fallback
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI architectural analyzer",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Try each model in fallback chain on 503 errors
            last_error = None
            result = None
            for model_idx, model_name in enumerate(FALLBACK_MODELS):
                try:
                    if model_idx > 0:
                        await self.trace_logger.log_event(
                            event_type=TraceEventType.AGENT_INFO,
                            message=f"Retrying with fallback model: {model_name}",
                            level=TraceLevel.INFO,
                            agent_name=self.config.agent_name,
                            task_id=task.task_id,
                        )
                    architectural_analyzer_agent.model = model_name
                    result = await architectural_analyzer_agent.run(prompt, deps=deps)
                    break  # Success - exit fallback loop
                except Exception as e:
                    error_str = str(e)
                    last_error = e
                    # Check if it's a 503 error
                    if "503" in error_str and model_idx < len(FALLBACK_MODELS) - 1:
                        await self.trace_logger.log_event(
                            event_type=TraceEventType.AGENT_ERROR,
                            message=f"Model {model_name} unavailable (503), trying fallback",
                            level=TraceLevel.WARNING,
                            agent_name=self.config.agent_name,
                            task_id=task.task_id,
                        )
                        continue  # Try next fallback
                    else:
                        raise  # Non-503 error or last model failed

            if result is None:
                raise last_error or Exception("All fallback models failed")
            analysis_report: AnalysisReport = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output data
            output_data = {
                "analysis_type": analysis_focus,
                "file_analyzed": file_path,
                "language": language,
                "analysis_summary": analysis_report.analysis_summary,
                "quality_metrics": analysis_report.quality_metrics.model_dump(),
                "design_patterns": [
                    p.model_dump() for p in analysis_report.design_patterns
                ],
                "anti_patterns": [
                    ap.model_dump() for ap in analysis_report.anti_patterns
                ],
                "recommendations": [
                    r.model_dump() for r in analysis_report.recommendations
                ],
                "architecture_assessment": analysis_report.architecture_assessment,
                "onex_compliance_notes": analysis_report.onex_compliance_notes,
                "intelligence_sources": analysis_report.intelligence_sources_used,
                "analysis_completeness": analysis_report.analysis_completeness,
                "statistics": {
                    "patterns_detected": len(analysis_report.design_patterns),
                    "anti_patterns_detected": len(analysis_report.anti_patterns),
                    "recommendations_count": len(analysis_report.recommendations),
                    "critical_recommendations": len(
                        [
                            r
                            for r in analysis_report.recommendations
                            if r.priority == "Critical"
                        ]
                    ),
                    "high_priority_recommendations": len(
                        [
                            r
                            for r in analysis_report.recommendations
                            if r.priority == "High"
                        ]
                    ),
                },
                "pydantic_ai_metadata": {
                    "model_used": FALLBACK_MODELS[0],
                    "structured_output": True,
                    "tools_available": 4,
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
                message=f"Analysis complete: {len(analysis_report.design_patterns)} patterns, "
                f"{len(analysis_report.recommendations)} recommendations",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Architectural analysis failed: {str(e)}"

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
        analysis_focus: str,
        pre_gathered_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Gather intelligence from context or MCP."""
        intelligence = {}

        # Use pre-gathered context if available
        if pre_gathered_context:
            for key, context_item in pre_gathered_context.items():
                context_type = context_item.get("type")
                if context_type == "rag":
                    intelligence[key] = context_item.get("content", {})
                elif context_type == "quality":
                    intelligence["code_quality"] = context_item.get("content", {})
                elif context_type == "pattern":
                    intelligence["quality_patterns"] = context_item.get("content", {})

        # Always assess the code if MCP is enabled
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

                # Quality patterns (best practices)
                patterns_result = await self.mcp_client.call_tool(
                    "get_quality_patterns", content=code, pattern_type="best_practices"
                )
                intelligence["quality_patterns"] = patterns_result

                # Anti-patterns detection
                anti_patterns_result = await self.mcp_client.call_tool(
                    "get_quality_patterns", content=code, pattern_type="anti_patterns"
                )
                intelligence["anti_patterns"] = anti_patterns_result

                # Design pattern intelligence if not pre-gathered
                if not pre_gathered_context or "design_patterns" not in intelligence:
                    pattern_intel = await self.mcp_client.perform_rag_query(
                        query=f"{language} design patterns architectural best practices {analysis_focus}",
                        context="architecture",
                        match_count=5,
                    )
                    intelligence["design_patterns"] = pattern_intel

            except Exception as e:
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_ERROR,
                    message=f"Intelligence gathering failed (continuing): {str(e)}",
                    level=TraceLevel.WARNING,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                )

        return intelligence

    def _build_analysis_prompt(
        self,
        task: AgentTask,
        code: str,
        file_path: str,
        language: str,
        analysis_focus: str,
    ) -> str:
        """Build detailed analysis prompt for LLM."""
        return f"""Perform comprehensive architectural and code quality analysis:

**File:** {file_path}
**Language:** {language}
**Analysis Focus:** {analysis_focus}

**Code to Analyze:**
```{language}
{code}
```

**Task Description:**
{task.description}

**Your Analysis Must Include:**

1. **Quality Metrics Assessment:**
   - Calculate overall quality score (0.0-1.0)
   - Assess maintainability index (0-100)
   - Evaluate complexity score
   - Measure ONEX architectural compliance
   - Estimate test coverage
   - Determine technical debt level

2. **Design Patterns Analysis:**
   - Identify all design patterns in use
   - Classify pattern types (Creational/Structural/Behavioral/Architectural)
   - Assign confidence scores to detections
   - Evaluate implementation quality
   - Suggest improvements for each pattern

3. **Anti-Patterns Detection:**
   - Detect code smells and anti-patterns
   - Assign severity levels (Critical/High/Medium/Low)
   - Identify refactoring difficulty
   - Recommend replacement patterns
   - List code smell indicators

4. **Improvement Recommendations:**
   - Generate prioritized recommendations
   - Categorize by type (Architecture/Quality/Performance/Security/Maintainability)
   - Provide implementation steps
   - Estimate effort levels
   - Identify dependencies between recommendations

5. **ONEX Compliance:**
   - Evaluate node type usage (Effect/Compute/Reducer/Orchestrator)
   - Check naming conventions compliance
   - Validate contract usage
   - Assess SOLID principles adherence

Use available tools to:
1. Get design pattern intelligence from knowledge base
2. Get code quality assessment data
3. Get ONEX architecture standards
4. Get anti-pattern detection results

Provide comprehensive, actionable analysis with evidence-based metrics and clear recommendations."""

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, "close"):
            await self.mcp_client.close()


# ============================================================================
# Example Usage
# ============================================================================


async def main():
    """Example usage of the architectural analyzer agent."""
    agent = ArchitecturalAnalyzerAgent()

    # Example code to analyze
    example_code = """
class UserManager:
    def __init__(self):
        self.users = []

    def add_user(self, name, email):
        user = {"name": name, "email": email}
        self.users.append(user)
        # Save to database
        with open("users.txt", "a") as f:
            f.write(f"{name},{email}\\n")
        # Send welcome email
        print(f"Welcome email sent to {email}")
        return user

    def get_user(self, email):
        for user in self.users:
            if user["email"] == email:
                return user
        return None
"""

    task = AgentTask(
        task_id="example-analysis-001",
        description="Analyze UserManager class for architectural quality",
        agent_name="agent-analyzer",
        input_data={
            "code": example_code,
            "file_path": "user_manager.py",
            "language": "python",
            "analysis_focus": "comprehensive",
        },
    )

    result = await agent.execute(task)

    print("\n" + "=" * 80)
    print("ARCHITECTURAL ANALYSIS REPORT")
    print("=" * 80)

    if result.success:
        output = result.output_data
        print(f"\nFile: {output['file_analyzed']}")
        print(f"Analysis Type: {output['analysis_type']}")
        print(f"\n{output['analysis_summary']}\n")

        print("\n--- Quality Metrics ---")
        metrics = output["quality_metrics"]
        print(f"Overall Quality: {metrics['overall_quality_score']:.2f}")
        print(f"Maintainability: {metrics['maintainability_index']:.2f}")
        print(f"ONEX Compliance: {metrics['architectural_compliance']:.2f}")
        print(f"Technical Debt: {metrics['technical_debt_level']}")

        print(f"\n--- Design Patterns ({len(output['design_patterns'])}) ---")
        for pattern in output["design_patterns"][:3]:
            print(f"- {pattern['pattern_name']} ({pattern['pattern_type']})")
            print(f"  Confidence: {pattern['confidence_score']:.2f}")
            print(f"  Quality: {pattern['implementation_quality']}")

        print(f"\n--- Anti-Patterns ({len(output['anti_patterns'])}) ---")
        for anti in output["anti_patterns"][:3]:
            print(f"- {anti['anti_pattern_name']} [{anti['severity']}]")
            print(f"  Location: {anti['location']}")

        print(
            f"\n--- Top Recommendations ({output['statistics']['critical_recommendations']} critical) ---"
        )
        for rec in output["recommendations"][:5]:
            print(f"- [{rec['priority']}] {rec['title']}")
            print(f"  Category: {rec['category']}")
            print(f"  Effort: {rec['estimated_effort']}")

        print("\n--- Architecture Assessment ---")
        print(output["architecture_assessment"])

        print("\n--- ONEX Compliance ---")
        print(output["onex_compliance_notes"])

        print("\n--- Statistics ---")
        stats = output["statistics"]
        print(f"Patterns Detected: {stats['patterns_detected']}")
        print(f"Anti-Patterns: {stats['anti_patterns_detected']}")
        print(f"Total Recommendations: {stats['recommendations_count']}")
        print(
            f"Critical: {stats['critical_recommendations']}, High: {stats['high_priority_recommendations']}"
        )

        print(f"\nExecution Time: {result.execution_time_ms:.2f}ms")
    else:
        print(f"Analysis failed: {result.error}")

    await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
