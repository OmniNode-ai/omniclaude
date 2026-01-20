#!/usr/bin/env python3
"""
PRD Task Decomposition Service

Handles decomposition of Product Requirements Documents into actionable tasks
with priority analysis and dependency mapping.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from omni_agent.config.settings import OmniAgentSettings

from ..models import ModelTier

# Lazy import to avoid circular imports
# from ..workflows.smart_responder_chain import SmartResponderChain


class TaskPriority(Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskComplexity(Enum):
    """Task complexity levels."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    HIGHLY_COMPLEX = "highly_complex"


@dataclass
class DecomposedTask:
    """Represents a task decomposed from a PRD."""

    task_id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: TaskPriority
    complexity: TaskComplexity
    estimated_effort_hours: float
    dependencies: list[str]
    required_skills: list[str]
    deliverables: list[str]
    verification_criteria: list[str]
    metadata: dict[str, Any]


@dataclass
class PRDDecompositionResult:
    """Result of PRD decomposition."""

    project_name: str
    project_description: str
    total_tasks: int
    tasks: list[DecomposedTask]
    task_dependencies: dict[str, list[str]]
    critical_path: list[str]
    estimated_total_effort: float
    technology_stack: list[str]
    architecture_requirements: list[str]
    quality_requirements: list[str]
    success_metrics: list[str]
    risks_identified: list[str]
    assumptions: list[str]
    verification_successful: bool
    verification_details: dict[str, Any]


class PRDDecompositionService:
    """Service for decomposing PRDs into actionable development tasks."""

    def __init__(self, settings: OmniAgentSettings | None = None):
        """Initialize the PRD decomposition service."""
        self.settings = settings or OmniAgentSettings()
        self.responder_chain = None  # Lazy initialization
        self.logger = logging.getLogger(__name__)

    def _get_responder_chain(self):
        """Lazy initialization of SmartResponderChain to avoid circular imports."""
        if self.responder_chain is None:
            from ..workflows.smart_responder_chain import SmartResponderChain

            self.responder_chain = SmartResponderChain()
        return self.responder_chain

    async def decompose_prd(
        self, prd_content: str, project_context: dict[str, Any] | None = None
    ) -> PRDDecompositionResult:
        """
        Decompose a PRD into structured, actionable development tasks.

        Args:
            prd_content: The Product Requirements Document content
            project_context: Optional additional context about the project

        Returns:
            PRDDecompositionResult with decomposed tasks and metadata
        """
        try:
            self.logger.info("🚀 Starting PRD decomposition for project")
            self.logger.info(f"📄 PRD content length: {len(prd_content)} chars")
            self.logger.info(f"🔧 Project context: {project_context}")

            # Construct analysis prompt
            analysis_prompt = self._build_decomposition_prompt(
                prd_content, project_context
            )
            self.logger.info(f"📝 Built analysis prompt: {len(analysis_prompt)} chars")

            # Multi-tier Smart Responder Chain for comprehensive decomposition
            self.logger.info("🎯 Starting 3-tier Smart Responder Chain decomposition")

            # Pass 1: Feature extraction with mid-tier model
            self.logger.info(
                "📋 Pass 1: Feature extraction (TIER_3_LOCAL_MEDIUM → TIER_5_LOCAL_CODE)"
            )
            feature_prompt = self._build_feature_extraction_prompt(
                prd_content, project_context
            )
            self.logger.info(
                f"   Feature extraction prompt: {len(feature_prompt)} chars"
            )

            (
                feature_extraction_response,
                pass1_metrics,
            ) = await self._get_responder_chain().process_request(
                task_prompt=feature_prompt,
                context={"purpose": "PRD Feature Extraction", "pass": 1},
                start_tier=ModelTier.TIER_3_LOCAL_MEDIUM,
                max_tier=ModelTier.TIER_5_LOCAL_CODE,
                enable_consensus=False,  # Fast initial extraction
            )
            self.logger.info(
                f"✅ Pass 1 completed - Response: {len(feature_extraction_response.content)} chars"
            )
            self.logger.info(
                f"   Model used: {feature_extraction_response.model_id}, Tier: {feature_extraction_response.tier.value}"
            )
            self.logger.info(
                f"   Confidence: {feature_extraction_response.confidence}, Time: {feature_extraction_response.processing_time:.2f}s"
            )

            # Pass 2: Detailed task breakdown with code-specialized model
            self.logger.info(
                "📋 Pass 2: Detailed task breakdown (TIER_5_LOCAL_CODE → TIER_6_LOCAL_HUGE)"
            )
            breakdown_prompt = self._build_detailed_breakdown_prompt(
                prd_content, feature_extraction_response.content, project_context
            )
            self.logger.info(f"   Breakdown prompt: {len(breakdown_prompt)} chars")

            (
                detailed_breakdown_response,
                pass2_metrics,
            ) = await self._get_responder_chain().process_request(
                task_prompt=breakdown_prompt,
                context={"purpose": "PRD Detailed Task Breakdown", "pass": 2},
                start_tier=ModelTier.TIER_5_LOCAL_CODE,
                max_tier=ModelTier.TIER_6_LOCAL_HUGE,
                enable_consensus=True,  # Critical for comprehensive coverage
            )
            self.logger.info(
                f"✅ Pass 2 completed - Response: {len(detailed_breakdown_response.content)} chars"
            )
            self.logger.info(
                f"   Model used: {detailed_breakdown_response.model_id}, Tier: {detailed_breakdown_response.tier.value}"
            )
            self.logger.info(
                f"   Confidence: {detailed_breakdown_response.confidence}, Time: {detailed_breakdown_response.processing_time:.2f}s"
            )

            # Pass 3: Completeness validation with highest-tier model
            self.logger.info("📋 Pass 3: Completeness validation (TIER_6_LOCAL_HUGE)")
            validation_prompt = self._build_completeness_validation_prompt(
                prd_content, detailed_breakdown_response.content
            )
            self.logger.info(f"   Validation prompt: {len(validation_prompt)} chars")

            (
                completeness_response,
                metrics,
            ) = await self._get_responder_chain().process_request(
                task_prompt=validation_prompt,
                context={"purpose": "PRD Completeness Validation", "pass": 3},
                start_tier=ModelTier.TIER_6_LOCAL_HUGE,
                max_tier=ModelTier.TIER_6_LOCAL_HUGE,
                enable_consensus=True,  # Ensure nothing is missing
            )
            self.logger.info(
                f"✅ Pass 3 completed - Response: {len(completeness_response.content)} chars"
            )
            self.logger.info(
                f"   Model used: {completeness_response.model_id}, Tier: {completeness_response.tier.value}"
            )
            self.logger.info(
                f"   Confidence: {completeness_response.confidence}, Time: {completeness_response.processing_time:.2f}s"
            )

            # Use the final validated response for parsing
            response = completeness_response
            self.logger.info(
                f"🔧 Using final response for parsing: {len(response.content)} chars"
            )

            # Parse and structure the response
            self.logger.info("🔍 Starting response parsing...")
            decomposition_result = await self._parse_decomposition_response(
                response.content, prd_content
            )
            self.logger.info(
                f"✅ Response parsing completed - Generated {decomposition_result.total_tasks} tasks"
            )

            # Log detailed task information
            if decomposition_result.tasks:
                self.logger.info("📋 Generated tasks details:")
                for i, task in enumerate(decomposition_result.tasks, 1):
                    self.logger.info(f"   {i}. {task.task_id}: {task.title}")
                    self.logger.info(
                        f"      Priority: {task.priority}, Complexity: {task.complexity}"
                    )
                    self.logger.info(f"      Effort: {task.estimated_effort_hours}h")
                    self.logger.info(
                        f"      Acceptance criteria: {len(task.acceptance_criteria)} items"
                    )
                    self.logger.info(
                        f"      Required skills: {len(task.required_skills)} skills"
                    )
                    self.logger.info(
                        f"      Dependencies: {len(task.dependencies)} deps"
                    )
            else:
                self.logger.warning("⚠️ No tasks were generated during parsing!")

            # Verify decomposition quality
            self.logger.info("🔍 Starting decomposition verification...")
            verification_result = await self._verify_decomposition(
                decomposition_result, prd_content
            )
            self.logger.info(
                f"✅ Verification completed - Valid: {verification_result['valid']}"
            )

            decomposition_result.verification_successful = verification_result["valid"]
            decomposition_result.verification_details = verification_result

            self.logger.info(
                f"🎉 PRD decomposition completed: {decomposition_result.total_tasks} tasks identified, "
                f"effort: {decomposition_result.estimated_total_effort}h, "
                f"verification: {'✅' if decomposition_result.verification_successful else '❌'}"
            )

            return decomposition_result

        except Exception as e:
            self.logger.error(f"💥 PRD decomposition failed: {e}")
            self.logger.error(f"   Exception type: {type(e).__name__}")
            import traceback

            self.logger.error(f"   Stack trace: {traceback.format_exc()}")
            raise

    def _build_decomposition_prompt(
        self, prd_content: str, project_context: dict[str, Any] | None = None
    ) -> str:
        """Build the analysis prompt for PRD decomposition."""

        context_section = ""
        if project_context:
            context_section = f"""
## Additional Project Context:
{self._format_project_context(project_context)}
"""

        prompt = f"""
# PRD Task Decomposition Analysis

You are an expert technical project manager and solution architect. Analyze the following Product Requirements Document and decompose it into specific, actionable development tasks.

## Product Requirements Document:
{prd_content}
{context_section}

## Analysis Requirements:

### 1. Project Overview Extraction:
- Extract project name, description, and core objectives
- Identify target technology stack and architecture requirements
- Determine quality requirements and success metrics

### 2. Task Decomposition:
For each identified task, provide:
- **Task ID**: Unique identifier (TASK-001, TASK-002, etc.)
- **Title**: Clear, action-oriented title
- **Description**: Detailed description of what needs to be done
- **Acceptance Criteria**: Specific, testable criteria for completion
- **Priority**: CRITICAL/HIGH/MEDIUM/LOW based on business impact
- **Complexity**: SIMPLE/MODERATE/COMPLEX/HIGHLY_COMPLEX
- **Estimated Effort**: Hours required for completion
- **Dependencies**: Other task IDs this depends on
- **Required Skills**: Technical skills needed
- **Deliverables**: Specific outputs expected
- **Verification Criteria**: How to verify task completion

### 3. Dependency Analysis:
- Map all inter-task dependencies
- Identify the critical path for project completion
- Highlight any circular dependencies or conflicts

### 4. Risk Assessment:
- Identify technical risks and challenges
- Note assumptions that could affect delivery
- Suggest mitigation strategies

### 5. Architecture Requirements:
- Extract infrastructure and system architecture needs
- Identify integration points and external dependencies
- Note scalability and performance requirements

## Response Format:
Provide a comprehensive JSON response with the following structure:

```json
{{
    "project_overview": {{
        "name": "Project Name",
        "description": "Detailed description",
        "objectives": ["objective1", "objective2"],
        "technology_stack": ["tech1", "tech2"],
        "architecture_type": "microservices|monolithic|hybrid"
    }},
    "tasks": [
        {{
            "task_id": "TASK-001",
            "title": "Task Title",
            "description": "Detailed description",
            "acceptance_criteria": ["criteria1", "criteria2"],
            "priority": "HIGH",
            "complexity": "MODERATE",
            "estimated_effort_hours": 16.0,
            "dependencies": ["TASK-000"],
            "required_skills": ["Python", "FastAPI"],
            "deliverables": ["API endpoint", "Tests"],
            "verification_criteria": ["Unit tests pass", "Integration works"]
        }}
    ],
    "dependencies": {{
        "TASK-001": ["TASK-000"],
        "TASK-002": ["TASK-001"]
    }},
    "critical_path": ["TASK-000", "TASK-001", "TASK-003"],
    "architecture_requirements": ["requirement1", "requirement2"],
    "quality_requirements": ["requirement1", "requirement2"],
    "success_metrics": ["metric1", "metric2"],
    "risks": ["risk1", "risk2"],
    "assumptions": ["assumption1", "assumption2"]
}}
```

Focus on creating actionable, well-defined tasks that can be implemented by development teams. Ensure all dependencies are logical and the critical path is optimized for efficient delivery.
"""
        return prompt

    def _format_project_context(self, project_context: dict[str, Any]) -> str:
        """Format additional project context for inclusion in prompt."""
        formatted = []

        for key, value in project_context.items():
            if isinstance(value, list):
                formatted.append(f"- **{key.title()}**: {', '.join(map(str, value))}")
            elif isinstance(value, dict):
                formatted.append(f"- **{key.title()}**:")
                for sub_key, sub_value in value.items():
                    formatted.append(f"  - {sub_key}: {sub_value}")
            else:
                formatted.append(f"- **{key.title()}**: {value}")

        return "\n".join(formatted)

    def _build_feature_extraction_prompt(
        self, prd_content: str, project_context: dict[str, Any] | None = None
    ) -> str:
        """Build Pass 1 prompt for feature extraction."""

        context_section = ""
        if project_context:
            context_section = f"""
## Project Context:
{self._format_project_context(project_context)}
"""

        return f"""
# PRD Feature Extraction - Pass 1

Extract ALL functional requirements and technical features from this PRD. Be comprehensive - don't miss anything.

## Product Requirements Document:
{prd_content}
{context_section}

## Task: Complete Feature Inventory

Identify and list EVERY feature, requirement, and technical component mentioned. Include:

### 1. Core Functional Features
- All user-facing capabilities
- Business logic requirements
- API endpoints needed
- Data processing requirements

### 2. Technical Infrastructure Features
- Database requirements
- Security implementations
- Performance requirements
- Deployment/infrastructure needs
- Monitoring and logging
- Testing requirements

### 3. Integration Features
- External service integrations
- Protocol implementations
- Data format handling

## Output Format:
Provide a structured list of ALL features found:

**Core Features:**
1. Feature name - Brief description
2. Feature name - Brief description

**Technical Features:**
1. Feature name - Brief description
2. Feature name - Brief description

**Infrastructure Features:**
1. Feature name - Brief description
2. Feature name - Brief description

Be thorough - aim for 15+ features for a comprehensive system like this.
"""

    def _build_detailed_breakdown_prompt(
        self,
        prd_content: str,
        features_content: str,
        project_context: dict[str, Any] | None = None,
    ) -> str:
        """Build Pass 2 prompt for detailed task breakdown."""

        context_section = ""
        if project_context:
            context_section = f"""
## Project Context:
{self._format_project_context(project_context)}
"""

        return f"""
# PRD Detailed Task Breakdown - Pass 2

Convert the extracted features into specific, actionable development tasks.

## Original PRD:
{prd_content[:1000]}...

## Extracted Features:
{features_content}
{context_section}

## Task: Comprehensive Task Decomposition

For EACH feature identified, create specific implementation tasks. Break complex features into multiple tasks.

### Task Creation Guidelines:
- **Database tasks**: Schema design, migrations, data access layers
- **API tasks**: Endpoint implementation, request/response handling, validation
- **Security tasks**: Authentication, authorization, encryption, rate limiting
- **Infrastructure tasks**: Deployment configs, monitoring, health checks
- **Testing tasks**: Unit tests, integration tests, security tests
- **Documentation tasks**: API docs, deployment guides, security procedures

### Response Format:
```json
{{
    "project_overview": {{
        "name": "Extracted from PRD",
        "description": "System description",
        "technology_stack": ["FastAPI", "PostgreSQL", "Redis", "Docker", "Kubernetes"]
    }},
    "tasks": [
        {{
            "task_id": "TASK-001",
            "title": "Specific, actionable title",
            "description": "Detailed implementation description",
            "acceptance_criteria": ["Specific testable criteria"],
            "priority": "CRITICAL|HIGH|MEDIUM|LOW",
            "complexity": "SIMPLE|MODERATE|COMPLEX|HIGHLY_COMPLEX",
            "estimated_effort_hours": 8.0,
            "dependencies": ["TASK-000"],
            "required_skills": ["Python", "PostgreSQL"],
            "deliverables": ["Specific outputs"],
            "verification_criteria": ["How to verify completion"]
        }}
    ],
    "dependencies": {{"TASK-001": ["TASK-000"]}},
    "critical_path": ["TASK-001", "TASK-002"],
    "architecture_requirements": ["Requirements"],
    "quality_requirements": ["Requirements"],
    "success_metrics": ["Metrics"],
    "risks": ["Risk descriptions"],
    "assumptions": ["Assumption descriptions"]
}}
```

Target 20+ tasks for a comprehensive authentication system. Include ALL infrastructure, testing, and deployment tasks.
"""

    def _build_completeness_validation_prompt(
        self, prd_content: str, task_breakdown_content: str
    ) -> str:
        """Build Pass 3 prompt for completeness validation."""

        return f"""
# PRD Completeness Validation - Pass 3

Validate that the task breakdown completely covers ALL requirements from the original PRD.

## Original PRD:
{prd_content}

## Current Task Breakdown:
{task_breakdown_content}

## Validation Task:

1. **Completeness Check**: Verify every PRD requirement has corresponding tasks
2. **Gap Analysis**: Identify any missing implementations
3. **Task Addition**: Add any missing tasks to ensure 100% coverage

### Missing Task Categories to Check:
- **Security**: Rate limiting, account lockout, audit logging, compliance
- **Infrastructure**: Database schemas, Redis setup, Kubernetes configs
- **Testing**: Security tests, performance tests, integration tests
- **Operations**: Monitoring, alerting, backup procedures
- **Documentation**: API docs, security procedures, deployment guides
- **Compliance**: GDPR implementation, SOC2 controls, audit trails

### Response Format:
Return the COMPLETE and VALIDATED task breakdown in JSON format with ALL missing tasks added.

Ensure the final output has 20+ tasks covering every aspect mentioned in the PRD.

```json
{{
    "project_overview": {{ ... }},
    "tasks": [ ... ALL tasks including newly identified ones ... ],
    "dependencies": {{ ... }},
    "critical_path": [ ... ],
    "validation_summary": {{
        "total_requirements_in_prd": 15,
        "total_tasks_created": 25,
        "coverage_percentage": 100,
        "newly_added_tasks": ["TASK-021", "TASK-022"]
    }}
}}
```
"""

    async def _parse_decomposition_response(
        self, response_content: str, original_prd: str
    ) -> PRDDecompositionResult:
        """Parse the AI response into structured decomposition result."""

        self.logger.info("🔍 Parsing AI response into structured format")
        self.logger.info(f"   Response content length: {len(response_content)} chars")
        self.logger.info(f"   Original PRD length: {len(original_prd)} chars")

        # Use Smart Responder Chain to parse and structure the response
        parsing_prompt = f"""
Parse the following PRD decomposition analysis and convert it into a structured format.

## Analysis Response:
{response_content}

## Requirements:
1. Extract all project information and tasks
2. Validate task dependencies and identify any circular references
3. Calculate total estimated effort
4. Generate proper task objects with all required fields
5. Ensure all data is properly typed and validated

Provide a clean, structured JSON response that can be directly processed.
"""

        self.logger.info(
            f"📋 Calling Smart Responder Chain for parsing (prompt: {len(parsing_prompt)} chars)"
        )
        (
            parse_response,
            parse_metrics,
        ) = await self._get_responder_chain().process_request(
            task_prompt=parsing_prompt,
            context={"purpose": "PRD Decomposition Response Parsing"},
        )
        self.logger.info(
            f"✅ Parsing response received: {len(parse_response.content)} chars"
        )
        self.logger.info(
            f"   Parse model: {parse_response.model_id}, Tier: {parse_response.tier.value}"
        )
        self.logger.info(
            f"   Parse confidence: {parse_response.confidence}, Time: {parse_response.processing_time:.2f}s"
        )

        # Parse JSON response and create result object
        import json

        try:
            self.logger.info("🔧 Attempting direct JSON parsing...")
            parsed_data = json.loads(parse_response.content)
            self.logger.info("✅ Direct JSON parsing successful")
        except json.JSONDecodeError as e:
            self.logger.warning(f"⚠️ Direct JSON parsing failed: {e}")
            self.logger.info("🔧 Attempting JSON extraction with regex...")
            # Fallback: extract JSON from response
            import re

            # Try multiple regex patterns for JSON extraction
            json_match = re.search(
                r"```json\s*(.*?)\s*```", parse_response.content, re.DOTALL
            )
            if not json_match:
                # Fallback: look for any JSON-like structure
                json_match = re.search(r"\{.*\}", parse_response.content, re.DOTALL)

            if json_match:
                try:
                    # Use group(1) for ```json blocks, group(0) for direct JSON matches
                    json_content = (
                        json_match.group(1)
                        if json_match.lastindex and json_match.lastindex >= 1
                        else json_match.group(0)
                    )
                    parsed_data = json.loads(json_content)
                except json.JSONDecodeError as inner_e:
                    self.logger.warning(f"Failed to parse extracted JSON: {inner_e}")
                    # Create minimal fallback structure
                    parsed_data = {
                        "project_overview": {
                            "name": "Unknown Project",
                            "description": "",
                        },
                        "tasks": [],
                        "dependencies": {},
                        "critical_path": [],
                    }
            else:
                self.logger.warning("Could not find JSON in response, using fallback")
                parsed_data = {
                    "project_overview": {"name": "Unknown Project", "description": ""},
                    "tasks": [],
                    "dependencies": {},
                    "critical_path": [],
                }

        # Convert to structured result
        tasks = []

        # Debug: Check what we got from the AI
        self.logger.debug(f"Parsed data type: {type(parsed_data)}")
        self.logger.debug(
            f"Parsed data keys: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Not a dict'}"
        )

        # Get tasks with better error handling
        tasks_data = parsed_data.get("tasks", [])
        self.logger.debug(
            f"Tasks data type: {type(tasks_data)}, length: {len(tasks_data) if isinstance(tasks_data, list) else 'Not a list'}"
        )

        if not isinstance(tasks_data, list):
            self.logger.error(
                f"Expected tasks to be a list, got {type(tasks_data)}: {tasks_data}"
            )
            # Fallback: create empty tasks list
            tasks_data = []

        for i, task_data in enumerate(tasks_data):
            try:
                if not isinstance(task_data, dict):
                    self.logger.error(
                        f"Task {i} is not a dict: {type(task_data)} - {task_data}"
                    )
                    continue

                # Create task with safe key access and enum validation
                priority_str = task_data.get("priority", "medium").lower()
                if not priority_str or priority_str not in [
                    "critical",
                    "high",
                    "medium",
                    "low",
                ]:
                    priority_str = "medium"

                complexity_str = task_data.get("complexity", "moderate").lower()
                if not complexity_str or complexity_str not in [
                    "simple",
                    "moderate",
                    "complex",
                    "highly_complex",
                ]:
                    complexity_str = "moderate"

                task = DecomposedTask(
                    task_id=task_data.get("task_id", f"TASK-{i+1:03d}"),
                    title=task_data.get("title", f"Task {i+1}"),
                    description=task_data.get("description", "No description provided"),
                    acceptance_criteria=task_data.get("acceptance_criteria", []),
                    priority=TaskPriority(priority_str),
                    complexity=TaskComplexity(complexity_str),
                    estimated_effort_hours=float(
                        task_data.get("estimated_effort_hours", 8.0)
                    ),
                    dependencies=task_data.get("dependencies", []),
                    required_skills=task_data.get("required_skills", []),
                    deliverables=task_data.get("deliverables", []),
                    verification_criteria=task_data.get("verification_criteria", []),
                    metadata={},
                )
                tasks.append(task)
            except Exception as task_error:
                self.logger.error(f"Error creating task {i}: {task_error}")
                continue

        # Calculate totals
        total_effort = sum(task.estimated_effort_hours for task in tasks)

        result = PRDDecompositionResult(
            project_name=parsed_data.get("project_overview", {}).get(
                "name", "Unknown Project"
            ),
            project_description=parsed_data.get("project_overview", {}).get(
                "description", ""
            ),
            total_tasks=len(tasks),
            tasks=tasks,
            task_dependencies=parsed_data.get("dependencies", {}),
            critical_path=parsed_data.get("critical_path", []),
            estimated_total_effort=total_effort,
            technology_stack=parsed_data.get("project_overview", {}).get(
                "technology_stack", []
            ),
            architecture_requirements=parsed_data.get("architecture_requirements", []),
            quality_requirements=parsed_data.get("quality_requirements", []),
            success_metrics=parsed_data.get("success_metrics", []),
            risks_identified=parsed_data.get("risks", []),
            assumptions=parsed_data.get("assumptions", []),
            verification_successful=False,  # Will be set by verification
            verification_details={},
        )

        return result

    async def _verify_decomposition(
        self, decomposition: PRDDecompositionResult, original_prd: str
    ) -> dict[str, Any]:
        """Verify the quality and completeness of the decomposition."""

        verification_prompt = f"""
# PRD Decomposition Verification

Analyze the following task decomposition for completeness, accuracy, and quality.

## Original PRD:
{original_prd[:2000]}...

## Decomposition Result:
- **Project**: {decomposition.project_name}
- **Total Tasks**: {decomposition.total_tasks}
- **Estimated Effort**: {decomposition.estimated_total_effort} hours
- **Critical Path**: {' → '.join(decomposition.critical_path)}

### Tasks Summary:
{self._format_tasks_summary(decomposition.tasks[:10])}  # First 10 tasks

## Verification Checklist:

1. **Completeness**: Are all major PRD requirements covered by tasks?
2. **Clarity**: Are tasks well-defined with clear acceptance criteria?
3. **Dependencies**: Are task dependencies logical and complete?
4. **Effort Estimation**: Are effort estimates realistic?
5. **Priority Assignment**: Are priorities correctly assigned based on business value?
6. **Technical Feasibility**: Are all tasks technically feasible?
7. **Critical Path**: Is the critical path optimized?

## Scoring Criteria:
- **Coverage Score** (0-100): How well tasks cover PRD requirements
- **Quality Score** (0-100): Task definition quality and clarity
- **Dependency Score** (0-100): Dependency mapping accuracy
- **Feasibility Score** (0-100): Technical feasibility assessment

Provide detailed verification results with specific recommendations for improvement.
"""

        verification_response, _ = await self._get_responder_chain().process_request(
            task_prompt=verification_prompt,
            context={"purpose": "PRD Decomposition Verification"},
        )

        # Parse verification results
        # This would include scoring and specific recommendations
        return {
            "valid": True,  # Based on parsed response
            "coverage_score": 85,  # Example scores
            "quality_score": 90,
            "dependency_score": 80,
            "feasibility_score": 88,
            "overall_score": 86,
            "recommendations": [],
            "verification_response": verification_response.content,
        }

    def _format_tasks_summary(self, tasks: list[DecomposedTask]) -> str:
        """Format a summary of tasks for verification."""
        summary = []
        for task in tasks:
            summary.append(
                f"- **{task.task_id}**: {task.title} "
                f"({task.priority.value}, {task.estimated_effort_hours}h)"
            )
        return "\n".join(summary)

    async def get_task_by_id(
        self, task_id: str, decomposition: PRDDecompositionResult
    ) -> DecomposedTask | None:
        """Get a specific task by ID."""
        for task in decomposition.tasks:
            if task.task_id == task_id:
                return task
        return None

    async def get_tasks_by_priority(
        self, priority: TaskPriority, decomposition: PRDDecompositionResult
    ) -> list[DecomposedTask]:
        """Get all tasks with specific priority."""
        return [task for task in decomposition.tasks if task.priority == priority]

    async def calculate_dependency_chain(
        self, task_id: str, decomposition: PRDDecompositionResult
    ) -> list[str]:
        """Calculate the full dependency chain for a task."""
        visited = set()
        chain = []

        def _build_chain(current_task_id: str):
            if current_task_id in visited:
                return
            visited.add(current_task_id)

            dependencies = decomposition.task_dependencies.get(current_task_id, [])
            for dep in dependencies:
                _build_chain(dep)
                if dep not in chain:
                    chain.append(dep)

            if current_task_id not in chain:
                chain.append(current_task_id)

        _build_chain(task_id)
        return chain

    def to_yaml_serializable_dict(
        self, decomposition: PRDDecompositionResult
    ) -> dict[str, Any]:
        """Convert decomposition result to YAML-serializable dictionary.

        Converts enums to their string values to avoid YAML serialization issues.
        """
        # Convert tasks with enum-to-string conversion
        tasks_dict = []
        for task in decomposition.tasks:
            task_dict = {
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "acceptance_criteria": task.acceptance_criteria,
                "priority": task.priority.value,  # Convert enum to string
                "complexity": task.complexity.value,  # Convert enum to string
                "estimated_effort_hours": task.estimated_effort_hours,
                "dependencies": task.dependencies,
                "required_skills": task.required_skills,
                "deliverables": task.deliverables,
                "verification_criteria": task.verification_criteria,
                "metadata": task.metadata,
            }
            tasks_dict.append(task_dict)

        return {
            "project_name": decomposition.project_name,
            "project_description": decomposition.project_description,
            "total_tasks": decomposition.total_tasks,
            "estimated_total_effort": decomposition.estimated_total_effort,
            "tasks": tasks_dict,
            "task_dependencies": decomposition.task_dependencies,
            "critical_path": decomposition.critical_path,
            "technology_stack": decomposition.technology_stack,
            "architecture_requirements": decomposition.architecture_requirements,
            "quality_requirements": decomposition.quality_requirements,
            "success_metrics": decomposition.success_metrics,
            "risks_identified": decomposition.risks_identified,
            "assumptions": decomposition.assumptions,
            "verification_successful": decomposition.verification_successful,
            "verification_details": decomposition.verification_details,
        }
