"""
Pydantic AI-based Task Breakdown Agent (Architect)

Breaks down user prompts into parallel subtasks for distributed execution.
Architecture-independent - works for any project type.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_model import AgentConfig, AgentResult, AgentTask
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


class SubTask(BaseModel):
    """A single subtask in the breakdown."""

    task_id: str = Field(
        description="Unique identifier for this subtask (e.g., 'task_1', 'task_2')"
    )
    description: str = Field(
        description="Clear description of what this subtask should accomplish"
    )
    agent: str = Field(
        description="Which agent handles this task (e.g., 'coder', 'analyzer', 'validator')"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="List of task_ids this task depends on (empty if no dependencies)",
    )
    input_data: Dict[str, Any] = Field(
        default_factory=dict, description="Input data/context for this subtask"
    )


class TaskBreakdown(BaseModel):
    """Structured output for task breakdown and execution planning."""

    subtasks: List[SubTask] = Field(description="List of subtasks to execute")
    execution_order: str = Field(
        description="Execution strategy: 'parallel' if tasks can run concurrently, 'sequential' if they must run in order"
    )
    reasoning: str = Field(
        description="Explanation of how tasks were broken down and why"
    )


# ============================================================================
# Dependencies for Pydantic AI Agent
# ============================================================================


@dataclass
class AgentDeps:
    """Dependencies passed to agent tools."""

    task: AgentTask
    config: AgentConfig
    trace_logger: Any
    trace_id: Optional[str]


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

# System prompt for task breakdown
ARCHITECT_SYSTEM_PROMPT = """You are an expert task architect that breaks down user requests into parallel subtasks.

**Your Role:**
1. Analyze the user's request to understand the goal
2. Break it down into clear, independent subtasks when possible
3. Identify dependencies between tasks
4. Determine optimal execution strategy (parallel vs sequential)
5. Assign appropriate agents to handle each subtask

**Available Agents:**
- **coder**: Generates code, implements features, creates files
- **analyzer**: Analyzes code, reviews patterns, provides insights
- **validator**: Tests code, validates quality, checks compliance
- **researcher**: Gathers documentation, searches for examples
- **debugger**: Diagnoses issues, identifies root causes

**Task Breakdown Guidelines:**
- Create focused, single-purpose subtasks
- Maximize parallelization when tasks are independent
- Use 'depends_on' to enforce ordering when needed
- Provide clear descriptions and necessary context
- Keep subtasks atomic and testable

**Execution Strategies:**
- **parallel**: Tasks can run simultaneously (no dependencies or only initial dependencies)
- **sequential**: Tasks must run in strict order (heavy interdependencies)

**Example Breakdown:**
User Request: "Create a FastAPI endpoint with database integration"

Subtasks:
1. task_1: Design database schema (agent: analyzer)
2. task_2: Generate database models (agent: coder, depends_on: [task_1])
3. task_3: Generate API endpoint code (agent: coder, depends_on: [task_2])
4. task_4: Generate tests (agent: coder, depends_on: [task_3])
5. task_5: Validate implementation (agent: validator, depends_on: [task_4])

Execution: sequential (tasks have clear dependencies)

**Your Task:**
Break down the user's request into optimal subtasks with clear responsibilities."""

# Model configuration
MODEL_NAME = "google-gla:gemini-2.5-flash"  # Latest Gemini Flash model

# Create the Pydantic AI agent
task_architect_agent = Agent[AgentDeps, TaskBreakdown](
    MODEL_NAME,
    deps_type=AgentDeps,
    output_type=TaskBreakdown,
    system_prompt=ARCHITECT_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@task_architect_agent.tool
async def analyze_task_complexity(
    ctx: RunContext[AgentDeps], task_description: str
) -> str:
    """Analyze the complexity of a task to help determine breakdown strategy.

    Args:
        task_description: Description of the task to analyze

    Returns: Complexity assessment with recommendations
    """
    # Simple heuristic-based complexity analysis
    indicators = {
        "simple": ["create", "add", "simple", "basic", "single"],
        "moderate": ["integrate", "implement", "refactor", "multiple", "several"],
        "complex": [
            "architecture",
            "system",
            "distributed",
            "parallel",
            "many",
            "complex",
        ],
    }

    task_lower = task_description.lower()
    complexity_score = 0

    for keyword in indicators["complex"]:
        if keyword in task_lower:
            complexity_score += 2

    for keyword in indicators["moderate"]:
        if keyword in task_lower:
            complexity_score += 1

    if complexity_score == 0:
        return "✅ Simple task - May be handled by single agent or 2-3 simple subtasks"
    elif complexity_score <= 2:
        return "⚠️ Moderate complexity - Break into 3-5 focused subtasks"
    else:
        return "🔴 Complex task - Break into 5+ subtasks with clear dependencies"


@task_architect_agent.tool
async def suggest_agent_for_task(ctx: RunContext[AgentDeps], task_type: str) -> str:
    """Suggest the best agent for a specific type of task.

    Args:
        task_type: Type of work needed (e.g., 'code generation', 'analysis', 'testing')

    Returns: Recommended agent with reasoning
    """
    agent_mapping = {
        "code": "coder - Generates implementation code, creates files",
        "implementation": "coder - Implements features and solutions",
        "generate": "coder - Creates new code artifacts",
        "create": "coder - Creates new files and implementations",
        "analyze": "analyzer - Reviews code and provides insights",
        "review": "analyzer - Analyzes patterns and quality",
        "design": "analyzer - Designs architecture and approaches",
        "test": "validator - Creates and runs tests",
        "validate": "validator - Validates quality and correctness",
        "verify": "validator - Verifies implementation meets requirements",
        "research": "researcher - Gathers documentation and examples",
        "document": "researcher - Finds and organizes documentation",
        "debug": "debugger - Diagnoses and fixes issues",
        "fix": "debugger - Identifies and resolves problems",
    }

    task_lower = task_type.lower()
    for keyword, recommendation in agent_mapping.items():
        if keyword in task_lower:
            return f"✅ Recommended: {recommendation}"

    return "💡 Default: coder - General-purpose implementation agent"


@task_architect_agent.tool
async def check_task_dependencies(ctx: RunContext[AgentDeps], task_list: str) -> str:
    """Check if tasks have dependencies that require sequential execution.

    Args:
        task_list: Comma-separated list of task descriptions

    Returns: Dependency analysis and execution recommendation
    """
    dependency_keywords = [
        "then",
        "after",
        "before",
        "depends",
        "requires",
        "needs",
        "first",
        "second",
        "next",
        "following",
        "previous",
    ]

    tasks_lower = task_list.lower()
    has_dependencies = any(keyword in tasks_lower for keyword in dependency_keywords)

    if has_dependencies:
        return "🔗 Dependencies detected - Recommend sequential or mixed execution with explicit depends_on relationships"
    else:
        return "✅ No obvious dependencies - Tasks can likely run in parallel"


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


class ArchitectAgent:
    """
    Pydantic AI-based task breakdown agent (architect).

    Breaks down complex user requests into parallel subtasks for distributed execution.
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-architect")
        self.trace_logger = get_trace_logger()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute task breakdown using Pydantic AI agent.

        Args:
            task: Task containing the user request to break down

        Returns:
            AgentResult with breakdown plan
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"using_pydantic_ai": True},
        )

        try:
            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Breaking down task: {task.description[:100]}...",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
            )

            # Build breakdown prompt
            prompt = self._build_breakdown_prompt(task)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI task architect",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            result = await task_architect_agent.run(prompt, deps=deps)
            breakdown: TaskBreakdown = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "subtasks": [subtask.model_dump() for subtask in breakdown.subtasks],
                "execution_order": breakdown.execution_order,
                "reasoning": breakdown.reasoning,
                "num_subtasks": len(breakdown.subtasks),
                "parallel_capable": breakdown.execution_order == "parallel",
                "pydantic_ai_metadata": {
                    "model_used": MODEL_NAME,
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
                message=f"Task breakdown complete: {len(breakdown.subtasks)} subtasks ({breakdown.execution_order})",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Task breakdown failed: {str(e)}"

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

    def _build_breakdown_prompt(self, task: AgentTask) -> str:
        """Build detailed breakdown prompt for LLM."""
        user_request = task.input_data.get("user_request", task.description)
        additional_context = task.input_data.get("additional_context", "")

        prompt_parts = [
            f"**User Request:** {user_request}",
            "",
            "**Your Task:**",
            "1. Analyze this request carefully",
            "2. Break it down into focused subtasks",
            "3. Identify dependencies between tasks",
            "4. Assign appropriate agents to each subtask",
            "5. Determine optimal execution strategy",
            "",
        ]

        if additional_context:
            prompt_parts.extend(["**Additional Context:**", additional_context, ""])

        prompt_parts.extend(
            [
                "**Requirements:**",
                "- Create clear, single-purpose subtasks",
                "- Maximize parallelization when possible",
                "- Use explicit depends_on relationships",
                "- Provide necessary context in input_data",
                "- Keep subtasks atomic and testable",
                "",
                "Use the available tools to:",
                "1. Analyze task complexity",
                "2. Suggest appropriate agents",
                "3. Check for dependencies",
                "",
                "Generate a complete task breakdown plan.",
            ]
        )

        return "\n".join(prompt_parts)

    async def cleanup(self):
        """Cleanup resources."""
        # No external resources to cleanup in architect agent
        pass
