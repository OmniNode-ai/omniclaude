"""
Pydantic AI-based Validation Agent

Expert validation for code, configuration, and output compliance with
intelligent rule evaluation and quality reporting.
"""

import datetime
import json
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


class ValidationRule(BaseModel):
    """Rule for validation checking."""

    id: str
    name: str
    description: str
    severity: str  # e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    pattern: str | None = None  # Regex or specific string pattern
    expected_value: Any | None = None  # For configuration validation


class Violation(BaseModel):
    """Validation violation found."""

    rule_id: str
    message: str
    location: str | None = None  # e.g., file:line, config_path
    severity: str


class ValidationResult(BaseModel):
    """Result of validation check."""

    is_compliant: bool
    violations: list[Violation] = Field(default_factory=list)
    summary: str


class ValidationRequest(BaseModel):
    """Request for validation."""

    target_type: str  # e.g., 'code', 'configuration', 'output'
    target_content: str  # The actual code, config (as JSON string), or output
    rules: list[ValidationRule]


class ComplianceReport(BaseModel):
    """Complete compliance report output."""

    report_id: str
    timestamp: str
    overall_status: str  # e.g., 'COMPLIANT', 'NON_COMPLIANT'
    validation_results: list[ValidationResult] = Field(default_factory=list)
    details: dict[str, Any] | None = None
    rules_evaluated: int = Field(description="Number of rules evaluated")
    violations_found: int = Field(description="Total violations found")
    critical_violations: int = Field(description="Critical violations count")
    quality_score: float = Field(
        description="Overall compliance quality score 0.0-1.0", ge=0.0, le=1.0
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
    validation_request: ValidationRequest


# ============================================================================
# Pydantic AI Agent Definition
# ============================================================================

VALIDATION_SYSTEM_PROMPT = """You are an expert validation agent for code, configuration, and output compliance.

**Your Expertise:**
- Code quality and standards validation
- Configuration compliance checking
- Output format and content validation
- Security and best practices enforcement

**Your Task:**
Evaluate the target content against validation rules to:
1. Check each rule systematically
2. Identify violations with precise locations
3. Assess severity and compliance status
4. Generate comprehensive compliance report

**Validation Requirements:**
- Apply each rule thoroughly to target content
- For code: Check patterns, structure, quality standards
- For config: Validate structure, required values, formats
- For output: Verify completeness, format, expected content
- Provide clear violation messages with exact locations
- Calculate overall quality score based on violations

**Quality Standards:**
- All rules must be evaluated
- Violations must specify exact location when possible
- Severity must match rule definition
- Quality score calculation:
  * 1.0 = No violations
  * 0.9-0.99 = Only LOW violations
  * 0.7-0.89 = MEDIUM violations present
  * 0.4-0.69 = HIGH violations present
  * 0.0-0.39 = CRITICAL violations present

Validate thoroughly and generate complete compliance report."""

# Model configuration
MODEL_NAME = "google-gla:gemini-2.5-flash"  # Latest Gemini Flash model

# Create the Pydantic AI agent
validation_agent = Agent[AgentDeps, ComplianceReport](
    MODEL_NAME,
    deps_type=AgentDeps,
    output_type=ComplianceReport,
    system_prompt=VALIDATION_SYSTEM_PROMPT,
)


# ============================================================================
# Agent Tools
# ============================================================================


@validation_agent.tool
async def evaluate_code_rules(ctx: RunContext[AgentDeps]) -> str:
    """Evaluate validation rules against code content.

    Returns: Summary of code validation findings
    """
    deps = ctx.deps
    request = deps.validation_request

    if request.target_type != "code":
        return "Not a code validation request"

    findings = []
    findings.append("**Code Validation Analysis:**")
    findings.append(f"- Total rules to evaluate: {len(request.rules)}")

    # Analyze code structure
    code_lines = request.target_content.split("\n")
    findings.append(f"- Code lines: {len(code_lines)}")

    # Check for common patterns
    for rule in request.rules:
        if rule.pattern and rule.pattern in request.target_content:
            findings.append(
                f"- Pattern '{rule.pattern}' found (Rule: {rule.id}, Severity: {rule.severity})"
            )

    return "\n".join(findings)


@validation_agent.tool
async def evaluate_config_rules(ctx: RunContext[AgentDeps]) -> str:
    """Evaluate validation rules against configuration content.

    Returns: Summary of configuration validation findings
    """
    deps = ctx.deps
    request = deps.validation_request

    if request.target_type != "configuration":
        return "Not a configuration validation request"

    findings = []
    findings.append("**Configuration Validation Analysis:**")

    # Try to parse as JSON
    try:
        config_dict = json.loads(request.target_content)
        findings.append(f"- Valid JSON with {len(config_dict)} keys")

        # Check for expected values
        for rule in request.rules:
            if rule.pattern and rule.expected_value:
                actual_value = config_dict.get(rule.pattern)
                if actual_value != rule.expected_value:
                    findings.append(
                        f"- Key '{rule.pattern}': expected '{rule.expected_value}', got '{actual_value}'"
                    )
                else:
                    findings.append(f"- Key '{rule.pattern}': compliant")
    except json.JSONDecodeError as e:
        findings.append(f"- **CRITICAL**: Invalid JSON - {str(e)}")

    return "\n".join(findings)


@validation_agent.tool
async def evaluate_output_rules(ctx: RunContext[AgentDeps]) -> str:
    """Evaluate validation rules against output content.

    Returns: Summary of output validation findings
    """
    deps = ctx.deps
    request = deps.validation_request

    if request.target_type != "output":
        return "Not an output validation request"

    findings = []
    findings.append("**Output Validation Analysis:**")
    findings.append(f"- Output length: {len(request.target_content)} characters")

    # Check for required patterns and values
    for rule in request.rules:
        if rule.pattern:
            if rule.pattern in request.target_content:
                findings.append(f"- Required pattern '{rule.pattern}' present")
            else:
                findings.append(
                    f"- **Missing**: Required pattern '{rule.pattern}' (Rule: {rule.id})"
                )

        if rule.expected_value:
            if str(rule.expected_value) in request.target_content:
                findings.append(f"- Expected value '{rule.expected_value}' present")
            else:
                findings.append(
                    f"- **Missing**: Expected value '{rule.expected_value}' (Rule: {rule.id})"
                )

    return "\n".join(findings)


@validation_agent.tool
async def get_validation_standards(ctx: RunContext[AgentDeps]) -> str:
    """Get validation standards and compliance guidelines.

    Returns: Validation methodology and standards
    """
    return """
**Validation Standards and Methodology:**

1. **Rule Evaluation Process:**
   - Evaluate each rule independently
   - Check pattern matches (regex or substring)
   - Verify expected values when specified
   - Record violation location precisely

2. **Severity Levels:**
   - CRITICAL: Security issues, broken functionality
   - HIGH: Major quality/compliance issues
   - MEDIUM: Best practice violations
   - LOW: Style and minor issues

3. **Quality Score Calculation:**
   - Start at 1.0 (perfect compliance)
   - CRITICAL violation: -0.3 per violation
   - HIGH violation: -0.2 per violation
   - MEDIUM violation: -0.1 per violation
   - LOW violation: -0.05 per violation
   - Minimum score: 0.0

4. **Compliance Status:**
   - COMPLIANT: No violations found
   - NON_COMPLIANT: One or more violations present

5. **Report Requirements:**
   - All violations must be documented
   - Locations must be specific
   - Summary must be actionable
"""


# ============================================================================
# Wrapper Class for Compatibility
# ============================================================================


@register_agent(
    agent_name="validator",
    agent_type="validator",
    capabilities=[
        "code_validation",
        "config_validation",
        "output_validation",
        "compliance_reporting",
    ],
    description="Compliance and validation agent",
)
class AgentValidator:
    """
    Pydantic AI-based validation agent.

    Provides expert validation for code, configuration, and output compliance.
    """

    def __init__(self):
        # Config is optional - create default if not found
        try:
            self.config = AgentConfig.load("agent-validator")
        except (FileNotFoundError, Exception):
            # Create minimal default config
            self.config = AgentConfig(
                agent_name="agent-validator",
                agent_domain="validation_compliance",
                agent_purpose="Validate code, configuration, and output compliance",
            )
        self.trace_logger = get_trace_logger()
        self.mcp_client = ArchonMCPClient()
        self._current_trace_id: str | None = None

    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute validation using Pydantic AI agent.

        Args:
            task: Task containing validation request

        Returns:
            AgentResult with compliance report
        """
        start_time = time.time()

        # Start agent trace
        self._current_trace_id = await self.trace_logger.start_agent_trace(
            agent_name=self.config.agent_name,
            task_id=task.task_id,
            metadata={"using_pydantic_ai": True},
        )

        try:
            # Extract validation request from task
            validation_request = self._extract_validation_request(task)

            await self.trace_logger.log_event(
                event_type=TraceEventType.TASK_ASSIGNED,
                message=f"Validating {validation_request.target_type}: {len(validation_request.rules)} rules",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            # Create agent dependencies
            deps = AgentDeps(
                task=task,
                config=self.config,
                mcp_client=self.mcp_client,
                trace_logger=self.trace_logger,
                trace_id=self._current_trace_id,
                validation_request=validation_request,
            )

            # Build validation prompt
            prompt = self._build_validation_prompt(validation_request)

            # Run Pydantic AI agent
            await self.trace_logger.log_event(
                event_type=TraceEventType.AGENT_START,
                message="Invoking Pydantic AI validation agent",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            result = await validation_agent.run(prompt, deps=deps)
            compliance_report: ComplianceReport = result.output

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Build output
            output_data = {
                "compliance_report": compliance_report.model_dump(),
                "validation_summary": {
                    "rules_evaluated": compliance_report.rules_evaluated,
                    "violations_found": compliance_report.violations_found,
                    "critical_violations": compliance_report.critical_violations,
                    "quality_score": compliance_report.quality_score,
                    "overall_status": compliance_report.overall_status,
                },
                "pydantic_ai_metadata": {
                    "model_used": MODEL_NAME,
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
                message=f"Validation complete: {compliance_report.overall_status}, quality={compliance_report.quality_score:.2f}",
                level=TraceLevel.INFO,
                agent_name=self.config.agent_name,
                task_id=task.task_id,
            )

            return agent_result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = f"Validation failed: {str(e)}"

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

    async def process_validation_request(
        self, request: ValidationRequest
    ) -> ComplianceReport:
        """
        Process validation request directly (legacy compatibility method).

        Args:
            request: ValidationRequest to process

        Returns:
            ComplianceReport with validation results
        """
        # Create a task from the validation request
        task = AgentTask(
            task_id=f"validation-{datetime.datetime.now().isoformat()}",
            description=f"Validate {request.target_type}",
            input_data={"validation_request": request.model_dump()},
        )

        # Execute via agent
        result = await self.execute(task)

        if result.success:
            return ComplianceReport(**result.output_data["compliance_report"])
        else:
            # Return error report
            return ComplianceReport(
                report_id=f"error-{datetime.datetime.now().isoformat()}",
                timestamp=datetime.datetime.now().isoformat(),
                overall_status="ERROR",
                validation_results=[],
                rules_evaluated=0,
                violations_found=0,
                critical_violations=0,
                quality_score=0.0,
                details={"error": result.error},
            )

    def _extract_validation_request(self, task: AgentTask) -> ValidationRequest:
        """Extract ValidationRequest from task input data."""
        input_data = task.input_data

        # Check if validation_request is already provided
        if "validation_request" in input_data:
            request_data = input_data["validation_request"]
            return ValidationRequest(**request_data)

        # Otherwise construct from task data
        target_type = input_data.get("target_type", "code")
        target_content = input_data.get("target_content", input_data.get("content", ""))
        rules_data = input_data.get("rules", [])

        rules = [
            ValidationRule(**rule) if isinstance(rule, dict) else rule
            for rule in rules_data
        ]

        return ValidationRequest(
            target_type=target_type, target_content=target_content, rules=rules
        )

    def _build_validation_prompt(self, request: ValidationRequest) -> str:
        """Build detailed validation prompt for LLM."""
        return f"""Perform comprehensive validation of {request.target_type} content:

**Target Type:** {request.target_type}

**Content to Validate:**
```
{request.target_content[:1000]}{"..." if len(request.target_content) > 1000 else ""}
```

**Validation Rules ({len(request.rules)}):**
{self._format_rules(request.rules)}

**Your Validation Must Include:**

1. **Rule Evaluation:**
   - Systematically evaluate each rule
   - Check for pattern matches
   - Verify expected values
   - Identify exact violation locations

2. **Violation Detection:**
   - Document all violations found
   - Specify precise locations
   - Match severity to rule definition
   - Provide clear violation messages

3. **Quality Assessment:**
   - Calculate overall quality score
   - Count violations by severity
   - Determine compliance status
   - Generate actionable summary

Use available tools to:
1. Evaluate code rules (for code validation)
2. Evaluate config rules (for configuration validation)
3. Evaluate output rules (for output validation)
4. Get validation standards for methodology

Provide complete compliance report with all violations documented."""

    def _format_rules(self, rules: list[ValidationRule]) -> str:
        """Format rules for display in prompt."""
        formatted = []
        for rule in rules:
            formatted.append(f"- {rule.id}: {rule.name} (Severity: {rule.severity})")
            formatted.append(f"  Description: {rule.description}")
            if rule.pattern:
                formatted.append(f"  Pattern: {rule.pattern}")
            if rule.expected_value:
                formatted.append(f"  Expected: {rule.expected_value}")
        return "\n".join(formatted)

    async def cleanup(self):
        """Cleanup resources."""
        if hasattr(self.mcp_client, "close"):
            await self.mcp_client.close()
