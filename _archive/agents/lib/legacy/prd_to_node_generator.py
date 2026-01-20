#!/usr/bin/env python3
"""
PRD-to-Node Generation Workflow Orchestrator

This orchestrator coordinates specialized services to generate complete OmniNode
implementations from Product Requirements Documents through a multi-stage pipeline
with verification loops and intelligence integration.

Refactored Architecture:
1. PRD Task Decomposition Service
2. Infrastructure Context Gathering Service
3. Dependency Analysis Service
4. Contract/Subcontract Generation Service
5. Node Cloning and Generation Service
6. Verification and Validation Service

The workflow orchestrates these services using LangGraph for state management
and service coordination.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from ..config.settings import OmniAgentSettings

# Import artifact models for proper typed serialization
from ..models import (
    ArtifactContract,
    ArtifactDependency,
    ArtifactInfrastructureContext,
    ArtifactTask,
    ArtifactVerificationResult,
    BaseWorkflowArtifact,
    PRDToNodeResult,
    TaskComplexity,
    TaskDecompositionArtifact,
    TaskPriority,
    WorkflowCompletionArtifact,
    WorkflowStage,
    WorkflowStateArtifact,
)
from ..services.contract_generation_service import (
    ContractGenerationService,
    ModelContractGenerationRequest,
)
from ..services.dependency_analysis_service import (
    DependencyAnalysisService,
    ModelDependencyAnalysisRequest,
)
from ..services.infrastructure_context_service import (
    InfrastructureContext,
    InfrastructureContextService,
    ModelInfrastructureContextRequest,
)
from ..services.infrastructure_context_service import NodeType as ServiceNodeType
from ..services.node_generation_service import (
    ModelNodeGenerationRequest,
    NodeGenerationService,
)

# Import specialized services
from ..services.prd_decomposition_service import PRDDecompositionService
from ..services.verification_validation_service import (
    ModelVerificationRequest,
    VerificationValidationService,
)


class NodeType(Enum):
    """OmniNode types based on the 4-node system."""

    COMPUTE = "COMPUTE"
    EFFECT = "EFFECT"
    REDUCER = "REDUCER"
    ORCHESTRATOR = "ORCHESTRATOR"


class VerificationStage(Enum):
    """Verification stages in the pipeline."""

    TASK_DECOMPOSITION = "task_decomposition"
    INFRASTRUCTURE_CONTEXT = "infrastructure_context"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    CONTRACT_GENERATION = "contract_generation"
    CANARY_CLONE = "canary_clone"
    FINAL_NODE = "final_node"


class Task(BaseModel):
    """Represents a decomposed task from PRD analysis."""

    task_id: str = Field(
        ..., description="Changed from 'id' to 'task_id' to match ArtifactTask"
    )
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Task description")
    acceptance_criteria: list[str] = Field(
        default_factory=list, description="Acceptance criteria"
    )
    priority: str = Field(default="medium", description="Will hold TaskPriority.value")
    complexity: str = Field(
        default="moderate", description="Will hold TaskComplexity.value"
    )
    estimated_effort_hours: float = Field(
        default=0.0, description="Estimated effort in hours"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Task dependencies"
    )
    required_skills: list[str] = Field(
        default_factory=list, description="Required skills"
    )
    deliverables: list[str] = Field(
        default_factory=list, description="Expected deliverables"
    )
    verification_criteria: list[str] = Field(
        default_factory=list, description="Verification criteria"
    )

    # Legacy fields for backward compatibility
    complexity_score: float = Field(default=0.0, description="Complexity score")
    node_type_hints: list[NodeType] = Field(
        default_factory=list, description="Node type hints"
    )


# Import InfrastructureContext from services to avoid duplication


class NodeGenerationState(BaseModel):
    """State maintained throughout the LangGraph workflow."""

    # Input
    prd_content: str
    target_node_type: NodeType
    project_context: dict[str, Any] = Field(default_factory=dict)

    # Artifact Generation Control
    generate_artifacts: bool = False
    artifact_output_dir: str | None = None

    # Task Decomposition
    tasks: list[Task] = Field(default_factory=list)
    current_task: Task | None = None
    current_task_index: int = 0

    # Infrastructure Context
    infrastructure_context: InfrastructureContext | None = Field(
        None, description="Infrastructure context"
    )

    # Dependency Analysis
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    method_signatures: list[dict[str, Any]] = Field(default_factory=list)
    required_protocols: list[dict[str, Any]] = Field(default_factory=list)
    required_classes: list[dict[str, Any]] = Field(default_factory=list)

    # Contract Generation
    contracts: list[dict[str, Any]] = Field(default_factory=list)
    subcontracts: list[dict[str, Any]] = Field(default_factory=list)

    # Canary Clone
    canary_clone_template: dict[str, Any] | None = None

    # Code Generation
    generated_node_code: str | None = None
    generated_tests: str | None = None

    # Verification Results (use string keys for JSON serialization)
    verification_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    overall_validation_passed: bool = False

    # Error Handling
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Retry Counters (to prevent infinite loops)
    infrastructure_context_retries: int = 0
    dependency_analysis_retries: int = 0
    contract_generation_retries: int = 0
    canary_clone_retries: int = 0

    MAX_RETRIES: int = 2  # Max 2 retries per stage

    # Archon Integration
    archon_session_id: str | None = None
    intelligence_context: dict[str, Any] = Field(default_factory=dict)


class PRDToNodeGenerator:
    """
    Lightweight workflow orchestrator for PRD-to-Node generation.

    This orchestrator coordinates specialized services to generate complete
    OmniNode implementations from Product Requirements Documents. Each service
    handles a specific concern while the orchestrator manages the workflow
    state and service coordination.
    """

    def __init__(self, settings: OmniAgentSettings | None = None):
        self.settings = settings or OmniAgentSettings()
        self.logger = logging.getLogger(__name__)

        # Initialize specialized services
        self.prd_decomposition_service = PRDDecompositionService(settings)
        self.infrastructure_context_service = InfrastructureContextService(settings)
        self.dependency_analysis_service = DependencyAnalysisService(settings)
        self.contract_generation_service = ContractGenerationService(settings)
        self.node_generation_service = NodeGenerationService(settings)
        self.verification_service = VerificationValidationService(settings)

        # Initialize workflow graph
        self.workflow = self._build_workflow()

    def _save_stage_artifacts(
        self,
        state: NodeGenerationState,
        stage_name: str,
        artifact_model: BaseWorkflowArtifact,
    ) -> None:
        """Save artifacts from a workflow stage using proper Pydantic models and YAML serialization."""
        if not state.generate_artifacts or not state.artifact_output_dir:
            return

        try:
            from pathlib import Path

            import yaml

            output_dir = Path(state.artifact_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save stage artifacts using Pydantic model to YAML
            stage_file = output_dir / f"{stage_name}_artifacts.yaml"
            with open(stage_file, "w") as f:
                yaml.safe_dump(
                    artifact_model.model_dump(mode="json"),
                    f,
                    indent=2,
                    default_flow_style=False,
                )

            self.logger.info(f"Saved {stage_name} artifacts to {stage_file}")

            # Save current workflow state snapshot
            state_artifact = self._create_state_artifact(state, stage_name)
            state_file = output_dir / f"{stage_name}_state.yaml"
            with open(state_file, "w") as f:
                yaml.safe_dump(
                    state_artifact.model_dump(mode="json"),
                    f,
                    indent=2,
                    default_flow_style=False,
                )

            self.logger.info(f"Saved {stage_name} state to {state_file}")

        except Exception as e:
            self.logger.error(f"Failed to save artifacts for {stage_name}: {e}")

    def _create_state_artifact(
        self, state: NodeGenerationState, current_stage: str
    ) -> WorkflowStateArtifact:
        """Create a WorkflowStateArtifact from the current state."""
        try:
            # Convert existing state data to artifact models
            artifact_tasks = []
            for task in state.tasks:
                # Convert Task BaseModel to ArtifactTask
                artifact_task = ArtifactTask(
                    task_id=task.task_id,
                    title=task.title,
                    description=task.description,
                    acceptance_criteria=task.acceptance_criteria,
                    priority=TaskPriority.MEDIUM,  # Map from string to enum if needed
                    complexity=TaskComplexity.MODERATE,  # Map from string to enum if needed
                    estimated_effort_hours=task.estimated_effort_hours,
                    dependencies=task.dependencies,
                    required_skills=task.required_skills,
                    deliverables=task.deliverables,
                    verification_criteria=task.verification_criteria,
                )
                artifact_tasks.append(artifact_task)

            # Convert InfrastructureContext BaseModel to ArtifactInfrastructureContext
            artifact_infra_context = None
            if state.infrastructure_context:
                artifact_infra_context = ArtifactInfrastructureContext(
                    canary_references=state.infrastructure_context.canary_references,
                    contract_examples=state.infrastructure_context.contract_examples,
                    coding_standards=state.infrastructure_context.coding_standards,
                    naming_conventions=state.infrastructure_context.naming_conventions,
                    deployment_patterns=state.infrastructure_context.deployment_patterns,
                    testing_patterns=state.infrastructure_context.testing_patterns,
                    architecture_patterns=state.infrastructure_context.architecture_patterns,
                    integration_patterns=state.infrastructure_context.integration_patterns,
                )

            # Convert dependencies to ArtifactDependency
            artifact_dependencies = []
            for dep in state.dependencies:
                artifact_dep = ArtifactDependency(
                    name=getattr(dep, "name", "Unknown Dependency"),
                    version=getattr(dep, "version", None),
                    dependency_type=getattr(dep, "dependency_type", "unknown"),
                    purpose=getattr(dep, "purpose", ""),
                    integration_notes=getattr(dep, "integration_notes", ""),
                )
                artifact_dependencies.append(artifact_dep)

            # Convert contracts to ArtifactContract
            artifact_contracts = []
            for contract in state.contracts:
                artifact_contract = ArtifactContract(
                    contract_name=getattr(
                        contract, "contract_name", "Unnamed Contract"
                    ),
                    input_schema=getattr(contract, "input_schema", {}),
                    output_schema=getattr(contract, "output_schema", {}),
                    error_codes=getattr(contract, "error_codes", {}),
                    capabilities=getattr(contract, "capabilities", []),
                )
                artifact_contracts.append(artifact_contract)

            return WorkflowStateArtifact(
                prd_content=state.prd_content,
                target_node_type=str(state.target_node_type),
                project_context=state.project_context,
                current_stage=WorkflowStage(current_stage.lower()),
                stages_completed=(
                    [stage.lower() for stage in state.validation_results.keys()]
                    if hasattr(state, "validation_results") and state.validation_results
                    else []
                ),
                generate_artifacts=state.generate_artifacts,
                artifact_output_dir=state.artifact_output_dir,
                tasks=artifact_tasks,
                current_task=(
                    artifact_tasks[state.current_task_index]
                    if artifact_tasks and state.current_task_index < len(artifact_tasks)
                    else None
                ),
                current_task_index=state.current_task_index,
                infrastructure_context=artifact_infra_context,
                dependencies=artifact_dependencies,
                contracts=artifact_contracts,
                subcontracts=[
                    ArtifactContract(
                        contract_name=getattr(
                            subcontract, "contract_name", "Unnamed Subcontract"
                        ),
                        input_schema=getattr(subcontract, "input_schema", {}),
                        output_schema=getattr(subcontract, "output_schema", {}),
                        error_codes=getattr(subcontract, "error_codes", {}),
                        capabilities=getattr(subcontract, "capabilities", []),
                    )
                    for subcontract in (
                        getattr(state, "subcontracts", [])
                        if hasattr(state, "subcontracts")
                        else []
                    )
                ],
                generated_node_code=state.generated_node_code,
                generated_tests=state.generated_tests,
                verification_results=[
                    # Convert verification results to proper format
                    {
                        "stage": stage_name,
                        "result": result,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    for stage_name, result in (
                        state.verification_results.items()
                        if hasattr(state, "verification_results")
                        and state.verification_results
                        else []
                    )
                ],
            )
        except Exception as e:
            self.logger.warning(f"Failed to create state artifact: {e}")
            # Return minimal state artifact
            return WorkflowStateArtifact(
                prd_content=state.prd_content,
                target_node_type=str(state.target_node_type),
                project_context=state.project_context,
                current_stage=WorkflowStage.TASK_DECOMPOSITION,
                generate_artifacts=state.generate_artifacts,
                artifact_output_dir=state.artifact_output_dir,
            )

    def _convert_to_artifact_tasks(self, tasks: list[Task]) -> list[ArtifactTask]:
        """Convert Task objects to ArtifactTask objects for serialization."""
        artifact_tasks = []
        for task in tasks:
            artifact_task = ArtifactTask(
                task_id=task.task_id,
                title=task.title,
                description=task.description,
                acceptance_criteria=task.acceptance_criteria,
                priority=task.priority,
                complexity=task.complexity,
                estimated_effort_hours=task.estimated_effort_hours,
                dependencies=task.dependencies,
                required_skills=task.required_skills,
                deliverables=task.deliverables,
                verification_criteria=task.verification_criteria,
            )
            artifact_tasks.append(artifact_task)
        return artifact_tasks

    def _generate_artifact_summary(self, state: NodeGenerationState) -> dict[str, Any]:
        """Generate a summary of all artifacts for final verification."""
        return {
            "workflow_summary": {
                "total_tasks": len(state.tasks),
                "current_task_index": state.current_task_index,
                "target_node_type": (
                    state.target_node_type.value if state.target_node_type else None
                ),
                "verification_stages_completed": list(
                    state.verification_results.keys()
                ),
                "overall_validation_passed": state.overall_validation_passed,
                "errors_count": len(state.errors),
                "warnings_count": len(state.warnings),
            },
            "artifacts_generated": {
                "tasks": len(state.tasks),
                "dependencies": len(state.dependencies),
                "contracts": len(state.contracts),
                "subcontracts": len(state.subcontracts),
                "method_signatures": len(state.method_signatures),
                "required_protocols": len(state.required_protocols),
                "required_classes": len(state.required_classes),
                "has_canary_template": state.canary_clone_template is not None,
                "has_generated_code": state.generated_node_code is not None,
                "has_generated_tests": state.generated_tests is not None,
            },
            "verification_results": state.verification_results,
            "errors": state.errors,
            "warnings": state.warnings,
        }

    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow for PRD-to-Node generation."""

        workflow = StateGraph(NodeGenerationState)

        # Add workflow nodes
        workflow.add_node("decompose_prd_tasks", self._decompose_prd_tasks)
        workflow.add_node(
            "gather_infrastructure_context", self._gather_infrastructure_context
        )
        workflow.add_node(
            "verify_infrastructure_context", self._verify_infrastructure_context
        )
        workflow.add_node("analyze_dependencies", self._analyze_dependencies)
        workflow.add_node("extract_method_signatures", self._extract_method_signatures)
        workflow.add_node("lab_verify_analysis", self._lab_verify_analysis)
        workflow.add_node("generate_contracts", self._generate_contracts)
        workflow.add_node("verify_contracts", self._verify_contracts)
        workflow.add_node("clone_canary_node", self._clone_canary_node)
        workflow.add_node("verify_canary_clone", self._verify_canary_clone)
        workflow.add_node("generate_final_node", self._generate_final_node)
        workflow.add_node("final_verification", self._final_verification)

        # Define workflow edges
        workflow.add_edge(START, "decompose_prd_tasks")
        workflow.add_edge("decompose_prd_tasks", "gather_infrastructure_context")
        workflow.add_edge(
            "gather_infrastructure_context", "verify_infrastructure_context"
        )

        # Conditional edge for infrastructure verification
        workflow.add_conditional_edges(
            "verify_infrastructure_context",
            self._should_proceed_to_dependency_analysis,
            {
                "proceed": "analyze_dependencies",
                "retry": "gather_infrastructure_context",
                "fail": END,
            },
        )

        workflow.add_edge("analyze_dependencies", "extract_method_signatures")
        workflow.add_edge("extract_method_signatures", "lab_verify_analysis")

        # Conditional edge for analysis verification
        workflow.add_conditional_edges(
            "lab_verify_analysis",
            self._should_proceed_to_contracts,
            {
                "proceed": "generate_contracts",
                "retry": "analyze_dependencies",
                "fail": END,
            },
        )

        workflow.add_edge("generate_contracts", "verify_contracts")

        # Conditional edge for contract verification
        workflow.add_conditional_edges(
            "verify_contracts",
            self._should_proceed_to_canary_clone,
            {
                "proceed": "clone_canary_node",
                "retry": "generate_contracts",
                "fail": END,
            },
        )

        workflow.add_edge("clone_canary_node", "verify_canary_clone")

        # Conditional edge for canary verification
        workflow.add_conditional_edges(
            "verify_canary_clone",
            self._should_proceed_to_final_generation,
            {
                "proceed": "generate_final_node",
                "retry": "clone_canary_node",
                "fail": END,
            },
        )

        workflow.add_edge("generate_final_node", "final_verification")
        workflow.add_edge("final_verification", END)

        return workflow.compile()

    async def generate_node_from_prd(
        self,
        prd_content: str,
        target_node_type: NodeType,
        project_context: dict[str, Any] | None = None,
        generate_artifacts: bool = False,
        artifact_output_dir: str | None = None,
    ) -> dict[str, Any]:
        """
        Main entry point for PRD-to-Node generation.

        Args:
            prd_content: The Product Requirements Document content
            target_node_type: The type of node to generate
            project_context: Additional project context
            generate_artifacts: Whether to generate and save intermediate artifacts
            artifact_output_dir: Directory to save artifacts (required if generate_artifacts=True)

        Returns:
            Dictionary containing generation results, code, and metadata
        """

        initial_state = NodeGenerationState(
            prd_content=prd_content,
            target_node_type=target_node_type,
            project_context=project_context or {},
            generate_artifacts=generate_artifacts,
            artifact_output_dir=artifact_output_dir,
        )

        try:
            # Execute the workflow
            final_state = await self.workflow.ainvoke(initial_state)

            # Package results
            result = {
                "success": final_state.overall_validation_passed,
                "generated_node_code": final_state.generated_node_code,
                "generated_tests": final_state.generated_tests,
                "contracts": final_state.contracts,
                "subcontracts": final_state.subcontracts,
                "dependencies": final_state.dependencies,
                "method_signatures": final_state.method_signatures,
                "verification_results": final_state.verification_results,
                "tasks": [task.__dict__ for task in final_state.tasks],
                "errors": final_state.errors,
                "warnings": final_state.warnings,
                "metadata": {
                    "target_node_type": target_node_type.value,
                    "archon_session_id": final_state.archon_session_id,
                    "total_tasks": len(final_state.tasks),
                },
            }

            # Generate final artifact summary if enabled
            if generate_artifacts:
                final_summary = self._generate_artifact_summary(final_state)
                completion_artifact = WorkflowCompletionArtifact(
                    success=result["success"],
                    stage_summary=(
                        "Workflow completed successfully"
                        if result["success"]
                        else "Workflow completed with errors"
                    ),
                    total_processing_time=result.get("processing_time_seconds", 0.0),
                    stages_completed=list(final_state.verification_results.keys()),
                    overall_success=result["success"],
                    final_outputs=result,
                    performance_metrics={
                        "processing_time": result.get("processing_time_seconds", 0.0)
                    },
                    resource_usage={"workflow_summary": final_summary},
                )
                self._save_stage_artifacts(
                    final_state, "workflow_completion", completion_artifact
                )
                result["artifact_summary"] = final_summary
                result["artifacts_saved_to"] = artifact_output_dir

            self.logger.info(
                f"PRD-to-Node generation completed. Success: {result['success']}"
            )
            return result

        except Exception as e:
            self.logger.error(f"PRD-to-Node generation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "partial_state": initial_state.dict(),
            }

    async def generate_node_from_prd_steps(
        self,
        prd_content: str,
        target_node_type: NodeType,
        max_steps: int = 1,
        project_context: dict[str, Any] | None = None,
        generate_artifacts: bool = False,
        artifact_output_dir: str | None = None,
    ) -> PRDToNodeResult:
        """
        Step-by-step PRD-to-Node generation for testing and isolation.

        Args:
            prd_content: The Product Requirements Document content
            target_node_type: The type of node to generate
            max_steps: Maximum number of steps to execute (1-6)
                      1 = PRD Task Decomposition only
                      2 = + Infrastructure Context
                      3 = + Dependency Analysis
                      4 = + Contract Generation
                      5 = + Node Generation
                      6 = + Verification (Full Pipeline)
            project_context: Additional project context
            generate_artifacts: Whether to generate and save intermediate artifacts
            artifact_output_dir: Directory to save artifacts

        Returns:
            Dictionary containing generation results for executed steps
        """

        initial_state = NodeGenerationState(
            prd_content=prd_content,
            target_node_type=target_node_type,
            project_context=project_context or {},
            generate_artifacts=generate_artifacts,
            artifact_output_dir=artifact_output_dir,
        )

        try:
            state = initial_state
            executed_steps = []

            # Step 1: PRD Task Decomposition
            if max_steps >= 1:
                self.logger.info("Executing Step 1: PRD Task Decomposition")
                state = await self._decompose_prd_tasks(state)
                executed_steps.append("prd_task_decomposition")

                if generate_artifacts:
                    # Save Step 1 artifacts
                    task_artifacts = []
                    for task in state.tasks:
                        task_artifact = ArtifactTask(
                            task_id=task.task_id,
                            title=task.title,
                            description=task.description,
                            acceptance_criteria=task.acceptance_criteria,
                            priority=(
                                TaskPriority(task.priority)
                                if isinstance(task.priority, str)
                                else task.priority
                            ),
                            complexity=(
                                TaskComplexity(task.complexity)
                                if isinstance(task.complexity, str)
                                else task.complexity
                            ),
                            estimated_effort_hours=task.estimated_effort_hours,
                            dependencies=task.dependencies,
                            required_skills=task.required_skills,
                            deliverables=task.deliverables,
                            verification_criteria=task.verification_criteria,
                        )
                        task_artifacts.append(task_artifact)

                    decomposition_artifact = TaskDecompositionArtifact(
                        stage_summary=f"Successfully decomposed PRD into {len(state.tasks)} actionable tasks with {sum(task.estimated_effort_hours for task in state.tasks):.1f} hours estimated effort",
                        prd_content=(
                            prd_content[:500] + "..."
                            if len(prd_content) > 500
                            else prd_content
                        ),
                        total_tasks=len(state.tasks),
                        tasks=task_artifacts,
                        critical_path=[],  # Will be populated in full run
                        estimated_total_effort=sum(
                            task.estimated_effort_hours for task in state.tasks
                        ),
                        success=len(state.tasks) > 0,
                        error_message=state.errors[-1] if state.errors else None,
                    )
                    self._save_stage_artifacts(
                        state, "task_decomposition", decomposition_artifact
                    )

            # Step 2: Infrastructure Context (if requested)
            if max_steps >= 2:
                self.logger.info("Executing Step 2: Infrastructure Context")
                state = await self._gather_infrastructure_context(state)
                executed_steps.append("infrastructure_context")

            # Step 3: Dependency Analysis (if requested)
            if max_steps >= 3:
                self.logger.info("Executing Step 3: Dependency Analysis")
                state = await self._analyze_dependencies(state)
                executed_steps.append("dependency_analysis")

            # Step 4: Contract Generation (if requested)
            if max_steps >= 4:
                self.logger.info("Executing Step 4: Contract Generation")
                state = await self._generate_contracts(state)
                executed_steps.append("contract_generation")

            # Step 5: Node Generation (if requested)
            if max_steps >= 5:
                self.logger.info("Executing Step 5: Node Generation")
                state = await self._generate_final_node(state)
                executed_steps.append("node_generation")

            # Step 6: Final Verification (if requested)
            if max_steps >= 6:
                self.logger.info("Executing Step 6: Final Verification")
                state = await self._final_verification(state)
                executed_steps.append("final_verification")

            # Convert tasks to ArtifactTask format
            artifact_tasks = []
            for task in state.tasks:
                artifact_task = ArtifactTask(
                    task_id=task.task_id,
                    title=task.title,
                    description=task.description,
                    acceptance_criteria=task.acceptance_criteria,
                    priority=task.priority,
                    complexity=task.complexity,
                    estimated_effort_hours=task.estimated_effort_hours,
                    dependencies=task.dependencies,
                    required_skills=task.required_skills,
                    deliverables=task.deliverables,
                    verification_criteria=task.verification_criteria,
                )
                artifact_tasks.append(artifact_task)

            # Convert dependencies to ArtifactDependency format
            artifact_dependencies = []
            for dep in state.dependencies:
                if hasattr(dep, "name"):
                    artifact_dep = ArtifactDependency(
                        name=dep.name,
                        version=getattr(dep, "version", None),
                        dependency_type=getattr(dep, "dependency_type", "unknown"),
                        purpose=getattr(dep, "purpose", ""),
                        integration_notes=getattr(dep, "integration_notes", ""),
                    )
                    artifact_dependencies.append(artifact_dep)

            # Convert contracts to ArtifactContract format
            artifact_contracts = []
            for contract in state.contracts:
                if hasattr(contract, "contract_name"):
                    artifact_contract = ArtifactContract(
                        contract_name=contract.contract_name,
                        input_schema=getattr(contract, "input_schema", {}),
                        output_schema=getattr(contract, "output_schema", {}),
                        error_codes=getattr(contract, "error_codes", {}),
                        capabilities=getattr(contract, "capabilities", []),
                    )
                    artifact_contracts.append(artifact_contract)

            # Convert subcontracts to ArtifactContract format
            artifact_subcontracts = []
            for subcontract in state.subcontracts:
                if hasattr(subcontract, "contract_name"):
                    artifact_subcontract = ArtifactContract(
                        contract_name=subcontract.contract_name,
                        input_schema=getattr(subcontract, "input_schema", {}),
                        output_schema=getattr(subcontract, "output_schema", {}),
                        error_codes=getattr(subcontract, "error_codes", {}),
                        capabilities=getattr(subcontract, "capabilities", []),
                    )
                    artifact_subcontracts.append(artifact_subcontract)

            # Convert verification results to ArtifactVerificationResult format
            artifact_verification_results = []
            for stage, result_dict in state.verification_results.items():
                if isinstance(result_dict, dict):
                    verification_result = ArtifactVerificationResult(
                        stage=stage,
                        success=result_dict.get("success", False),
                        confidence_score=result_dict.get("confidence_score", 0.0),
                        issues_found=result_dict.get("issues_found", []),
                        recommendations=result_dict.get("recommendations", []),
                        details=result_dict.get("details", {}),
                    )
                    artifact_verification_results.append(verification_result)

            # Convert infrastructure context if present
            artifact_infra_context = None
            if state.infrastructure_context:
                artifact_infra_context = ArtifactInfrastructureContext(
                    canary_references=getattr(
                        state.infrastructure_context, "canary_references", []
                    ),
                    contract_examples=getattr(
                        state.infrastructure_context, "contract_examples", []
                    ),
                    coding_standards=getattr(
                        state.infrastructure_context, "coding_standards", {}
                    ),
                    naming_conventions=getattr(
                        state.infrastructure_context, "naming_conventions", {}
                    ),
                    deployment_patterns=getattr(
                        state.infrastructure_context, "deployment_patterns", []
                    ),
                    testing_patterns=getattr(
                        state.infrastructure_context, "testing_patterns", []
                    ),
                    architecture_patterns=getattr(
                        state.infrastructure_context, "architecture_patterns", []
                    ),
                    integration_patterns=getattr(
                        state.infrastructure_context, "integration_patterns", []
                    ),
                )

            # Create properly typed result
            result = PRDToNodeResult(
                success=len(state.errors) == 0,
                executed_steps=executed_steps,
                max_steps_requested=max_steps,
                errors=state.errors,
                warnings=state.warnings,
                tasks=artifact_tasks,
                total_tasks=len(state.tasks),
                estimated_total_effort=sum(
                    task.estimated_effort_hours for task in state.tasks
                ),
                infrastructure_context=(
                    artifact_infra_context if max_steps >= 2 else None
                ),
                dependencies=artifact_dependencies if max_steps >= 3 else [],
                method_signatures=state.method_signatures if max_steps >= 3 else [],
                required_protocols=state.required_protocols if max_steps >= 3 else [],
                contracts=artifact_contracts if max_steps >= 4 else [],
                subcontracts=artifact_subcontracts if max_steps >= 4 else [],
                generated_node_code=(
                    state.generated_node_code if max_steps >= 5 else None
                ),
                generated_tests=state.generated_tests if max_steps >= 5 else None,
                verification_results=(
                    artifact_verification_results if max_steps >= 6 else []
                ),
                overall_validation_passed=(
                    state.overall_validation_passed if max_steps >= 6 else False
                ),
                processing_time_seconds=0.0,  # Would need to track this
                artifact_files_generated=[],  # Would need to collect from artifacts
            )

            self.logger.info(
                f"PRD-to-Node step-by-step generation completed. "
                f"Steps executed: {len(executed_steps)}/{max_steps}. "
                f"Success: {result.success}"
            )
            return result

        except Exception as e:
            self.logger.error(f"PRD-to-Node step-by-step generation failed: {e}")
            return PRDToNodeResult(
                success=False,
                executed_steps=executed_steps if "executed_steps" in locals() else [],
                max_steps_requested=max_steps,
                errors=[str(e)],
            )

    # Workflow Node Implementations (Service-based)

    async def _decompose_prd_tasks(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """
        Step 1: Decompose PRD into actionable tasks using PRD Decomposition Service.
        """

        self.logger.info("Starting PRD task decomposition with service")

        try:
            # Use PRD Decomposition Service
            decomposition_result = await self.prd_decomposition_service.decompose_prd(
                prd_content=state.prd_content, project_context=state.project_context
            )

            # Convert service result to workflow state
            # Map from service DecomposedTask to workflow Task objects
            tasks = []
            for service_task in decomposition_result.tasks:
                # Convert to workflow Task format
                task = Task(
                    task_id=service_task.task_id,  # Fixed: use task_id instead of id
                    title=service_task.title,
                    description=service_task.description,
                    acceptance_criteria=service_task.acceptance_criteria,
                    priority=(
                        service_task.priority.value
                        if hasattr(service_task.priority, "value")
                        else str(service_task.priority)
                    ),
                    complexity=(
                        service_task.complexity.value
                        if hasattr(service_task.complexity, "value")
                        else str(service_task.complexity)
                    ),
                    estimated_effort_hours=service_task.estimated_effort_hours,
                    dependencies=service_task.dependencies,
                    required_skills=service_task.required_skills,
                    deliverables=service_task.deliverables,
                    verification_criteria=service_task.verification_criteria,
                    # Legacy fields for backward compatibility
                    complexity_score=0.5,  # Map from service complexity enum
                    node_type_hints=[state.target_node_type],  # Use target node type
                    estimated_effort="medium",  # Map from hours to size category
                )
                tasks.append(task)

            state.tasks = tasks
            state.current_task = tasks[0] if tasks else None
            state.current_task_index = 0

            # Store verification results
            state.verification_results[VerificationStage.TASK_DECOMPOSITION.value] = {
                "success": decomposition_result.verification_successful,
                "tasks_identified": decomposition_result.total_tasks,
                "verification_details": decomposition_result.verification_details,
                "service_used": "PRDDecompositionService",
            }

            self.logger.info(
                f"Successfully decomposed PRD into {len(tasks)} tasks using service"
            )

            # Save artifacts for verification using proper model
            task_artifact = TaskDecompositionArtifact(
                success=True,
                stage_summary=f"Decomposed PRD into {len(tasks)} actionable tasks",
                project_name=(
                    decomposition_result.project_name
                    if decomposition_result
                    else "Unknown Project"
                ),
                project_description=(
                    decomposition_result.project_description
                    if decomposition_result
                    else ""
                ),
                total_tasks=len(tasks),
                tasks=self._convert_to_artifact_tasks(tasks),
                task_dependencies=(
                    decomposition_result.task_dependencies
                    if decomposition_result
                    else {}
                ),
                critical_path=(
                    decomposition_result.critical_path if decomposition_result else []
                ),
                estimated_total_effort=(
                    decomposition_result.estimated_total_effort
                    if decomposition_result
                    else 0.0
                ),
                technology_stack=(
                    decomposition_result.technology_stack
                    if decomposition_result
                    else []
                ),
                architecture_requirements=(
                    decomposition_result.architecture_requirements
                    if decomposition_result
                    else []
                ),
                quality_requirements=(
                    decomposition_result.quality_requirements
                    if decomposition_result
                    else []
                ),
                success_metrics=(
                    decomposition_result.success_metrics if decomposition_result else []
                ),
                risks_identified=(
                    decomposition_result.risks_identified
                    if decomposition_result
                    else []
                ),
                assumptions=(
                    decomposition_result.assumptions if decomposition_result else []
                ),
            )
            self._save_stage_artifacts(state, "task_decomposition", task_artifact)

        except Exception as e:
            error_msg = f"Task decomposition failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)
            state.verification_results[VerificationStage.TASK_DECOMPOSITION.value] = {
                "success": False,
                "error": error_msg,
            }

            # Save error artifacts using proper model
            error_artifact = TaskDecompositionArtifact(
                success=False,
                error_message=error_msg,
                stage_summary="Task decomposition failed",
            )
            self._save_stage_artifacts(state, "task_decomposition", error_artifact)

        return state

    async def _gather_infrastructure_context(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """
        Step 2: Gather infrastructure context using Infrastructure Context Service.
        """

        self.logger.info("Gathering infrastructure context with service")

        try:
            # Build service request
            context_request = ModelInfrastructureContextRequest(
                target_node_type=ServiceNodeType(state.target_node_type.value),
                current_task_title=(
                    state.current_task.title if state.current_task else None
                ),
                current_task_description=(
                    state.current_task.description if state.current_task else None
                ),
                project_context=state.project_context,
            )

            # Use Infrastructure Context Service
            context_response = (
                await self.infrastructure_context_service.gather_infrastructure_context(
                    context_request
                )
            )

            if context_response.success and context_response.infrastructure_context:
                # Store infrastructure context in state
                state.infrastructure_context = context_response.infrastructure_context

                # Store in intelligence context for later use
                state.intelligence_context.update(
                    {
                        "infrastructure_context": context_response.infrastructure_context.model_dump(),
                        "completeness_score": context_response.completeness_score,
                        "missing_components": context_response.missing_components,
                        "service_used": "InfrastructureContextService",
                    }
                )

                self.logger.info(
                    f"Successfully gathered infrastructure context with completeness score: {context_response.completeness_score:.2f}"
                )
            else:
                error_msg = (
                    context_response.error_message
                    or "Infrastructure context gathering failed"
                )
                self.logger.error(error_msg)
                state.errors.append(error_msg)
                if context_response.warnings:
                    state.warnings.extend(context_response.warnings)

        except Exception as e:
            error_msg = f"Infrastructure context gathering failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)

        return state

    async def _verify_infrastructure_context(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """
        Step 3: Verify infrastructure context using Verification Service.
        """

        self.logger.info("Verifying infrastructure context with service")

        try:
            # Build verification request
            verification_request = ModelVerificationRequest(
                verification_stage="infrastructure_context",
                validation_types=["completeness", "quality"],
                target_data={
                    "infrastructure_context": (
                        state.infrastructure_context.__dict__
                        if state.infrastructure_context
                        else None
                    ),
                    "target_node_type": state.target_node_type.value,
                    "current_task": {
                        "title": (
                            state.current_task.title if state.current_task else None
                        ),
                        "description": (
                            state.current_task.description
                            if state.current_task
                            else None
                        ),
                    },
                },
                confidence_threshold=0.7,
            )

            # Use Verification Service
            verification_response = await self.verification_service.verify_component(
                verification_request
            )

            # Store verification results
            state.verification_results[
                VerificationStage.INFRASTRUCTURE_CONTEXT.value
            ] = {
                "success": verification_response.success,
                "overall_confidence": verification_response.overall_confidence,
                "total_issues": verification_response.total_issues,
                "issues_by_severity": verification_response.issues_by_severity,
                "critical_issues": verification_response.critical_issues,
                "quality_score": verification_response.quality_score,
                "compliance_score": verification_response.compliance_score,
                "next_action": verification_response.next_action_recommendation,
                "service_used": "VerificationValidationService",
            }

            # Add recommendations as warnings
            if verification_response.improvement_recommendations:
                state.warnings.extend(verification_response.improvement_recommendations)

            self.logger.info(
                f"Infrastructure context verification completed. "
                f"Success: {verification_response.success}, "
                f"Confidence: {verification_response.overall_confidence:.2f}"
            )

        except Exception as e:
            error_msg = f"Infrastructure context verification failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)
            state.verification_results[
                VerificationStage.INFRASTRUCTURE_CONTEXT.value
            ] = {
                "success": False,
                "error": error_msg,
            }

        return state

    # Conditional edge functions

    def _should_proceed_to_dependency_analysis(self, state: NodeGenerationState) -> str:
        """Decide whether to proceed to dependency analysis based on infrastructure verification."""

        verification = state.verification_results.get(
            VerificationStage.INFRASTRUCTURE_CONTEXT.value, {}
        )

        if verification.get("success", False):
            return "proceed"
        elif state.infrastructure_context_retries >= state.MAX_RETRIES:
            self.logger.warning(
                f"Infrastructure context failed after {state.MAX_RETRIES} retries, failing workflow"
            )
            return "fail"
        else:
            state.infrastructure_context_retries += 1
            self.logger.info(
                f"Retrying infrastructure context gathering (attempt {state.infrastructure_context_retries}/{state.MAX_RETRIES})"
            )
            return "retry"

    def _should_proceed_to_contracts(self, state: NodeGenerationState) -> str:
        """Decide whether to proceed to contract generation based on analysis verification."""

        verification = state.verification_results.get(
            VerificationStage.DEPENDENCY_ANALYSIS.value, {}
        )

        if verification.get("success", False):
            return "proceed"
        elif state.dependency_analysis_retries >= state.MAX_RETRIES:
            self.logger.warning(
                f"Dependency analysis failed after {state.MAX_RETRIES} retries, failing workflow"
            )
            return "fail"
        else:
            state.dependency_analysis_retries += 1
            self.logger.info(
                f"Retrying dependency analysis (attempt {state.dependency_analysis_retries}/{state.MAX_RETRIES})"
            )
            return "retry"

    def _should_proceed_to_canary_clone(self, state: NodeGenerationState) -> str:
        """Decide whether to proceed to canary cloning based on contract verification."""

        verification = state.verification_results.get(
            VerificationStage.CONTRACT_GENERATION.value, {}
        )

        if verification.get("success", False):
            return "proceed"
        elif state.contract_generation_retries >= state.MAX_RETRIES:
            self.logger.warning(
                f"Contract generation failed after {state.MAX_RETRIES} retries, failing workflow"
            )
            return "fail"
        else:
            state.contract_generation_retries += 1
            self.logger.info(
                f"Retrying contract generation (attempt {state.contract_generation_retries}/{state.MAX_RETRIES})"
            )
            return "retry"

    def _should_proceed_to_final_generation(self, state: NodeGenerationState) -> str:
        """Decide whether to proceed to final node generation based on canary verification."""

        verification = state.verification_results.get(
            VerificationStage.CANARY_CLONE.value, {}
        )

        if verification.get("success", False):
            return "proceed"
        elif state.canary_clone_retries >= state.MAX_RETRIES:
            self.logger.warning(
                f"Canary clone failed after {state.MAX_RETRIES} retries, failing workflow"
            )
            return "fail"
        else:
            state.canary_clone_retries += 1
            self.logger.info(
                f"Retrying canary clone (attempt {state.canary_clone_retries}/{state.MAX_RETRIES})"
            )
            return "retry"

    # Service-based implementations for remaining workflow nodes

    async def _analyze_dependencies(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """
        Step 4: Analyze dependencies using Dependency Analysis Service.
        """

        self.logger.info("Analyzing node dependencies with service")

        try:
            # Build dependency analysis request
            analysis_request = ModelDependencyAnalysisRequest(
                task_title=(
                    state.current_task.title if state.current_task else "Unknown Task"
                ),
                task_description=(
                    state.current_task.description
                    if state.current_task
                    else "No description"
                ),
                target_node_type=state.target_node_type.value,
                infrastructure_context=(
                    state.infrastructure_context.__dict__
                    if state.infrastructure_context
                    else {}
                ),
                project_context=state.project_context,
                analysis_depth="comprehensive",
            )

            # Use Dependency Analysis Service
            analysis_response = (
                await self.dependency_analysis_service.analyze_dependencies(
                    analysis_request
                )
            )

            if analysis_response.success:
                # Store analysis results in state
                state.dependencies = analysis_response.dependencies
                state.method_signatures = analysis_response.method_signatures
                state.required_protocols = analysis_response.protocol_requirements
                state.required_classes = analysis_response.required_classes

                self.logger.info(
                    f"Dependency analysis completed. "
                    f"Total: {analysis_response.total_dependencies}, "
                    f"Critical: {analysis_response.critical_dependencies}, "
                    f"Complexity: {analysis_response.complexity_score:.2f}"
                )
            else:
                error_msg = (
                    analysis_response.error_message or "Dependency analysis failed"
                )
                self.logger.error(error_msg)
                state.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Dependency analysis failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)

        return state

    async def _extract_method_signatures(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 5: Method signatures are now extracted by the Dependency Analysis Service."""
        self.logger.info(
            "Method signatures already extracted by dependency analysis service"
        )
        # Method signatures are now handled by the dependency analysis service
        return state

    async def _lab_verify_analysis(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 6: Verify dependency analysis using Verification Service."""
        self.logger.info("Verifying dependency analysis with service")

        try:
            # Build verification request for dependency analysis
            verification_request = ModelVerificationRequest(
                verification_stage="dependency_analysis",
                validation_types=["completeness", "correctness", "quality"],
                target_data={
                    "dependencies": state.dependencies,
                    "method_signatures": state.method_signatures,
                    "protocol_requirements": state.required_protocols,
                    "required_classes": state.required_classes,
                    "current_task": {
                        "title": (
                            state.current_task.title if state.current_task else None
                        ),
                        "description": (
                            state.current_task.description
                            if state.current_task
                            else None
                        ),
                    },
                },
                confidence_threshold=0.7,
            )

            # Use Verification Service
            verification_response = await self.verification_service.verify_component(
                verification_request
            )

            # Store verification results
            state.verification_results[VerificationStage.DEPENDENCY_ANALYSIS.value] = {
                "success": verification_response.success,
                "overall_confidence": verification_response.overall_confidence,
                "quality_score": verification_response.quality_score,
                "service_used": "VerificationValidationService",
            }

            self.logger.info(
                f"Dependency analysis verification completed. Success: {verification_response.success}"
            )

        except Exception as e:
            error_msg = f"Dependency analysis verification failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)
            state.verification_results[VerificationStage.DEPENDENCY_ANALYSIS.value] = {
                "success": False,
                "error": error_msg,
            }

        return state

    async def _generate_contracts(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 7: Generate contracts using Contract Generation Service."""
        self.logger.info("Generating contracts and subcontracts with service")

        try:
            # Build contract generation request
            contract_request = ModelContractGenerationRequest(
                task_title=(
                    state.current_task.title if state.current_task else "Unknown Task"
                ),
                task_description=(
                    state.current_task.description
                    if state.current_task
                    else "No description"
                ),
                node_type=state.target_node_type.value,
                dependencies=state.dependencies,
                method_signatures=state.method_signatures,
                infrastructure_context=(
                    state.infrastructure_context.__dict__
                    if state.infrastructure_context
                    else {}
                ),
                contract_types=["main_contract"],
                validation_level="strict",
            )

            # Use Contract Generation Service
            contract_response = (
                await self.contract_generation_service.generate_contracts(
                    contract_request
                )
            )

            if contract_response.success:
                # Store contract results in state
                state.contracts = contract_response.contracts
                state.subcontracts = contract_response.subcontracts

                self.logger.info(
                    f"Contract generation completed. "
                    f"Contracts: {contract_response.total_contracts}, "
                    f"Quality: {contract_response.quality_score:.2f}"
                )
            else:
                error_msg = (
                    contract_response.error_message or "Contract generation failed"
                )
                self.logger.error(error_msg)
                state.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Contract generation failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)

        return state

    async def _verify_contracts(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 8: Verify contracts using Verification Service."""
        self.logger.info("Verifying contracts with service")

        try:
            # Build verification request for contracts
            verification_request = ModelVerificationRequest(
                verification_stage="contract_generation",
                validation_types=["correctness", "completeness", "compliance"],
                target_data={
                    "contracts": state.contracts,
                    "subcontracts": state.subcontracts,
                    "target_node_type": state.target_node_type.value,
                },
                confidence_threshold=0.8,
            )

            # Use Verification Service
            verification_response = await self.verification_service.verify_component(
                verification_request
            )

            # Store verification results
            state.verification_results[VerificationStage.CONTRACT_GENERATION.value] = {
                "success": verification_response.success,
                "overall_confidence": verification_response.overall_confidence,
                "compliance_score": verification_response.compliance_score,
                "service_used": "VerificationValidationService",
            }

            self.logger.info(
                f"Contract verification completed. Success: {verification_response.success}"
            )

        except Exception as e:
            error_msg = f"Contract verification failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)
            state.verification_results[VerificationStage.CONTRACT_GENERATION.value] = {
                "success": False,
                "error": error_msg,
            }

        return state

    async def _clone_canary_node(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 9: Clone canary node using Node Generation Service (if canary available)."""
        self.logger.info("Preparing canary node context for generation service")

        # Select best canary template from infrastructure context
        canary_template = None
        if (
            state.infrastructure_context
            and state.infrastructure_context.canary_references
        ):
            # Select the best matching canary template
            canary_template = state.infrastructure_context.canary_references[
                0
            ]  # Simple selection

        # Store canary template for node generation step
        state.canary_clone_template = canary_template

        return state

    async def _verify_canary_clone(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 10: Verify canary clone preparation."""
        self.logger.info("Verifying canary clone preparation")

        # Basic verification of canary template selection
        success = True
        if state.canary_clone_template:
            self.logger.info("Canary template selected for node generation")
        else:
            self.logger.info(
                "No canary template available - will generate from scratch"
            )

        state.verification_results[VerificationStage.CANARY_CLONE.value] = {
            "success": success
        }
        return state

    async def _generate_final_node(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 11: Generate final node using Node Generation Service."""
        self.logger.info("Generating final node with service")

        try:
            # Build node generation request
            node_request = ModelNodeGenerationRequest(
                task_title=(
                    state.current_task.title if state.current_task else "Unknown Task"
                ),
                task_description=(
                    state.current_task.description
                    if state.current_task
                    else "No description"
                ),
                node_type=state.target_node_type.value,
                contracts=state.contracts,
                dependencies=state.dependencies,
                method_signatures=state.method_signatures,
                infrastructure_context=(
                    state.infrastructure_context.__dict__
                    if state.infrastructure_context
                    else {}
                ),
                canary_template=state.canary_clone_template,
                generation_type="final_node",
                code_quality="production",
                include_tests=True,
                include_documentation=True,
                include_deployment=True,
                project_context=state.project_context,
            )

            # Use Node Generation Service
            node_response = await self.node_generation_service.generate_node(
                node_request
            )

            if node_response.success:
                # Store node generation results in state
                state.generated_node_code = node_response.node_implementation
                state.generated_tests = node_response.generated_files

                self.logger.info(
                    f"Node generation completed. "
                    f"Files: {len(node_response.generated_files)}, "
                    f"Quality: {node_response.code_quality_metrics.get('overall_score', 0.0):.2f}"
                )
            else:
                error_msg = node_response.error_message or "Node generation failed"
                self.logger.error(error_msg)
                state.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Node generation failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)

        return state

    async def _final_verification(
        self, state: NodeGenerationState
    ) -> NodeGenerationState:
        """Step 12: Final verification using Verification Service."""
        self.logger.info("Running final verification with service")

        try:
            # Build final verification request
            verification_request = ModelVerificationRequest(
                verification_stage="final_node",
                validation_types=[
                    "correctness",
                    "completeness",
                    "quality",
                    "compliance",
                ],
                target_data={
                    "node_implementation": state.generated_node_code,
                    "generated_files": state.generated_tests,
                    "contracts": state.contracts,
                    "dependencies": state.dependencies,
                    "target_node_type": state.target_node_type.value,
                },
                confidence_threshold=0.8,
            )

            # Use Verification Service
            verification_response = await self.verification_service.verify_component(
                verification_request
            )

            # Store final verification results
            state.verification_results[VerificationStage.FINAL_NODE.value] = {
                "success": verification_response.success,
                "overall_confidence": verification_response.overall_confidence,
                "quality_score": verification_response.quality_score,
                "compliance_score": verification_response.compliance_score,
                "total_issues": verification_response.total_issues,
                "service_used": "VerificationValidationService",
            }

            # Set overall validation passed based on final verification
            state.overall_validation_passed = verification_response.success

            self.logger.info(
                f"Final verification completed. "
                f"Success: {verification_response.success}, "
                f"Quality: {verification_response.quality_score:.2f}"
            )

        except Exception as e:
            error_msg = f"Final verification failed: {e}"
            self.logger.error(error_msg)
            state.errors.append(error_msg)
            state.verification_results[VerificationStage.FINAL_NODE.value] = {
                "success": False,
                "error": error_msg,
            }
            state.overall_validation_passed = False

        return state


# Factory function for easy instantiation
def create_prd_to_node_generator(
    settings: OmniAgentSettings | None = None,
) -> PRDToNodeGenerator:
    """Create and return a PRDToNodeGenerator instance."""
    return PRDToNodeGenerator(settings)


# Example usage and testing
if __name__ == "__main__":
    import asyncio

    async def test_workflow():
        """Test the PRD-to-Node generation workflow."""

        generator = create_prd_to_node_generator()

        sample_prd = """
        # User Authentication Service

        ## Purpose
        Create a secure user authentication service that handles user registration,
        login, token management, and session validation for our microservices platform.

        ## Requirements
        1. User registration with email verification
        2. Secure password hashing and storage
        3. JWT token generation and validation
        4. Session management and refresh token handling
        5. Password reset functionality
        6. Rate limiting for security
        7. Integration with existing user database
        8. API endpoints for all authentication operations

        ## Technical Constraints
        - Must integrate with PostgreSQL user database
        - JWT tokens should expire after 24 hours
        - Refresh tokens valid for 30 days
        - Rate limiting: 5 attempts per minute per IP
        - Password requirements: 8+ chars, mixed case, numbers, symbols
        """

        # Test with artifact generation enabled
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Generating artifacts in: {temp_dir}")

            result = await generator.generate_node_from_prd(
                prd_content=sample_prd,
                target_node_type=NodeType.COMPUTE,
                project_context={
                    "database_type": "postgresql",
                    "deployment_target": "kubernetes",
                    "security_level": "high",
                },
                generate_artifacts=True,
                artifact_output_dir=temp_dir,
            )

            print(f"Generation Result: {json.dumps(result, indent=2, default=str)}")

            # Show generated artifacts
            print("\nGenerated Artifacts:")
            for file_name in os.listdir(temp_dir):
                if file_name.endswith(".json"):
                    print(f"  - {file_name}")
                    file_path = os.path.join(temp_dir, file_name)
                    try:
                        with open(file_path) as f:
                            content = json.load(f)
                            print(f"    Size: {len(json.dumps(content))} characters")
                            if "stage_summary" in content:
                                print(f"    Summary: {content['stage_summary']}")
                    except Exception as e:
                        print(f"    Error reading: {e}")

            input("Press Enter to continue (artifacts will be deleted)...")

    # Run test
    asyncio.run(test_workflow())
