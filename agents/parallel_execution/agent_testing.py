"""
Pydantic AI-based Testing Agent

Generates comprehensive test suites (pytest, unit tests, integration tests).
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

class TestCase(BaseModel):
    """A single test case."""

    test_name: str = Field(description="Descriptive test function name (test_*)")
    test_type: str = Field(description="Type of test: unit, integration, or functional")
    test_code: str = Field(description="Complete test function implementation")
    fixtures_needed: List[str] = Field(default_factory=list, description="Pytest fixtures required")
    mocks_needed: List[str] = Field(default_factory=list, description="Mocks/patches needed")
    assertions: int = Field(description="Number of assertions in the test")


class TestSuite(BaseModel):
    """Structured output for comprehensive test generation."""

    test_file_name: str = Field(description="Test file name (test_*.py)")
    test_cases: List[TestCase] = Field(description="List of test cases")

    # Setup and teardown
    fixtures: List[str] = Field(default_factory=list, description="Pytest fixture implementations")
    setup_code: str = Field(default="", description="Module-level setup code")

    # Dependencies
    imports: List[str] = Field(description="Required import statements")
    test_dependencies: List[str] = Field(default_factory=list, description="Test-specific dependencies (pytest-mock, etc)")

    # Coverage and quality
    coverage_target: int = Field(default=80, description="Target code coverage percentage")
    test_strategy: str = Field(description="Testing strategy and rationale")


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

# System prompt for comprehensive test generation
TESTING_SYSTEM_PROMPT = """You are an expert test generation agent specializing in pytest and Python testing best practices.

**Your Role:**
1. Generate comprehensive test suites for Python code
2. Follow pytest best practices and conventions
3. Ensure high code coverage (target: 80%+)
4. Create maintainable, readable test code
5. Use appropriate fixtures, mocks, and test strategies

**Testing Best Practices:**

1. **Test Structure (AAA Pattern)**:
   - Arrange: Setup test data and conditions
   - Act: Execute the code being tested
   - Assert: Verify expected outcomes

2. **Test Naming**:
   - Descriptive function names: `test_<what>_<condition>_<expected>`
   - Example: `test_user_login_with_invalid_password_returns_error`

3. **Pytest Fixtures**:
   - Use fixtures for reusable setup/teardown
   - Scope appropriately: function, class, module, session
   - Example: `@pytest.fixture(scope="function")`

4. **Mocking**:
   - Mock external dependencies (APIs, databases, file systems)
   - Use pytest-mock or unittest.mock
   - Clear mock specifications and assertions

5. **Parametrization**:
   - Use `@pytest.mark.parametrize` for multiple test cases
   - Test edge cases, boundary conditions, and error paths

6. **Test Types**:
   - **Unit Tests**: Test individual functions/methods in isolation
   - **Integration Tests**: Test interaction between components
   - **Functional Tests**: Test end-to-end workflows

**Coverage Strategy**:
- Test happy path (main use case)
- Test error paths and exceptions
- Test edge cases and boundary conditions
- Test validation logic
- Test state changes and side effects

**Code Quality**:
- Clear, descriptive assertions
- Minimal test duplication
- Fast execution (mock expensive operations)
- Independent tests (no test interdependencies)

**Your Task:**
Generate production-quality pytest test suites that thoroughly validate code correctness."""

# Create the Pydantic AI agent
testing_agent = Agent[AgentDeps, TestSuite](
    'google-gla:gemini-2.5-flash',  # Latest Gemini Flash model
    deps_type=AgentDeps,
    output_type=TestSuite,
    system_prompt=TESTING_SYSTEM_PROMPT
)


# ============================================================================
# Agent Tools
# ============================================================================

@testing_agent.tool
async def analyze_code_for_testing(ctx: RunContext[AgentDeps], code_description: str) -> str:
    """Analyze code to determine appropriate testing strategy.

    Args:
        code_description: Description of the code to be tested

    Returns: Testing strategy recommendations
    """
    strategy_indicators = {
        "unit": ["function", "method", "class", "utility", "helper"],
        "integration": ["api", "database", "service", "integration", "external"],
        "functional": ["workflow", "process", "end-to-end", "e2e", "user"]
    }

    desc_lower = code_description.lower()
    recommended_types = []

    for test_type, keywords in strategy_indicators.items():
        if any(keyword in desc_lower for keyword in keywords):
            recommended_types.append(test_type)

    if not recommended_types:
        recommended_types = ["unit"]  # Default to unit tests

    return f"✅ Recommended test types: {', '.join(recommended_types)}\n" \
           f"Strategy: Focus on {recommended_types[0]} testing with complementary {', '.join(recommended_types[1:])} tests"


@testing_agent.tool
async def suggest_test_cases(ctx: RunContext[AgentDeps], functionality: str) -> str:
    """Suggest specific test cases for given functionality.

    Args:
        functionality: Description of functionality to test

    Returns: List of suggested test cases
    """
    test_case_templates = [
        "test_<functionality>_with_valid_input_succeeds",
        "test_<functionality>_with_invalid_input_raises_error",
        "test_<functionality>_with_edge_case_handles_correctly",
        "test_<functionality>_with_empty_input_handles_correctly",
        "test_<functionality>_with_none_input_handles_correctly"
    ]

    func_slug = functionality.lower().replace(" ", "_")[:30]
    suggested = [template.replace("<functionality>", func_slug) for template in test_case_templates]

    return "💡 Suggested test cases:\n" + "\n".join(f"  - {tc}" for tc in suggested)


@testing_agent.tool
async def get_pytest_fixtures(ctx: RunContext[AgentDeps]) -> str:
    """Get common pytest fixture patterns.

    Returns: Example fixture implementations
    """
    return """
📦 Common Pytest Fixtures:

```python
@pytest.fixture
def sample_data():
    '''Provide test data.'''
    return {"key": "value"}

@pytest.fixture
def mock_database():
    '''Mock database connection.'''
    db = Mock()
    db.query.return_value = []
    return db

@pytest.fixture
def temp_file(tmp_path):
    '''Create temporary test file.'''
    file_path = tmp_path / "test.txt"
    file_path.write_text("test content")
    return file_path

@pytest.fixture(scope="module")
def api_client():
    '''Create API client for tests.'''
    client = TestClient(app)
    yield client
    # Cleanup if needed
```
"""


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================

class TestingAgent:
    """
    Pydantic AI-based testing agent.

    Generates comprehensive pytest test suites with intelligent coverage strategies.
    """

    def __init__(self):
        self.config = AgentConfig.load("agent-testing")
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: Optional[str] = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute test generation using Pydantic AI agent.

        Args:
            task: Task containing test generation requirements

        Returns:
            AgentResult with generated test suite
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
            target_file = task.input_data.get("target_file", "unknown.py")
            requirements = task.input_data.get("requirements", task.description)
            pre_gathered_context = task.input_data.get("pre_gathered_context", {})

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Generating tests for: {target_file}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
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
                intelligence=intelligence
            )

            # Build generation prompt
            prompt = self._build_testing_prompt(task, target_file, requirements)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI testing agent",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            result = await testing_agent.run(prompt, deps=deps)
            test_suite: TestSuite = result.output

            # Assemble final test code
            final_test_code = self._assemble_test_code(test_suite)

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "generated_tests": final_test_code,
                "test_file_name": test_suite.test_file_name,
                "num_test_cases": len(test_suite.test_cases),
                "test_types": list(set(tc.test_type for tc in test_suite.test_cases)),
                "coverage_target": test_suite.coverage_target,
                "test_strategy": test_suite.test_strategy,
                "fixtures_count": len(test_suite.fixtures),
                "dependencies": test_suite.test_dependencies,
                "intelligence_gathered": intelligence,
                "lines_generated": len(final_test_code.split('\n')),
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
                message=f"Test generation complete: {len(test_suite.test_cases)} test cases",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Test generation failed: {str(e)}"

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
        self, task: AgentTask, pre_gathered_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Gather intelligence from context or MCP."""
        intelligence = {}

        if pre_gathered_context:
            # Use pre-gathered context
            for key, context_item in pre_gathered_context.items():
                if "testing" in key.lower() or "test" in key.lower():
                    intelligence["testing_patterns"] = context_item.get("content", {})
        elif self.config.archon_mcp_enabled:
            # Gather fresh intelligence
            try:
                testing_intel = await self.mcp_client.perform_rag_query(
                    query="pytest testing patterns best practices",
                    context="testing",
                    match_count=3
                )
                intelligence["testing_patterns"] = testing_intel
            except Exception as e:
                await self.trace_logger.log_event(
                    event_type=TraceEventType.AGENT_ERROR,
                    message=f"Intelligence gathering failed (continuing): {str(e)}",
                    level=TraceLevel.WARNING,
                    agent_name=self.config.agent_name,
                    task_id=task.task_id
                )

        return intelligence

    def _build_testing_prompt(self, task: AgentTask, target_file: str, requirements: str) -> str:
        """Build detailed testing prompt for LLM."""
        return f"""Generate a comprehensive pytest test suite for the following:

**Target File:** {target_file}
**Task Description:** {task.description}

**Requirements:**
{requirements}

**Testing Goals:**
- Achieve 80%+ code coverage
- Test happy paths and error conditions
- Test edge cases and boundary conditions
- Use appropriate mocking for external dependencies
- Follow pytest best practices
- Create maintainable, readable tests

**Additional Context:**
{task.input_data.get('additional_context', 'None provided')}

Use the available tools to:
1. Analyze code to determine testing strategy
2. Suggest specific test cases
3. Get pytest fixture patterns

Generate a complete, production-ready test suite."""

    def _assemble_test_code(self, test_suite: TestSuite) -> str:
        """Assemble final test code."""
        code_parts = []

        # Header
        code_parts.append(f'"""')
        code_parts.append(f'{test_suite.test_file_name}')
        code_parts.append(f'')
        code_parts.append(f'Test suite with {len(test_suite.test_cases)} test cases.')
        code_parts.append(f'Coverage target: {test_suite.coverage_target}%')
        code_parts.append(f'Strategy: {test_suite.test_strategy}')
        code_parts.append(f'"""')
        code_parts.append("")

        # Imports
        code_parts.extend(test_suite.imports)
        code_parts.append("")

        # Setup code
        if test_suite.setup_code:
            code_parts.append("# ============================================================================")
            code_parts.append("# Setup")
            code_parts.append("# ============================================================================")
            code_parts.append("")
            code_parts.append(test_suite.setup_code)
            code_parts.append("")

        # Fixtures
        if test_suite.fixtures:
            code_parts.append("# ============================================================================")
            code_parts.append("# Fixtures")
            code_parts.append("# ============================================================================")
            code_parts.append("")
            for fixture in test_suite.fixtures:
                code_parts.append(fixture)
                code_parts.append("")

        # Test cases
        code_parts.append("# ============================================================================")
        code_parts.append("# Test Cases")
        code_parts.append("# ============================================================================")
        code_parts.append("")

        for test_case in test_suite.test_cases:
            code_parts.append(test_case.test_code)
            code_parts.append("")

        return "\n".join(code_parts)

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, 'close'):
            await self.mcp_client.close()
