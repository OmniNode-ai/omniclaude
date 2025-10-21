"""
Pydantic AI-based Refactoring Agent

Analyzes and improves code quality, structure, and maintainability.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_model import AgentConfig, AgentResult, AgentTask
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
    pass


# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================


class RefactoringChange(BaseModel):
    """A single refactoring change recommendation."""

    change_type: str = Field(
        description="Type of refactoring: extract_method, rename, simplify, optimize, etc."
    )
    location: str = Field(
        description="Code location (function/class name, line numbers)"
    )
    current_code: str = Field(description="Current code snippet")
    refactored_code: str = Field(description="Improved code")
    rationale: str = Field(description="Why this refactoring improves the code")
    impact: str = Field(description="Impact level: low, medium, high")
    category: str = Field(
        description="Category: readability, performance, maintainability, design"
    )


class RefactoringPlan(BaseModel):
    """Structured output for code refactoring analysis and recommendations."""

    file_path: str = Field(description="Path to file being refactored")
    quality_score: float = Field(description="Current code quality score (0-100)")

    # Refactoring changes
    changes: List[RefactoringChange] = Field(
        description="List of refactoring recommendations"
    )

    # Analysis
    code_smells: List[str] = Field(description="Detected code smells")
    complexity_issues: List[str] = Field(description="Complexity issues identified")
    design_patterns_suggested: List[str] = Field(
        default_factory=list, description="Design patterns that could improve the code"
    )

    # Summary
    overall_assessment: str = Field(description="Overall code quality assessment")
    priority_actions: List[str] = Field(description="High-priority refactoring actions")
    estimated_improvement: int = Field(
        description="Estimated quality score improvement (%)"
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


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

REFACTORING_SYSTEM_PROMPT = """You are an expert code refactoring agent specializing in Python code quality and design improvements.

**Your Role:**
1. Analyze code for quality, readability, and maintainability issues
2. Identify code smells and anti-patterns
3. Suggest specific refactoring improvements
4. Prioritize changes by impact and effort
5. Preserve behavior while improving structure

**Refactoring Categories:**

1. **Readability**:
   - Improve naming (variables, functions, classes)
   - Simplify complex expressions
   - Add/improve documentation
   - Format consistently

2. **Maintainability**:
   - Extract methods/functions (reduce length)
   - Remove duplication (DRY principle)
   - Simplify conditional logic
   - Reduce coupling

3. **Performance**:
   - Optimize algorithms
   - Reduce unnecessary computations
   - Improve data structures
   - Remove bottlenecks

4. **Design**:
   - Apply design patterns
   - Improve abstraction
   - Enhance modularity
   - Follow SOLID principles

**Common Code Smells**:
- Long methods (>20 lines)
- Large classes (>200 lines)
- Long parameter lists (>3 parameters)
- Duplicated code
- Complex conditional logic
- God objects
- Feature envy
- Inappropriate intimacy

**Refactoring Principles**:
- Make small, incremental changes
- Preserve existing behavior
- Add tests before refactoring
- One refactoring at a time
- Prioritize high-impact changes

**Your Task:**
Analyze code thoroughly and provide actionable refactoring recommendations with clear before/after examples."""

# Create the Pydantic AI agent
refactoring_agent = Agent[AgentDeps, RefactoringPlan](
    "google-gla:gemini-2.5-flash",
    deps_type=AgentDeps,
    output_type=RefactoringPlan,
    system_prompt=REFACTORING_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@refactoring_agent.tool
async def detect_code_smells(ctx: RunContext[AgentDeps], code_snippet: str) -> str:
    """Detect code smells in given code snippet.

    Args:
        code_snippet: Code to analyze

    Returns: List of detected code smells
    """
    smells = []

    lines = code_snippet.split("\n")

    # Long method
    if len(lines) > 20:
        smells.append(
            f"⚠️ Long method ({len(lines)} lines) - Consider extracting smaller methods"
        )

    # Complex nesting
    max_indent = max(
        (len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0
    )
    if max_indent > 12:
        smells.append(
            f"⚠️ Deep nesting (indent level {max_indent//4}) - Simplify control flow"
        )

    # Long parameter list
    if "def " in code_snippet:
        for line in lines:
            if "def " in line and line.count(",") > 3:
                smells.append(
                    "⚠️ Long parameter list - Consider parameter object pattern"
                )
                break

    if not smells:
        smells.append("✅ No obvious code smells detected")

    return "\n".join(smells)


@refactoring_agent.tool
async def suggest_design_pattern(
    ctx: RunContext[AgentDeps], problem_description: str
) -> str:
    """Suggest appropriate design pattern for given problem.

    Args:
        problem_description: Description of the code structure/problem

    Returns: Design pattern suggestion
    """
    pattern_keywords = {
        "factory": ["create", "instantiate", "different types"],
        "strategy": ["different algorithms", "behavior", "switch"],
        "observer": ["notify", "event", "listener", "subscribe"],
        "decorator": ["add behavior", "extend", "wrap"],
        "singleton": ["one instance", "global", "shared"],
        "adapter": ["interface", "incompatible", "wrapper"],
    }

    desc_lower = problem_description.lower()

    for pattern, keywords in pattern_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            return f"💡 Consider {pattern.title()} Pattern - Matches keywords: {', '.join(k for k in keywords if k in desc_lower)}"

    return "💡 Standard refactoring techniques may be sufficient"


@refactoring_agent.tool
async def calculate_complexity(ctx: RunContext[AgentDeps], code_snippet: str) -> str:
    """Estimate cyclomatic complexity of code.

    Args:
        code_snippet: Code to analyze

    Returns: Complexity assessment
    """
    # Simple heuristic: count decision points
    decision_keywords = ["if", "elif", "for", "while", "and", "or", "except"]
    complexity = 1  # Base complexity

    code_lower = code_snippet.lower()
    for keyword in decision_keywords:
        complexity += code_lower.count(f" {keyword} ")
        complexity += code_lower.count(f"\n{keyword} ")

    if complexity <= 5:
        return f"✅ Low complexity ({complexity}) - Code is easy to understand"
    elif complexity <= 10:
        return f"⚠️ Moderate complexity ({complexity}) - Consider simplification"
    else:
        return f"🔴 High complexity ({complexity}) - Refactoring recommended"


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


class RefactoringAgent:
    """
    Pydantic AI-based refactoring agent.

    Analyzes code quality and suggests improvements.
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-refactoring")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute refactoring analysis using Pydantic AI agent.

        Args:
            task: Task containing refactoring requirements

        Returns:
            AgentResult with refactoring plan
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
            file_path = task.input_data.get("file_path", "unknown.py")
            code_content = task.input_data.get("code_content", "")
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Analyzing code for refactoring: {file_path}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Gather intelligence
            intelligence = await self._gather_intelligence(task, pre_gathered_context)

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                mcp_client=self.mcp_client,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
                intelligence=intelligence,
            )

            # Build refactoring prompt
            prompt = self._build_refactoring_prompt(task, file_path, code_content)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI refactoring agent",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            result = await refactoring_agent.run(prompt, deps=deps)
            refactoring_plan: RefactoringPlan = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "refactoring_plan": refactoring_plan.model_dump(),
                "file_path": file_path,
                "quality_score": refactoring_plan.quality_score,
                "num_changes": len(refactoring_plan.changes),
                "priority_actions": refactoring_plan.priority_actions,
                "estimated_improvement": refactoring_plan.estimated_improvement,
                "code_smells": refactoring_plan.code_smells,
                "intelligence_gathered": intelligence,
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
                message=f"Refactoring analysis complete: {len(refactoring_plan.changes)} suggestions",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Refactoring analysis failed: {str(e)}"

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
            for key, context_item in pre_gathered_context.items():
                if "refactor" in key.lower() or "quality" in key.lower():
                    intelligence["quality_patterns"] = context_item.get("content", {})
        elif self.config.archon_mcp_enabled:
            try:
                quality_intel = await self.mcp_client.perform_rag_query(
                    query="code refactoring patterns clean code principles",
                    context="quality",
                    match_count=3,
                )
                intelligence["quality_patterns"] = quality_intel
            except Exception as e:
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_ERROR,
                    message=f"Intelligence gathering failed (continuing): {str(e)}",
                    level=TraceLevel.WARNING,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id,
                )

        return intelligence

    def _build_refactoring_prompt(
        self, task: AgentTask, file_path: str, code_content: str
    ) -> str:
        """Build detailed refactoring prompt for LLM."""
        return f"""Analyze the following code and provide comprehensive refactoring recommendations:

**File Path:** {file_path}
**Task Description:** {task.description}

**Code to Analyze:**
```python
{code_content[:2000]}  # First 2000 chars
```

**Analysis Goals:**
- Identify code smells and anti-patterns
- Suggest specific refactoring improvements
- Provide before/after code examples
- Prioritize changes by impact
- Estimate quality improvement

**Additional Context:**
{task.input_data.get('additional_context', 'None provided')}

Use the available tools to:
1. Detect code smells
2. Suggest appropriate design patterns
3. Calculate code complexity

Generate a comprehensive refactoring plan with actionable recommendations."""

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, "close"):
            await self.mcp_client.close()
