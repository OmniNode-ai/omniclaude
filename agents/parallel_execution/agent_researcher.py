"""
Pydantic AI-based Researcher Agent

Gathers documentation, examples, and implementation patterns.
"""

import asyncio
import os
import time
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from agent_model import AgentConfig, AgentTask, AgentResult
from mcp_client import ArchonMCPClient
from trace_logger import get_trace_logger, TraceEventType, TraceLevel

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

class CodeExample(BaseModel):
    """A code example from research."""

    example_type: str = Field(description="Type: implementation, pattern, usage, integration")
    source: str = Field(description="Source of example (documentation, library, project)")
    code_snippet: str = Field(description="The code example")
    explanation: str = Field(description="What this example demonstrates")
    relevance_score: float = Field(description="Relevance to task (0-1)")


class DocumentationLink(BaseModel):
    """A relevant documentation reference."""

    title: str = Field(description="Documentation title/topic")
    source: str = Field(description="Source (official docs, tutorial, blog, etc.)")
    url: Optional[str] = Field(default=None, description="URL if available")
    summary: str = Field(description="Key points from this documentation")
    sections_relevant: List[str] = Field(description="Specific relevant sections")


class ResearchFindings(BaseModel):
    """Structured output for research and documentation gathering."""

    research_topic: str = Field(description="Main research topic/question")

    # Findings
    code_examples: List[CodeExample] = Field(description="Relevant code examples found")
    documentation: List[DocumentationLink] = Field(description="Relevant documentation references")

    # Patterns and approaches
    recommended_approach: str = Field(description="Recommended implementation approach based on research")
    alternative_approaches: List[str] = Field(default_factory=list, description="Alternative approaches considered")
    best_practices: List[str] = Field(description="Best practices identified")
    gotchas: List[str] = Field(default_factory=list, description="Common pitfalls and gotchas")

    # Dependencies and tools
    libraries_recommended: List[str] = Field(default_factory=list, description="Recommended libraries/tools")
    dependencies_needed: List[str] = Field(default_factory=list, description="Required dependencies")

    # Summary
    research_summary: str = Field(description="Overall research summary")
    confidence_score: float = Field(description="Confidence in findings (0-1)")
    additional_research_needed: List[str] = Field(default_factory=list, description="Areas needing more research")


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

RESEARCHER_SYSTEM_PROMPT = """You are an expert technical researcher specializing in finding implementation patterns, documentation, and code examples.

**Your Role:**
1. Research technical topics thoroughly
2. Find relevant code examples and patterns
3. Locate authoritative documentation
4. Identify best practices and gotchas
5. Synthesize findings into actionable recommendations

**Research Strategy:**

1. **Documentation Sources**:
   - Official documentation (primary source)
   - API references and guides
   - Community tutorials and blogs
   - Stack Overflow discussions
   - GitHub repositories and examples

2. **Code Examples**:
   - Official examples from documentation
   - Open-source implementations
   - Common usage patterns
   - Integration examples
   - Test cases as examples

3. **Best Practices**:
   - Performance considerations
   - Security implications
   - Scalability patterns
   - Common pitfalls
   - Migration strategies

4. **Quality Assessment**:
   - Source authority (official > community)
   - Recency (newer > older)
   - Completeness (full examples > fragments)
   - Clarity (well-explained > cryptic)

**Research Process**:
1. Understand the specific question/need
2. Identify key technologies/concepts involved
3. Search for authoritative sources
4. Extract relevant examples and patterns
5. Synthesize into actionable recommendations

**Output Quality**:
- Provide working code examples when possible
- Include source attribution
- Explain rationale for recommendations
- Note any uncertainties or gaps
- Suggest related topics for further research

**Your Task:**
Conduct thorough research and provide comprehensive, actionable findings."""

# Create the Pydantic AI agent
researcher_agent = Agent[AgentDeps, ResearchFindings](
    'google-gla:gemini-2.5-flash',
    deps_type=AgentDeps,
    output_type=ResearchFindings,
    system_prompt=RESEARCHER_SYSTEM_PROMPT
)


# ============================================================================
# Agent Tools
# ============================================================================

@researcher_agent.tool
async def search_archon_intelligence(ctx: RunContext[AgentDeps], query: str, context: str = "general") -> str:
    """Search Archon MCP intelligence for patterns and examples.

    Args:
        query: Search query
        context: Context category (general, architecture, implementation, etc.)

    Returns: Search results summary
    """
    deps = ctx.deps
    try:
        results = await deps.mcp_client.perform_rag_query(
            query=query,
            context=context,
            match_count=5
        )

        if results and isinstance(results, dict):
            summary_parts = [f"📚 Found {len(results.get('results', []))} relevant items"]

            # Extract key findings
            for i, item in enumerate(results.get('results', [])[:3], 1):
                if isinstance(item, dict):
                    title = item.get('title', item.get('source', f'Result {i}'))
                    summary_parts.append(f"{i}. {title}")

            return "\n".join(summary_parts)
        else:
            return "✅ Search completed (limited results)"

    except Exception as e:
        return f"⚠️ Search failed: {str(e)}"


@researcher_agent.tool
async def identify_key_technologies(ctx: RunContext[AgentDeps], topic: str) -> str:
    """Identify key technologies and concepts for a topic.

    Args:
        topic: Research topic

    Returns: Key technologies identified
    """
    tech_keywords = {
        "web": ["http", "rest", "api", "fastapi", "flask", "django"],
        "database": ["sql", "postgres", "mongodb", "redis", "orm"],
        "async": ["asyncio", "async/await", "concurrent", "parallel"],
        "testing": ["pytest", "unittest", "mock", "fixture"],
        "data": ["pandas", "numpy", "dataframe", "analysis"],
        "ml": ["scikit-learn", "tensorflow", "pytorch", "model"]
    }

    topic_lower = topic.lower()
    identified = []

    for category, keywords in tech_keywords.items():
        if any(kw in topic_lower for kw in keywords):
            identified.append(f"{category}: {', '.join(k for k in keywords if k in topic_lower)}")

    if identified:
        return "🔍 Key technologies identified:\n" + "\n".join(f"  - {tech}" for tech in identified)
    else:
        return "💡 General programming topic - no specific technology stack identified"


@researcher_agent.tool
async def suggest_documentation_sources(ctx: RunContext[AgentDeps], library_or_topic: str) -> str:
    """Suggest where to find authoritative documentation.

    Args:
        library_or_topic: Library name or topic

    Returns: Documentation source suggestions
    """
    common_sources = {
        "python": "https://docs.python.org/3/",
        "fastapi": "https://fastapi.tiangolo.com/",
        "pytest": "https://docs.pytest.org/",
        "pydantic": "https://docs.pydantic.dev/",
        "sqlalchemy": "https://docs.sqlalchemy.org/",
        "asyncio": "https://docs.python.org/3/library/asyncio.html"
    }

    lib_lower = library_or_topic.lower()

    # Direct match
    for lib, url in common_sources.items():
        if lib in lib_lower:
            return f"📖 Official documentation: {url}"

    # General suggestions
    return f"""📖 Documentation sources to check:
  1. Official project documentation
  2. PyPI project page
  3. GitHub repository README
  4. Read the Docs
  5. API reference docs"""


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================

class ResearcherAgent:
    """
    Pydantic AI-based researcher agent.

    Gathers documentation, examples, and implementation patterns.
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-research")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute research using Pydantic AI agent.

        Args:
            task: Task containing research requirements

        Returns:
            AgentResult with research findings
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"using_pydantic_ai": True}
        )

        try:
            # Extract task inputs
            research_topic = task.input_data.get("research_topic", task.description)
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Researching: {research_topic}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            # Gather intelligence
            intelligence = await self._gather_intelligence(task, pre_gathered_context, research_topic)

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                mcp_client=self.mcp_client,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
                intelligence=intelligence
            )

            # Build research prompt
            prompt = self._build_research_prompt(task, research_topic)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI researcher agent",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            result = await researcher_agent.run(prompt, deps=deps)
            findings: ResearchFindings = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "research_findings": findings.model_dump(),
                "research_topic": research_topic,
                "num_examples": len(findings.code_examples),
                "num_documentation_links": len(findings.documentation),
                "recommended_approach": findings.recommended_approach,
                "confidence_score": findings.confidence_score,
                "libraries_recommended": findings.libraries_recommended,
                "best_practices": findings.best_practices,
                "intelligence_gathered": intelligence,
                "pydantic_ai_metadata": {
                    "model_used": "gemini-2.5-flash",
                    "structured_output": True,
                    "tools_available": 3
                }
            }

            # Create result
            agent_result = AgentResult(
                task_id=task.task_id,
                agent_name=self.config.agent_name,
                success=True,
                output_data=output_data,
                execution_time_ms=execution_time_ms,
                trace_id=self._current_trace_id
            )

            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id,
                status="completed",
                result=agent_result.model_dump()
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_COMPLETED,
                message=f"Research complete: {len(findings.code_examples)} examples, {len(findings.documentation)} docs",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Research failed: {str(e)}"

            await self.trace_logger.end_agent_trace(
                trace_id=self._current_trace_id,
                status="failed",
                error=error_msg
            )

            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_ERROR,
                message=error_msg,
                level=TraceLevel.ERROR,
                agent_name=self.config.agent_name,
                task_id=task.task_id
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
        self, task: AgentTask, pre_gathered_context: Dict[str, Any], research_topic: str
    ) -> Dict[str, Any]:
        """Gather intelligence from context or MCP."""
        intelligence = {}

        if pre_gathered_context:
            intelligence["pre_gathered"] = pre_gathered_context
        elif self.config.archon_mcp_enabled:
            try:
                # Search for relevant patterns and examples
                research_intel = await self.mcp_client.perform_rag_query(
                    query=research_topic,
                    context="research",
                    match_count=5
                )
                intelligence["rag_results"] = research_intel
            except Exception as e:
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_ERROR,
                    message=f"Intelligence gathering failed (continuing): {str(e)}",
                    level=TraceLevel.WARNING,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id
                )

        return intelligence

    def _build_research_prompt(self, task: AgentTask, research_topic: str) -> str:
        """Build detailed research prompt for LLM."""
        return f"""Conduct comprehensive research on the following topic:

**Research Topic:** {research_topic}
**Task Description:** {task.description}

**Research Goals:**
- Find relevant code examples and implementation patterns
- Locate authoritative documentation
- Identify best practices and common pitfalls
- Recommend optimal approach
- Suggest libraries and tools

**Specific Questions:**
{task.input_data.get('specific_questions', 'General research on topic')}

**Additional Context:**
{task.input_data.get('additional_context', 'None provided')}

Use the available tools to:
1. Search Archon intelligence for patterns
2. Identify key technologies involved
3. Suggest documentation sources

Provide comprehensive research findings with practical examples and recommendations."""

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, 'close'):
            await self.mcp_client.close()
