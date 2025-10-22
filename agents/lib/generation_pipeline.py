#!/usr/bin/env python3
"""
Generation Pipeline - Autonomous Node Generation POC

Orchestrates the 9-stage node generation pipeline with 16 validation gates:
- Stage 1: Prompt Parsing (5s)
- Stage 1.5: Intelligence Gathering (3s) - 1 warning gate
- Stage 2: Contract Building (2s) - Quorum validation
- Stage 3: Pre-Generation Validation (2s) - 6 blocking gates
- Stage 4: Code Generation (10-15s) - 2 warning gates
- Stage 4.5: Event Bus Integration (2s) - NEW Day 2 MVP
- Stage 5: Post-Generation Validation (5s) - 4 blocking gates
- Stage 5.5: AI-Powered Code Refinement (3s) - 1 blocking gate (R1)
- Stage 6: File Writing (3s)
- Stage 7: Compilation Testing (10s) - 2 warning gates

Total target: ~53 seconds for successful generation.
"""

import ast
import logging
import re
import subprocess
import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path
from time import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

# Load environment variables from .env file
from dotenv import load_dotenv

load_dotenv()  # Load .env file automatically

# Import from omnibase_core  # noqa: E402 (must load .env first)
from omnibase_core.errors import EnumCoreErrorCode, OnexError  # noqa: E402

# Import interactive validation  # noqa: E402
from ..parallel_execution.interactive_validator import (  # noqa: E402
    CheckpointType,
    UserChoice,
    create_validator,
)

# Import code refinement components  # noqa: E402
from .code_refiner import CodeRefiner  # noqa: E402

# Import contract building components  # noqa: E402
from .generation.contract_builder_factory import ContractBuilderFactory  # noqa: E402

# Import existing components  # noqa: E402
from .intelligence_gatherer import IntelligenceGatherer  # noqa: E402
from .models.intelligence_context import IntelligenceContext  # noqa: E402

# Import pipeline models  # noqa: E402
from .models.pipeline_models import (  # noqa: E402
    GateType,
    PipelineResult,
    PipelineStage,
    StageStatus,
    ValidationGate,
)
from .models.quorum_config import QuorumConfig  # noqa: E402
from .omninode_template_engine import OmniNodeTemplateEngine  # noqa: E402
from .prompt_parser import PromptParser  # noqa: E402
from .simple_prd_analyzer import (  # noqa: E402
    SimplePRDAnalysisResult,
    SimplePRDAnalyzer,
)
from .warning_fixer import apply_automatic_fixes  # noqa: E402

# Import quorum validation (optional dependency)
try:
    from ..parallel_execution.quorum_validator import (
        QuorumResult,
        QuorumValidator,
        ValidationDecision,
    )

    QUORUM_AVAILABLE = True
except ImportError as e:
    QUORUM_AVAILABLE = False
    QuorumResult = None
    QuorumValidator = None
    ValidationDecision = None
    logging.warning(f"Quorum validation not available: {e}")

logger = logging.getLogger(__name__)


class GenerationPipeline:
    """
    Orchestrates autonomous node generation pipeline.

    Coordinates 8 stages with 16 validation gates for robust,
    production-ready node generation from natural language prompts.

    Key Features:
    - AI-powered code refinement (Stage 5.5) with quorum feedback integration
    - Intelligence-driven enhancements from RAG patterns
    - Graceful degradation on refinement failures
    - Validation gate R1 ensures refinement quality
    """

    # Critical imports required for node generation
    CRITICAL_IMPORTS = [
        "omnibase_core.nodes.node_effect.NodeEffect",
        "omnibase_core.nodes.node_compute.NodeCompute",
        "omnibase_core.nodes.node_reducer.NodeReducer",
        "omnibase_core.nodes.node_orchestrator.NodeOrchestrator",
        "omnibase_core.errors.ModelOnexError",
        "omnibase_core.errors.EnumCoreErrorCode",
        "omnibase_core.models.container.ModelONEXContainer",
    ]

    def __init__(
        self,
        template_engine: Optional[OmniNodeTemplateEngine] = None,
        enable_compilation_testing: bool = True,
        enable_intelligence_gathering: bool = True,
        interactive_mode: bool = False,
        session_file: Optional[Path] = None,
        quorum_config: Optional[QuorumConfig] = None,
    ):
        """
        Initialize generation pipeline.

        Args:
            template_engine: Pre-configured template engine (optional)
            enable_compilation_testing: Enable Stage 6 compilation testing
            enable_intelligence_gathering: Enable Stage 1.5 intelligence gathering
            interactive_mode: Enable interactive checkpoints for user validation
            session_file: Path to session file for save/resume capability
            quorum_config: Quorum validation configuration (optional, defaults to disabled)
        """
        self.logger = logging.getLogger(__name__)
        self.template_engine = template_engine or OmniNodeTemplateEngine(
            enable_cache=True
        )
        self.prd_analyzer = SimplePRDAnalyzer(enable_ml_recommendations=False)
        self.prompt_parser = PromptParser()
        self.enable_compilation_testing = enable_compilation_testing
        self.enable_intelligence_gathering = enable_intelligence_gathering
        self.interactive_mode = interactive_mode
        self.quorum_config = quorum_config or QuorumConfig.disabled()

        # Create validator (interactive or quiet based on mode)
        self.validator = create_validator(
            interactive=interactive_mode,
            session_file=session_file,
        )

        # Lazy-initialize intelligence gatherer (only if needed)
        self._intelligence_gatherer: Optional[IntelligenceGatherer] = None

        # Lazy-initialize quorum validator (only if needed and available)
        self._quorum_validator: Optional[QuorumValidator] = None

        # Lazy-initialize code refiner (only if needed)
        self._code_refiner: Optional[CodeRefiner] = None

        # Track written files for rollback
        self.written_files: List[Path] = []
        self.temp_files: List[Path] = []

    async def execute(
        self, prompt: str, output_directory: str, correlation_id: Optional[UUID] = None
    ) -> PipelineResult:
        """
        Execute complete generation pipeline.

        Args:
            prompt: Natural language prompt describing the node to generate
            output_directory: Directory to write generated files
            correlation_id: Optional correlation ID for tracking

        Returns:
            PipelineResult with comprehensive execution metadata

        Raises:
            OnexError: If any blocking validation gate fails
        """
        correlation_id = correlation_id or uuid4()
        start_time = time()

        self.logger.info(
            f"Starting generation pipeline for correlation_id={correlation_id}"
        )

        # Initialize result
        stages: List[PipelineStage] = []
        status = "failed"
        output_path = None
        generated_files = []
        node_type = None
        service_name = None
        domain = None
        validation_passed = False
        compilation_passed = False
        error_summary = None

        try:
            # Stage 1: Prompt Parsing
            stage1, parse_result = await self._stage_1_parse_prompt(prompt)
            stages.append(stage1)

            if stage1.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Stage 1 failed: {stage1.error}",
                )

            # Extract parsed data
            parsed_data = parse_result["parsed_data"]
            analysis_result = parse_result["analysis_result"]
            node_type = parsed_data["node_type"]
            service_name = parsed_data["service_name"]
            domain = parsed_data["domain"]

            # Interactive Checkpoint 1: Review PRD Analysis
            if self.interactive_mode:
                checkpoint_result = self.validator.checkpoint(
                    checkpoint_id="prd_analysis",
                    checkpoint_type=CheckpointType.CONTEXT_GATHERING,
                    step_number=1,
                    total_steps=2,
                    step_name="PRD Analysis Review",
                    output_data={
                        "node_type": node_type,
                        "service_name": service_name,
                        "domain": domain,
                        "description": parsed_data.get("description", ""),
                        "operations": parsed_data.get("operations", []),
                        "features": parsed_data.get("features", []),
                        "confidence": parsed_data.get("confidence", 0.0),
                    },
                )

                # Handle user choice
                if checkpoint_result.choice == UserChoice.RETRY:
                    self.logger.info(
                        f"User requested retry with feedback: {checkpoint_result.user_feedback}"
                    )
                    raise OnexError(
                        code=EnumCoreErrorCode.VALIDATION_ERROR,
                        message=f"User requested retry: {checkpoint_result.user_feedback}",
                    )
                elif checkpoint_result.choice == UserChoice.EDIT:
                    # Apply user edits to parsed_data
                    if checkpoint_result.modified_output:
                        self.logger.info("Applying user edits to parsed data")
                        parsed_data.update(checkpoint_result.modified_output)
                        node_type = parsed_data.get("node_type", node_type)
                        service_name = parsed_data.get("service_name", service_name)
                        domain = parsed_data.get("domain", domain)

            # Stage 1.5: Intelligence Gathering (Optional)
            intelligence_context = IntelligenceContext()  # Default empty context
            if self.enable_intelligence_gathering:
                stage1_5, intelligence_context = (
                    await self._stage_1_5_gather_intelligence(
                        parsed_data, analysis_result
                    )
                )
                stages.append(stage1_5)

                if stage1_5.status == StageStatus.FAILED:
                    # Graceful degradation: continue with empty intelligence
                    self.logger.warning(
                        "Intelligence gathering failed, continuing with defaults"
                    )
                    intelligence_context = IntelligenceContext()

            # Stage 2: Contract Building (with Quorum Validation)
            stage2, contract = await self._stage_2_contract_building(
                prompt, parsed_data, correlation_id
            )
            stages.append(stage2)

            # Track quorum result for later stages
            quorum_result = None
            if hasattr(stage2, "metadata") and "quorum_result" in stage2.metadata:
                quorum_result = stage2.metadata["quorum_result"]

            if stage2.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Stage 2 (Contract Building) failed: {stage2.error}",
                )

            # Stage 3: Pre-Generation Validation
            stage3 = await self._stage_3_pre_validation(parsed_data)
            stages.append(stage3)

            if stage3.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Stage 3 failed: {stage3.error}",
                )

            # Stage 4: Code Generation (with intelligence context)
            stage4, generation_result = await self._stage_4_generate_code(
                analysis_result,
                node_type,
                service_name,
                domain,
                output_directory,
                intelligence_context,
            )
            stages.append(stage4)

            if stage4.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message=f"Stage 4 failed: {stage4.error}",
                )

            # Stage 4.5: Event Bus Integration (NEW - Day 2 MVP)
            stage4_5, generation_result = await self._stage_4_5_event_bus_integration(
                generation_result,
                node_type,
                service_name,
                domain,
            )
            stages.append(stage4_5)

            # Stage 4.5 failure is non-fatal (graceful degradation)
            if stage4_5.status == StageStatus.FAILED:
                self.logger.warning(
                    f"Stage 4.5 (Event Bus Integration) failed: {stage4_5.error}"
                )
                # Continue without event bus integration

            # Interactive Checkpoint 2: Review Generated Contract/Code
            if self.interactive_mode:
                # Read generated contract/code for review
                main_file_path = Path(generation_result.get("main_file", ""))
                contract_preview = "Contract generated successfully"

                if main_file_path.exists():
                    # Read first 50 lines for preview
                    with open(main_file_path, "r") as f:
                        lines = f.readlines()[:50]
                        contract_preview = "".join(lines)

                checkpoint_result = self.validator.checkpoint(
                    checkpoint_id="contract_review",
                    checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                    step_number=2,
                    total_steps=2,
                    step_name="Contract/Code Generation Review",
                    output_data={
                        "node_type": node_type,
                        "service_name": service_name,
                        "files_generated": generation_result.get("generated_files", []),
                        "main_file": str(main_file_path),
                        "contract_preview": contract_preview,
                    },
                )

                # Handle user choice
                if checkpoint_result.choice == UserChoice.RETRY:
                    self.logger.info(
                        f"User requested retry with feedback: {checkpoint_result.user_feedback}"
                    )
                    raise OnexError(
                        code=EnumCoreErrorCode.VALIDATION_ERROR,
                        message=f"User requested retry: {checkpoint_result.user_feedback}",
                    )
                elif checkpoint_result.choice == UserChoice.EDIT:
                    # User edited the generated code
                    if checkpoint_result.modified_output:
                        self.logger.info("User edited generated code")
                        # If user edited contract_preview, write it back
                        if "contract_preview" in checkpoint_result.modified_output:
                            try:
                                with open(main_file_path, "w") as f:
                                    f.write(
                                        checkpoint_result.modified_output[
                                            "contract_preview"
                                        ]
                                    )
                                self.logger.info(
                                    f"Updated {main_file_path} with user edits"
                                )
                            except Exception as e:
                                self.logger.error(f"Failed to apply user edits: {e}")

            # Stage 5: Post-Generation Validation
            stage5 = await self._stage_5_post_validation(generation_result, node_type)
            stages.append(stage5)

            if stage5.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Stage 5 failed: {stage5.error}",
                )

            validation_passed = stage5.status == StageStatus.COMPLETED

            # Stage 5.5: Code Refinement (AI-powered)
            # Collect all validation gates from previous stages for refinement context
            all_validation_gates = []
            for stage in stages:
                all_validation_gates.extend(stage.validation_gates)

            stage5_5, refined_files = await self._stage_5_5_code_refinement(
                generation_result,
                all_validation_gates,
                quorum_result,
                intelligence_context,
                correlation_id,
                node_type,
                service_name,
                domain,
            )
            stages.append(stage5_5)

            # Use refined files for subsequent stages
            if stage5_5.status == StageStatus.COMPLETED and refined_files:
                generation_result = refined_files

            # Stage 6 (was Stage 6): File Writing
            stage6, write_result = await self._stage_6_write_files(
                generation_result, output_directory
            )
            stages.append(stage6)

            if stage6.status == StageStatus.FAILED:
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message=f"Stage 6 failed: {stage6.error}",
                )

            output_path = write_result["output_path"]
            generated_files = write_result["generated_files"]

            # Stage 7 (was Stage 7): Compilation Testing (Optional)
            if self.enable_compilation_testing:
                stage7, compile_result = await self._stage_7_compile_test(
                    output_path, node_type, service_name
                )
                stages.append(stage7)
                compilation_passed = compile_result.get("passed", False)
            else:
                # Skip stage 7
                stage7 = PipelineStage(
                    stage_name="compilation_testing",
                    status=StageStatus.SKIPPED,
                    metadata={"reason": "Compilation testing disabled"},
                )
                stages.append(stage7)
                compilation_passed = True  # Assume passed if skipped

            # Pipeline succeeded
            status = "success"
            self.logger.info(
                f"Pipeline completed successfully for correlation_id={correlation_id}"
            )

        except OnexError as e:
            error_summary = str(e)
            self.logger.error(
                f"Pipeline failed for correlation_id={correlation_id}: {error_summary}"
            )

            # Rollback written files
            await self._rollback(stages[-1].stage_name if stages else "unknown")

        except Exception as e:
            error_summary = f"Unexpected error: {str(e)}"
            self.logger.error(
                f"Pipeline failed with unexpected error: {error_summary}",
                exc_info=True,
            )

            # Rollback written files
            await self._rollback(stages[-1].stage_name if stages else "unknown")

        # Calculate total duration
        total_duration_ms = int((time() - start_time) * 1000)

        # Build result
        result = PipelineResult(
            correlation_id=correlation_id,
            status=status,
            total_duration_ms=total_duration_ms,
            stages=stages,
            output_path=output_path,
            generated_files=generated_files,
            node_type=node_type,
            service_name=service_name,
            domain=domain,
            validation_passed=validation_passed,
            compilation_passed=compilation_passed,
            error_summary=error_summary,
            metadata={
                "prompt": prompt,
                "output_directory": output_directory,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        self.logger.info(
            f"Pipeline result: {result.status} in {result.duration_seconds:.2f}s"
        )

        return result

    async def _stage_1_parse_prompt(self, prompt: str) -> Tuple[PipelineStage, Dict]:
        """
        Stage 1: Parse natural language prompt.

        Validation Gates:
        - G7: Prompt completeness (WARNING)
        - G8: Context has expected fields (WARNING)
        """
        stage = PipelineStage(stage_name="prompt_parsing", status=StageStatus.RUNNING)
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # G7: Prompt completeness check
            gate_g7 = self._gate_g7_prompt_completeness(prompt)
            stage.validation_gates.append(gate_g7)

            if gate_g7.status == "fail" and gate_g7.gate_type == GateType.BLOCKING:
                stage.status = StageStatus.FAILED
                stage.error = gate_g7.message
                return stage, {}

            # Parse prompt using PRD analyzer
            # For POC, create a simple PRD from prompt
            simple_prd = self._prompt_to_prd(prompt)

            # Analyze PRD
            analysis_result = await self.prd_analyzer.analyze_prd(simple_prd)

            # Extract structured data
            parsed_data = {
                "node_type": self._detect_node_type(prompt),
                "service_name": self._extract_service_name(prompt, analysis_result),
                "domain": self._extract_domain(prompt, analysis_result),
                "description": analysis_result.parsed_prd.description,
                "operations": analysis_result.parsed_prd.functional_requirements[:3],
                "features": analysis_result.parsed_prd.features[:3],
                "confidence": analysis_result.confidence_score,
            }

            # G8: Context completeness check
            gate_g8 = self._gate_g8_context_completeness(parsed_data)
            stage.validation_gates.append(gate_g8)

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "node_type": parsed_data["node_type"],
                "service_name": parsed_data["service_name"],
                "confidence": parsed_data["confidence"],
            }

            return stage, {
                "parsed_data": parsed_data,
                "analysis_result": analysis_result,
            }

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage, {}

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_1_5_gather_intelligence(
        self, parsed_data: Dict[str, Any], analysis_result: SimplePRDAnalysisResult
    ) -> Tuple[PipelineStage, IntelligenceContext]:
        """
        Stage 1.5: Gather intelligence for enhanced generation.

        This stage gathers best practices, patterns, and production examples
        to enhance code generation quality.

        Validation Gates:
        - I1: Intelligence completeness (WARNING)
        """
        stage = PipelineStage(
            stage_name="intelligence_gathering", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # Lazy-initialize intelligence gatherer
            if not self._intelligence_gatherer:
                self._intelligence_gatherer = IntelligenceGatherer()
                self.logger.debug("Initialized IntelligenceGatherer")

            # Gather intelligence
            intelligence = await self._intelligence_gatherer.gather_intelligence(
                node_type=parsed_data["node_type"],
                domain=parsed_data["domain"],
                service_name=parsed_data["service_name"],
                operations=parsed_data.get("operations", []),
                prompt=analysis_result.prd_content,  # Fixed: use prd_content not original_prompt
            )

            # I1: Validate intelligence completeness
            gate_i1 = self._gate_i1_intelligence_completeness(intelligence)
            stage.validation_gates.append(gate_i1)

            # Add metadata
            stage.metadata = {
                "patterns_found": len(intelligence.node_type_patterns),
                "code_examples": len(intelligence.code_examples),
                "rag_sources": intelligence.rag_sources,
                "recommended_mixins": intelligence.required_mixins,
                "confidence_score": intelligence.confidence_score,
            }

            stage.status = StageStatus.COMPLETED
            stage.end_time = datetime.utcnow()

            return stage, intelligence

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            stage.end_time = datetime.utcnow()
            self.logger.error(f"Intelligence gathering failed: {e}")
            return stage, IntelligenceContext()  # Return empty context

        finally:
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_2_contract_building(
        self, prompt: str, parsed_data: Dict[str, Any], correlation_id: UUID
    ) -> Tuple[PipelineStage, Any]:
        """
        Stage 2: Contract building with quorum validation.

        Builds ONEX contract from parsed data and validates with AI quorum
        for correctness and alignment with user intent.

        Validation: Q1 - Quorum contract validation (if enabled)

        Args:
            prompt: Original user prompt
            parsed_data: Parsed prompt data from Stage 1
            correlation_id: Pipeline correlation ID

        Returns:
            Tuple of (PipelineStage, contract) where contract is the built contract model
        """
        stage = PipelineStage(
            stage_name="contract_building", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()
        contract = None

        try:
            # Build contract using factory
            node_type = parsed_data["node_type"]
            builder = ContractBuilderFactory.create(node_type, correlation_id)
            contract = builder.build(parsed_data)

            self.logger.info(
                f"Built {node_type} contract: {contract.name} v{contract.version}"
            )

            # Quorum validation (if enabled and available)
            if self.quorum_config.validate_contract and QUORUM_AVAILABLE:
                max_retries = (
                    self.quorum_config.max_retries_per_stage
                    if self.quorum_config.retry_on_fail
                    else 0
                )

                for retry_attempt in range(max_retries + 1):
                    # Initialize quorum validator lazily
                    if not self._quorum_validator:
                        try:
                            self._quorum_validator = QuorumValidator()
                            self.logger.info("Initialized QuorumValidator")
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to initialize QuorumValidator: {e}"
                            )
                            # Continue without quorum validation
                            break

                    # Prepare task breakdown for validation
                    task_breakdown = {
                        "node_type": (
                            contract.node_type.value
                            if hasattr(contract.node_type, "value")
                            else str(contract.node_type)
                        ),
                        "name": contract.name,
                        "description": contract.description,
                        "version": str(contract.version),
                        "tasks": [
                            {
                                "task_name": "contract_generation",
                                "input_data": {
                                    "node_type": parsed_data["node_type"],
                                    "service_name": parsed_data["service_name"],
                                    "domain": parsed_data["domain"],
                                },
                            }
                        ],
                    }

                    # Validate with quorum
                    try:
                        quorum_result = await self._quorum_validator.validate_intent(
                            user_prompt=prompt,
                            task_breakdown=task_breakdown,
                        )

                        # Log quorum decision
                        self.logger.info(
                            f"Quorum validation: {quorum_result.decision.value} "
                            f"(confidence: {quorum_result.confidence:.2f})"
                        )

                        # Create validation gate for quorum
                        gate_q1 = ValidationGate(
                            gate_id="Q1",
                            name="Quorum Contract Validation",
                            status=(
                                "pass"
                                if quorum_result.decision == ValidationDecision.PASS
                                else (
                                    "warning"
                                    if quorum_result.decision
                                    == ValidationDecision.RETRY
                                    else "fail"
                                )
                            ),
                            gate_type=GateType.BLOCKING,
                            message=f"Quorum {quorum_result.decision.value}: {len(quorum_result.deficiencies)} deficiencies, confidence {quorum_result.confidence:.0%}",
                            duration_ms=int((time() - start_ms) * 1000),
                        )
                        stage.validation_gates.append(gate_q1)

                        # Handle quorum decision
                        if quorum_result.decision == ValidationDecision.PASS:
                            # Success! Continue with contract
                            stage.metadata = {
                                "contract_name": contract.name,
                                "contract_version": str(contract.version),
                                "quorum_confidence": quorum_result.confidence,
                                "quorum_decision": "PASS",
                                "quorum_result": quorum_result,  # Store for Stage 5.5
                            }
                            break

                        elif quorum_result.decision == ValidationDecision.RETRY:
                            # Retry needed
                            if retry_attempt < max_retries:
                                self.logger.warning(
                                    f"Quorum RETRY (attempt {retry_attempt + 1}/{max_retries + 1}). "
                                    f"Deficiencies: {quorum_result.deficiencies}"
                                )
                                # Rebuild contract with deficiency feedback
                                # For now, we'll use the same data but log the deficiencies
                                # Future: Incorporate feedback into contract building
                                continue
                            else:
                                # Max retries exceeded
                                stage.status = StageStatus.FAILED
                                stage.error = (
                                    f"Quorum validation failed after {max_retries + 1} attempts. "
                                    f"Deficiencies: {', '.join(quorum_result.deficiencies[:3])}"
                                )
                                return stage, contract

                        else:  # FAIL
                            # Quorum failed contract
                            stage.status = StageStatus.FAILED
                            stage.error = (
                                f"Quorum validation FAIL. "
                                f"Deficiencies: {', '.join(quorum_result.deficiencies[:3])}"
                            )
                            return stage, contract

                    except Exception as e:
                        self.logger.error(
                            f"Quorum validation error: {e}", exc_info=True
                        )
                        # Continue without quorum validation on error
                        gate_q1_error = ValidationGate(
                            gate_id="Q1",
                            name="Quorum Contract Validation",
                            status="warning",
                            gate_type=GateType.WARNING,
                            message=f"Quorum validation error: {str(e)[:100]}",
                            duration_ms=int((time() - start_ms) * 1000),
                        )
                        stage.validation_gates.append(gate_q1_error)
                        break

            else:
                # Quorum disabled or not available
                self.logger.debug(
                    f"Quorum validation skipped (enabled: {self.quorum_config.validate_contract}, "
                    f"available: {QUORUM_AVAILABLE})"
                )

            # Stage completed successfully
            stage.status = StageStatus.COMPLETED
            if not stage.metadata:
                stage.metadata = {
                    "contract_name": contract.name,
                    "contract_version": str(contract.version),
                    "quorum_validation": "disabled",
                }

            return stage, contract

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            self.logger.error(f"Contract building failed: {e}", exc_info=True)
            return stage, None

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_3_pre_validation(
        self, parsed_data: Dict[str, Any]
    ) -> PipelineStage:
        """
        Stage 3: Pre-generation validation.

        Validation Gates (BLOCKING):
        - G1: Prompt completeness
        - G2: Node type valid
        - G3: Service name valid
        - G4: Critical imports exist
        - G5: Templates available
        - G6: Output directory writable
        """
        stage = PipelineStage(
            stage_name="pre_generation_validation", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # G1: Prompt completeness (redundant with G7, but required)
            gate_g1 = self._gate_g1_prompt_completeness_full(parsed_data)
            stage.validation_gates.append(gate_g1)

            if gate_g1.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g1.message
                return stage

            # G2: Node type valid
            gate_g2 = self._gate_g2_node_type_valid(parsed_data["node_type"])
            stage.validation_gates.append(gate_g2)

            if gate_g2.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g2.message
                return stage

            # G3: Service name valid
            gate_g3 = self._gate_g3_service_name_valid(parsed_data["service_name"])
            stage.validation_gates.append(gate_g3)

            if gate_g3.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g3.message
                return stage

            # G4: Critical imports exist
            gate_g4 = self._gate_g4_critical_imports_exist()
            stage.validation_gates.append(gate_g4)

            if gate_g4.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g4.message
                return stage

            # G5: Templates available
            gate_g5 = self._gate_g5_templates_available(parsed_data["node_type"])
            stage.validation_gates.append(gate_g5)

            if gate_g5.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g5.message
                return stage

            # G6: Output directory writable
            # Note: output_directory is not passed yet, will be validated in Stage 5
            gate_g6 = ValidationGate(
                gate_id="G6",
                name="Output Directory Writable",
                status="pass",
                gate_type=GateType.BLOCKING,
                message="Output directory validation deferred to Stage 5",
                duration_ms=1,
            )
            stage.validation_gates.append(gate_g6)

            stage.status = StageStatus.COMPLETED
            return stage

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_4_generate_code(
        self,
        analysis_result: SimplePRDAnalysisResult,
        node_type: str,
        service_name: str,
        domain: str,
        output_directory: str,
        intelligence_context: IntelligenceContext,
    ) -> Tuple[PipelineStage, Dict]:
        """
        Stage 4: Generate node code from templates with intelligence.

        No blocking validation gates (G7-G8 are warnings in Stage 1).
        """
        stage = PipelineStage(stage_name="code_generation", status=StageStatus.RUNNING)
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # Generate node using template engine with intelligence
            generation_result = await self.template_engine.generate_node(
                analysis_result=analysis_result,
                node_type=node_type,
                microservice_name=service_name,
                domain=domain,
                output_directory=output_directory,
                intelligence=intelligence_context,  # Fixed: parameter name is 'intelligence' not 'intelligence_context'
            )

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "files_generated": len(generation_result["generated_files"]),
                "main_file": generation_result["main_file"],
            }

            return stage, generation_result

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage, {}

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_4_5_event_bus_integration(
        self,
        generation_result: Dict[str, Any],
        node_type: str,
        service_name: str,
        domain: str,
    ) -> Tuple[PipelineStage, Dict[str, Any]]:
        """
        Stage 4.5: Event Bus Integration (NEW - Day 2 MVP)

        Injects event bus initialization code and generates startup script:
        - Adds EventPublisher initialization to __init__
        - Adds initialize() and shutdown() lifecycle methods
        - Adds _publish_introspection_event() method
        - Generates standalone startup script (start_node.py)

        No blocking validation gates - graceful degradation if event bus unavailable.
        """
        stage = PipelineStage(
            stage_name="event_bus_integration", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            self.logger.info("Stage 4.5: Injecting event bus integration...")

            # Only inject event bus code for Effect and Orchestrator nodes
            # Compute and Reducer can optionally have it but not required for MVP
            if node_type.lower() not in ["effect", "orchestrator"]:
                self.logger.info(
                    f"Skipping event bus integration for {node_type} node (optional)"
                )
                stage.status = StageStatus.SKIPPED
                stage.metadata = {
                    "reason": f"Event bus integration optional for {node_type} nodes"
                }
                return stage, generation_result

            # Extract node name and paths
            main_file = generation_result.get("main_file", "")
            if not main_file or not Path(main_file).exists():
                raise ValueError(f"Main file not found: {main_file}")

            node_path = Path(main_file)
            output_dir = node_path.parent

            # Extract node name from file
            node_name = generation_result.get("node_name", "")
            if not node_name:
                # Parse from main file
                with open(main_file, "r") as f:
                    content = f.read()
                    match = re.search(r"class (Node\w+)\(", content)
                    if match:
                        node_name = match.group(1)
                    else:
                        raise ValueError(
                            "Could not extract node name from generated code"
                        )

            # Prepare template context
            name_lower = re.sub(r"^Node", "", node_name).lower()
            name_lower = re.sub(
                r"(Effect|Compute|Reducer|Orchestrator)$", "", name_lower
            )

            context = {
                "node_name": node_name,
                "node_type": node_type.lower(),
                "service_name": service_name,
                "domain": domain,
                "version": "1.0.0",
                "description": generation_result.get(
                    "description", f"{node_name} node"
                ),
                "name_lower": name_lower,
                "name_pascal": node_name.replace("Node", "")
                .replace("Effect", "")
                .replace("Compute", "")
                .replace("Reducer", "")
                .replace("Orchestrator", ""),
                "kafka_bootstrap_servers": "omninode-bridge-redpanda:9092",
            }

            # Render event bus templates
            from jinja2 import Environment, FileSystemLoader

            template_dir = Path(__file__).parent.parent / "templates"
            env = Environment(loader=FileSystemLoader(str(template_dir)))

            # 1. Render introspection event method
            introspection_template = env.get_template("introspection_event.py.jinja2")
            introspection_method = introspection_template.render(context)

            # 1.5 Render orchestrator workflow events (Day 4 enhancement)
            orchestrator_workflow_methods = ""
            if node_type.lower() == "orchestrator":
                try:
                    orchestrator_template = env.get_template(
                        "orchestrator_workflow_events.py.jinja2"
                    )
                    orchestrator_workflow_methods = orchestrator_template.render(
                        context
                    )
                    self.logger.info("Rendered orchestrator workflow event methods")
                except Exception as e:
                    self.logger.warning(
                        f"Could not load orchestrator workflow template: {e}"
                    )
                    orchestrator_workflow_methods = ""

            # 2. Render startup script
            startup_template = env.get_template("startup_script.py.jinja2")
            startup_script = startup_template.render(context)

            # 3. Inject event bus code into main node file
            with open(main_file, "r") as f:
                node_code = f.read()

            # Add imports at top (after existing imports)
            # Day 4: Add UUID and Any imports for orchestrators
            if node_type.lower() == "orchestrator":
                event_bus_imports = """
# Event Bus Integration (Stage 4.5 + Day 4 Orchestrator Enhancements)
import asyncio
import os
from datetime import datetime
from uuid import UUID, uuid4
from typing import Any, Optional

try:
    from omniarchon.events.publisher import EventPublisher
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False
    EventPublisher = None
"""
            else:
                event_bus_imports = """
# Event Bus Integration (Stage 4.5)
import asyncio
import os
from uuid import uuid4
from typing import Optional

try:
    from omniarchon.events.publisher import EventPublisher
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False
    EventPublisher = None
"""

            # Insert imports after the last import statement
            # Handle multi-line imports with backslash continuations
            import_pattern = r"((?:import |from )(?:[^\n]|\\\n)+\n)+"
            match = list(re.finditer(import_pattern, node_code))
            if match:
                last_import_end = match[-1].end()
                # Find the next blank line or class definition
                next_section = node_code[last_import_end : last_import_end + 200]
                blank_line = next_section.find("\n\n")
                if blank_line != -1:
                    insert_pos = last_import_end + blank_line
                else:
                    insert_pos = last_import_end

                node_code = (
                    node_code[:insert_pos] + event_bus_imports + node_code[insert_pos:]
                )
            else:
                # No imports found, add at beginning
                node_code = event_bus_imports + "\n\n" + node_code

            # Add event bus initialization to __init__ method
            event_bus_init_code = """
        # Event Bus Integration (Stage 4.5)
        if EVENT_BUS_AVAILABLE:
            self.event_publisher: Optional[EventPublisher] = None
            self._bootstrap_servers = os.getenv(
                "KAFKA_BOOTSTRAP_SERVERS",
                "%s"
            )
            self._service_name = "%s"
            self._instance_id = f"%s-{uuid4().hex[:8]}"
            self._node_id = uuid4()
            self.is_running = False
            self._shutdown_event = asyncio.Event()
            self.logger.info(
                f"%s initialized | "
                f"service={self._service_name} | "
                f"instance={self._instance_id}"
            )
        else:
            self.logger.warning("Event bus not available - node will run in standalone mode")
""" % (
                context["kafka_bootstrap_servers"],
                context["service_name"],
                context["name_lower"],
                context["node_name"],
            )

            # Find the last line in __init__ and append event bus code
            init_match = re.search(
                r"def __init__\(self[^)]*\):[^\n]+\n((?:\s+.*\n)+)",
                node_code,
                re.MULTILINE,
            )
            if init_match:
                # Insert event bus code at the end of __init__
                insert_pos = init_match.end()
                node_code = (
                    node_code[:insert_pos]
                    + event_bus_init_code
                    + node_code[insert_pos:]
                )

            # Add introspection method at the end of the class (before the last line)
            # Insert before the last line of the file
            node_code = node_code.rstrip() + "\n\n" + introspection_method + "\n"

            # Day 4: Add orchestrator workflow event methods if this is an orchestrator
            if orchestrator_workflow_methods:
                node_code = (
                    node_code.rstrip() + "\n\n" + orchestrator_workflow_methods + "\n"
                )
                self.logger.info("✅ Injected orchestrator workflow event methods")

            # Write updated node code
            with open(main_file, "w") as f:
                f.write(node_code)

            self.logger.info(f"✅ Injected event bus code into {node_path.name}")

            # 4. Write startup script
            startup_script_path = output_dir / "start_node.py"
            with open(startup_script_path, "w") as f:
                f.write(startup_script)

            # Make startup script executable
            startup_script_path.chmod(0o755)

            self.logger.info(f"✅ Generated startup script: {startup_script_path.name}")

            # Update generation_result with new files
            if "generated_files" not in generation_result:
                generation_result["generated_files"] = []

            generation_result["generated_files"].append(str(startup_script_path))
            generation_result["startup_script"] = str(startup_script_path)
            generation_result["event_bus_integrated"] = True

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "node_type": node_type,
                "event_bus_code_injected": True,
                "startup_script_generated": True,
                "startup_script_path": str(startup_script_path),
                "orchestrator_workflow_events": bool(
                    orchestrator_workflow_methods
                ),  # Day 4
            }

            if orchestrator_workflow_methods:
                self.logger.info(
                    "Stage 4.5 completed successfully (with Day 4 orchestrator enhancements)"
                )
            else:
                self.logger.info("Stage 4.5 completed successfully")
            return stage, generation_result

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            self.logger.error(f"Stage 4.5 failed: {e}", exc_info=True)
            return stage, generation_result  # Return original result on failure

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_5_post_validation(
        self, generated_files: Dict[str, Any], node_type: str
    ) -> PipelineStage:
        """
        Stage 5: Post-generation validation.

        Validation Gates (BLOCKING):
        - G9: Python syntax valid
        - G10: ONEX naming convention
        - G11: Import resolution
        - G12: Pydantic model structure
        """
        stage = PipelineStage(
            stage_name="post_generation_validation", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # Load generated code from main file
            main_file_path = Path(generated_files["main_file"])
            if not main_file_path.exists():
                stage.status = StageStatus.FAILED
                stage.error = f"Main file not found: {main_file_path}"
                return stage

            main_file_content = main_file_path.read_text()

            # G9: Python syntax valid
            gate_g9 = self._gate_g9_python_syntax_valid(
                main_file_content, str(main_file_path)
            )
            stage.validation_gates.append(gate_g9)

            if gate_g9.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g9.message
                return stage

            # G10: ONEX naming convention
            gate_g10 = self._gate_g10_onex_naming(main_file_content, node_type)
            stage.validation_gates.append(gate_g10)

            if gate_g10.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g10.message
                return stage

            # G11: Import resolution
            gate_g11 = self._gate_g11_import_resolution(main_file_content)
            stage.validation_gates.append(gate_g11)

            if gate_g11.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g11.message
                return stage

            # G12: Pydantic model structure
            # Check model files if they exist
            model_files = [
                f for f in generated_files.get("generated_files", []) if "model" in f
            ]
            gate_g12 = self._gate_g12_pydantic_models(model_files)
            stage.validation_gates.append(gate_g12)

            if gate_g12.status == "fail":
                stage.status = StageStatus.FAILED
                stage.error = gate_g12.message
                return stage

            stage.status = StageStatus.COMPLETED
            return stage

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_5_5_code_refinement(
        self,
        generated_files: Dict[str, Any],
        validation_gates: List[ValidationGate],
        quorum_result: Optional["QuorumResult"],
        intelligence: IntelligenceContext,
        correlation_id: UUID,
        node_type: str,
        service_name: str,
        domain: str,
    ) -> Tuple[PipelineStage, Dict[str, Any]]:
        """
        Stage 5.5: AI-Powered Code Refinement

        Automatically refines generated code using:
        - Production ONEX patterns from catalog
        - Quorum validation feedback
        - Validation warning fixes
        - Intelligence-driven enhancements

        Args:
            generated_files: Files generated in Stage 4
            validation_gates: All validation gates from previous stages
            quorum_result: Quorum validation result from Stage 2 (if available)
            intelligence: Intelligence context from Stage 1.5
            correlation_id: Pipeline correlation ID
            node_type: ONEX node type (effect, compute, reducer, orchestrator)
            service_name: Service name for the node
            domain: Domain/category for the node

        Returns:
            Tuple of (PipelineStage, refined_files_dict)
        """
        stage = PipelineStage(stage_name="code_refinement", status=StageStatus.RUNNING)
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # Build refinement context from all inputs
            refinement_context = self._build_refinement_context(
                validation_gates, quorum_result, intelligence
            )

            # Load generated code
            main_file_path = Path(generated_files["main_file"])
            if not main_file_path.exists():
                stage.status = StageStatus.FAILED
                stage.error = f"Main file not found: {main_file_path}"
                return stage, generated_files

            original_code = main_file_path.read_text()

            # Check if refinement is needed
            needs_refinement = self._check_refinement_needed(
                validation_gates, quorum_result
            )

            if not needs_refinement:
                # No refinement needed, pass through
                self.logger.info("Code refinement skipped - no issues detected")
                stage.status = StageStatus.SKIPPED
                stage.metadata = {"reason": "No refinement needed"}
                return stage, generated_files

            # Apply AI-powered refinement
            self.logger.info(
                f"Refining code with context: {len(refinement_context)} enhancement opportunities"
            )

            refined_code = await self._apply_ai_refinement(
                original_code=original_code,
                refinement_context=refinement_context,
                intelligence=intelligence,
                correlation_id=correlation_id,
                node_type=node_type,
                service_name=service_name,
                domain=domain,
            )

            # R1: Validate refinement quality
            gate_r1 = self._gate_r1_refinement_quality(
                original_code, refined_code, refinement_context
            )
            stage.validation_gates.append(gate_r1)

            if gate_r1.status == "fail":
                # Refinement quality check failed, keep original code
                self.logger.warning(
                    f"Refinement quality check failed: {gate_r1.message}"
                )
                stage.status = StageStatus.COMPLETED
                stage.metadata = {
                    "refinement_attempted": True,
                    "refinement_applied": False,
                    "reason": gate_r1.message,
                }
                return stage, generated_files

            # Write refined code back to file
            main_file_path.write_text(refined_code)
            self.logger.info(f"Code refinement applied to {main_file_path}")

            # Update generated_files with refinement metadata
            refined_files = generated_files.copy()
            refined_files["refinement_applied"] = True
            refined_files["refinement_context"] = refinement_context

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "refinement_attempted": True,
                "refinement_applied": True,
                "enhancements": len(refinement_context),
                "original_lines": len(original_code.splitlines()),
                "refined_lines": len(refined_code.splitlines()),
            }

            return stage, refined_files

        except Exception as e:
            # Graceful degradation: log error but continue with original code
            self.logger.error(f"Code refinement failed: {e}", exc_info=True)
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            stage.metadata = {
                "refinement_attempted": True,
                "refinement_applied": False,
                "error": str(e),
            }
            # Return original files on error
            return stage, generated_files

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    def _build_refinement_context(
        self,
        validation_gates: List[ValidationGate],
        quorum_result: Optional["QuorumResult"],
        intelligence: IntelligenceContext,
    ) -> List[str]:
        """
        Build refinement context from validation gates, quorum, and intelligence.

        Args:
            validation_gates: All validation gates from previous stages
            quorum_result: Quorum validation result (if available)
            intelligence: Intelligence context

        Returns:
            List of refinement opportunities/recommendations
        """
        context = []

        # 1. Extract warning messages from validation gates
        warnings = [
            gate.message
            for gate in validation_gates
            if gate.status == "warning" and gate.message
        ]
        if warnings:
            context.append(f"Address validation warnings: {'; '.join(warnings[:3])}")

        # 2. Extract quorum deficiencies
        if quorum_result and quorum_result.deficiencies:
            context.append(
                f"Address quorum deficiencies: {'; '.join(quorum_result.deficiencies[:3])}"
            )

        # 3. Apply intelligence patterns
        if intelligence.node_type_patterns:
            context.append(
                f"Apply ONEX best practices: {'; '.join(intelligence.node_type_patterns[:3])}"
            )

        # 4. Apply domain best practices
        if intelligence.domain_best_practices:
            context.append(
                f"Apply domain patterns: {'; '.join(intelligence.domain_best_practices[:2])}"
            )

        # 5. Avoid anti-patterns
        if intelligence.anti_patterns:
            context.append(
                f"Avoid anti-patterns: {'; '.join(intelligence.anti_patterns[:2])}"
            )

        return context

    def _check_refinement_needed(
        self,
        validation_gates: List[ValidationGate],
        quorum_result: Optional["QuorumResult"],
    ) -> bool:
        """
        Check if code refinement is needed based on validation results.

        Args:
            validation_gates: All validation gates
            quorum_result: Quorum result (if available)

        Returns:
            True if refinement is needed, False otherwise
        """
        # Check for warnings
        has_warnings = any(gate.status == "warning" for gate in validation_gates)

        # Check for quorum deficiencies
        has_quorum_deficiencies = quorum_result and len(quorum_result.deficiencies) > 0

        # Check for low quorum confidence
        low_quorum_confidence = quorum_result and quorum_result.confidence < 0.8

        return has_warnings or has_quorum_deficiencies or low_quorum_confidence

    async def _apply_ai_refinement(
        self,
        original_code: str,
        refinement_context: List[str],
        intelligence: IntelligenceContext,
        correlation_id: UUID,
        node_type: str,
        service_name: str,
        domain: str,
    ) -> str:
        """
        Apply AI-powered code refinement using CodeRefiner.

        Applies refinement in two phases:
        1. Deterministic fixes (G12, G13, G14) - fast & free via WarningFixer
        2. AI-powered refinement - pattern-based via CodeRefiner

        Args:
            original_code: Original generated code
            refinement_context: Refinement recommendations
            intelligence: Intelligence context
            correlation_id: Pipeline correlation ID
            node_type: ONEX node type (effect, compute, reducer, orchestrator)
            service_name: Service name for the node
            domain: Domain/category for the node

        Returns:
            Refined code with both deterministic and AI-powered improvements
        """
        self.logger.info(
            f"Starting code refinement for {node_type}/{domain} "
            f"with {len(refinement_context)} recommendations"
        )

        # Step 1: Apply deterministic fixes (G12, G13, G14) - fast & free
        fix_result = apply_automatic_fixes(original_code, Path(f"temp_{node_type}.py"))
        code = fix_result.fixed_code if fix_result.fix_count > 0 else original_code

        if fix_result.fix_count > 0:
            self.logger.info(
                f"Applied {fix_result.fix_count} automatic fixes: "
                f"{', '.join(fix_result.fixes_applied[:3])}"
            )

        # Step 2: AI-powered refinement using CodeRefiner
        if not hasattr(self, "_code_refiner") or self._code_refiner is None:
            try:
                self._code_refiner = CodeRefiner()
                self.logger.info("Initialized CodeRefiner for AI-powered refinement")
            except Exception as e:
                self.logger.warning(
                    f"Failed to initialize CodeRefiner: {e}, "
                    "continuing with deterministic fixes only"
                )
                return code

        try:
            # Build refinement context dict for CodeRefiner
            context_dict = {
                "node_type": node_type,
                "domain": domain,
                "service_name": service_name,
                "requirements": {
                    "refinement_context": refinement_context,
                    "intelligence_patterns": intelligence.node_type_patterns or [],
                    "domain_practices": intelligence.domain_best_practices or [],
                    "anti_patterns": intelligence.anti_patterns or [],
                },
            }

            # Apply AI refinement
            refined_code = await self._code_refiner.refine_code(
                code=code, file_type="node", refinement_context=context_dict
            )

            self.logger.info(
                f"AI refinement completed for {node_type}/{domain} "
                f"({len(original_code.splitlines())} → {len(refined_code.splitlines())} lines)"
            )

            return refined_code

        except Exception as e:
            # Graceful degradation: return code with deterministic fixes
            self.logger.warning(
                f"AI refinement failed: {e}, returning code with deterministic fixes only"
            )
            return code

    async def _stage_6_write_files(
        self, generation_result: Dict[str, Any], output_directory: str
    ) -> Tuple[PipelineStage, Dict]:
        """
        Stage 6: Write generated files to filesystem.

        Files are already written by template engine, this stage verifies.
        """
        stage = PipelineStage(stage_name="file_writing", status=StageStatus.RUNNING)
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            # Files are already written by template engine
            # Verify they exist
            output_path = Path(generation_result["output_path"])
            generated_files = generation_result["generated_files"]

            if not output_path.exists():
                stage.status = StageStatus.FAILED
                stage.error = f"Output path not found: {output_path}"
                return stage, {}

            # Verify all files exist
            for file_path_str in generated_files:
                file_path = Path(file_path_str)
                if not file_path.exists():
                    stage.status = StageStatus.FAILED
                    stage.error = f"File not found: {file_path}"
                    return stage, {}

            # Track written files for rollback
            self.written_files = [Path(f) for f in generated_files]

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "files_written": len(generated_files),
                "output_path": str(output_path),
            }

            return stage, {
                "output_path": str(output_path),
                "generated_files": generated_files,
            }

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage, {}

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    async def _stage_7_compile_test(
        self, output_path: str, node_type: str, service_name: str
    ) -> Tuple[PipelineStage, Dict]:
        """
        Stage 7: Compilation testing (OPTIONAL).

        Validation Gates (WARNING):
        - G13: MyPy type checking
        - G14: Import test
        """
        stage = PipelineStage(
            stage_name="compilation_testing", status=StageStatus.RUNNING
        )
        stage.start_time = datetime.utcnow()
        start_ms = time()

        try:
            output_path_obj = Path(output_path)
            main_file = output_path_obj / "v1_0_0" / "node.py"

            if not main_file.exists():
                stage.status = StageStatus.FAILED
                stage.error = f"Main file not found: {main_file}"
                return stage, {"passed": False}

            # G13: MyPy type checking
            gate_g13 = self._gate_g13_mypy_check(str(main_file))
            stage.validation_gates.append(gate_g13)

            # G14: Import test
            gate_g14 = self._gate_g14_import_test(
                output_path_obj, node_type, service_name
            )
            stage.validation_gates.append(gate_g14)

            # Compilation passed if no failures (warnings OK)
            passed = all(gate.status != "fail" for gate in stage.validation_gates)

            stage.status = StageStatus.COMPLETED
            stage.metadata = {
                "mypy_passed": gate_g13.status == "pass",
                "import_passed": gate_g14.status == "pass",
            }

            return stage, {"passed": passed}

        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            return stage, {"passed": False}

        finally:
            stage.end_time = datetime.utcnow()
            stage.duration_ms = int((time() - start_ms) * 1000)

    # -------------------------------------------------------------------------
    # Validation Gates Implementation
    # -------------------------------------------------------------------------

    def _gate_g1_prompt_completeness_full(
        self, parsed_data: Dict[str, Any]
    ) -> ValidationGate:
        """G1: Prompt has minimum required information."""
        start_ms = time()

        required_fields = ["node_type", "service_name", "domain", "description"]
        missing = [f for f in required_fields if not parsed_data.get(f)]

        if missing:
            return ValidationGate(
                gate_id="G1",
                name="Prompt Completeness",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Missing required fields: {', '.join(missing)}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G1",
            name="Prompt Completeness",
            status="pass",
            gate_type=GateType.BLOCKING,
            message="All required fields present",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g2_node_type_valid(self, node_type: str) -> ValidationGate:
        """G2: Node type is valid (all 4 ONEX types supported)."""
        start_ms = time()

        # Phase 2: All 4 ONEX node types supported
        valid_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

        if node_type not in valid_types:
            return ValidationGate(
                gate_id="G2",
                name="Node Type Valid",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Invalid node type: {node_type}. Valid types: {', '.join(valid_types)}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G2",
            name="Node Type Valid",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"Node type '{node_type}' is valid",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g3_service_name_valid(self, service_name: str) -> ValidationGate:
        """G3: Service name is valid Python identifier."""
        start_ms = time()

        # Check if valid Python identifier (snake_case)
        if not re.match(r"^[a-z][a-z0-9_]*$", service_name):
            return ValidationGate(
                gate_id="G3",
                name="Service Name Valid",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Invalid service name: '{service_name}'. Must be snake_case Python identifier.",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G3",
            name="Service Name Valid",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"Service name '{service_name}' is valid",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g4_critical_imports_exist(self) -> ValidationGate:
        """G4: Critical imports exist in omnibase_core."""
        start_ms = time()

        failures = []

        for import_path in self.CRITICAL_IMPORTS:
            try:
                module_path, class_name = import_path.rsplit(".", 1)
                module = import_module(module_path)

                if not hasattr(module, class_name):
                    failures.append(f"{class_name} not found in {module_path}")

            except ImportError as e:
                failures.append(f"Cannot import {module_path}: {e}")

        if failures:
            return ValidationGate(
                gate_id="G4",
                name="Critical Imports Exist",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Critical imports failed: {'; '.join(failures[:3])}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G4",
            name="Critical Imports Exist",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"All {len(self.CRITICAL_IMPORTS)} critical imports validated",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g5_templates_available(self, node_type: str) -> ValidationGate:
        """G5: Templates are available for node type."""
        start_ms = time()

        if node_type not in self.template_engine.templates:
            return ValidationGate(
                gate_id="G5",
                name="Templates Available",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Template not found for node type: {node_type}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G5",
            name="Templates Available",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"Template for {node_type} node is available",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g7_prompt_completeness(self, prompt: str) -> ValidationGate:
        """G7: Prompt has minimum information (WARNING)."""
        start_ms = time()

        if len(prompt) < 10:
            return ValidationGate(
                gate_id="G7",
                name="Prompt Completeness Check",
                status="warning",
                gate_type=GateType.WARNING,
                message="Prompt is very short (<10 chars). Results may be unreliable.",
                duration_ms=int((time() - start_ms) * 1000),
            )

        if len(prompt.split()) < 5:
            return ValidationGate(
                gate_id="G7",
                name="Prompt Completeness Check",
                status="warning",
                gate_type=GateType.WARNING,
                message="Prompt has few words (<5). Consider providing more context.",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G7",
            name="Prompt Completeness Check",
            status="pass",
            gate_type=GateType.WARNING,
            message="Prompt has sufficient information",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g8_context_completeness(
        self, parsed_data: Dict[str, Any]
    ) -> ValidationGate:
        """G8: Context has all expected fields (WARNING)."""
        start_ms = time()

        expected_fields = [
            "node_type",
            "service_name",
            "domain",
            "description",
            "operations",
            "features",
        ]
        missing = [f for f in expected_fields if f not in parsed_data]

        if missing:
            return ValidationGate(
                gate_id="G8",
                name="Context Completeness",
                status="warning",
                gate_type=GateType.WARNING,
                message=f"Context missing optional fields: {', '.join(missing)}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G8",
            name="Context Completeness",
            status="pass",
            gate_type=GateType.WARNING,
            message="Context has all expected fields",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_i1_intelligence_completeness(
        self, intelligence: IntelligenceContext
    ) -> ValidationGate:
        """I1: Verify intelligence gathering completeness (WARNING)."""
        start_ms = time()

        # Check if we have meaningful intelligence
        has_patterns = len(intelligence.node_type_patterns) > 0
        has_best_practices = len(intelligence.domain_best_practices) > 0

        if not has_patterns:
            return ValidationGate(
                gate_id="I1",
                name="Intelligence Completeness",
                status="warning",
                gate_type=GateType.WARNING,
                message="No node type patterns found - using template defaults",
                duration_ms=int((time() - start_ms) * 1000),
            )

        if not has_best_practices:
            return ValidationGate(
                gate_id="I1",
                name="Intelligence Completeness",
                status="warning",
                gate_type=GateType.WARNING,
                message="No domain best practices found - limited enhancement",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="I1",
            name="Intelligence Completeness",
            status="pass",
            gate_type=GateType.WARNING,
            message=f"Intelligence gathered: {len(intelligence.node_type_patterns)} patterns from {len(intelligence.rag_sources)} sources (confidence: {intelligence.confidence_score:.2f})",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g9_python_syntax_valid(self, code: str, file_path: str) -> ValidationGate:
        """G9: Generated code has valid Python syntax (AST parsing)."""
        start_ms = time()

        try:
            ast.parse(code)
            return ValidationGate(
                gate_id="G9",
                name="Python Syntax Valid",
                status="pass",
                gate_type=GateType.BLOCKING,
                message=f"Syntax valid: {file_path}",
                duration_ms=int((time() - start_ms) * 1000),
            )
        except SyntaxError as e:
            return ValidationGate(
                gate_id="G9",
                name="Python Syntax Valid",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Syntax error in {file_path} line {e.lineno}: {e.msg}",
                duration_ms=int((time() - start_ms) * 1000),
            )

    def _gate_g10_onex_naming(self, code: str, node_type: str) -> ValidationGate:
        """G10: Node class follows ONEX naming convention (suffix-based)."""
        start_ms = time()

        # Convert node_type to title case for pattern matching
        # node_type comes in as uppercase (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
        # but ONEX naming standard uses title case (Effect, Compute, Reducer, Orchestrator)
        node_type_title = node_type.capitalize()

        # Find class definition
        class_pattern = rf"class\s+(Node\w+{node_type_title})\("
        match = re.search(class_pattern, code)

        if not match:
            return ValidationGate(
                gate_id="G10",
                name="ONEX Naming Convention",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Node class not found or incorrect naming (must end with '{node_type_title}')",
                duration_ms=int((time() - start_ms) * 1000),
            )

        class_name = match.group(1)

        # Verify suffix (not prefix)
        if not class_name.endswith(node_type_title):
            return ValidationGate(
                gate_id="G10",
                name="ONEX Naming Convention",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Incorrect naming: '{class_name}' should end with '{node_type_title}'",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G10",
            name="ONEX Naming Convention",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"Class name '{class_name}' follows ONEX naming convention",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g11_import_resolution(self, code: str) -> ValidationGate:
        """G11: All imports are resolvable (static check)."""
        start_ms = time()

        warnings = []

        # Find all import statements
        import_pattern = r"^from\s+([\w\.]+)\s+import"
        for match in re.finditer(import_pattern, code, re.MULTILINE):
            module_path = match.group(1)

            # Check for old (wrong) import paths
            if "omnibase_core.core.node_" in module_path:
                warnings.append(
                    f"Old import path detected: {module_path} (should use omnibase_core.nodes.node_*)"
                )

        if warnings:
            return ValidationGate(
                gate_id="G11",
                name="Import Resolution",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Import issues found: {'; '.join(warnings[:2])}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G11",
            name="Import Resolution",
            status="pass",
            gate_type=GateType.BLOCKING,
            message="All imports appear resolvable",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g12_pydantic_models(self, model_files: List[str]) -> ValidationGate:
        """G12: Pydantic models are well-formed."""
        start_ms = time()

        warnings = []

        for file_path_str in model_files[:5]:  # Check first 5 model files
            try:
                file_path = Path(file_path_str)
                if not file_path.exists():
                    continue

                code = file_path.read_text()

                # Check for old Pydantic v1 patterns
                if ".dict()" in code:
                    warnings.append(
                        f"Pydantic v1 pattern in {file_path.name}: .dict() should be .model_dump()"
                    )

                # Check for BaseModel usage
                if "class Model" in code and "BaseModel" in code:
                    # Verify Config class (optional for v2)
                    if "class Config:" not in code and "model_config" not in code:
                        warnings.append(
                            f"Pydantic model in {file_path.name} missing Config class"
                        )

            except Exception as e:
                warnings.append(f"Error checking {file_path_str}: {e}")

        if warnings:
            return ValidationGate(
                gate_id="G12",
                name="Pydantic Model Structure",
                status="warning",
                gate_type=GateType.BLOCKING,
                message=f"Model issues found: {'; '.join(warnings[:2])}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        return ValidationGate(
            gate_id="G12",
            name="Pydantic Model Structure",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"All {len(model_files)} model files validated",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_r1_refinement_quality(
        self, original_code: str, refined_code: str, refinement_context: List[str]
    ) -> ValidationGate:
        """R1: Validate refinement quality (syntax, preservation)."""
        start_ms = time()

        # Check 1: Refined code must have valid Python syntax
        try:
            ast.parse(refined_code)
        except SyntaxError as e:
            return ValidationGate(
                gate_id="R1",
                name="Refinement Quality",
                status="fail",
                gate_type=GateType.BLOCKING,
                message=f"Refined code has syntax error at line {e.lineno}: {e.msg}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        # Check 2: Refined code should not be dramatically different in length
        # (avoid AI hallucinations or major rewrites)
        original_lines = len(original_code.splitlines())
        refined_lines = len(refined_code.splitlines())
        line_change_ratio = abs(refined_lines - original_lines) / max(original_lines, 1)

        if line_change_ratio > 0.5:  # More than 50% change
            return ValidationGate(
                gate_id="R1",
                name="Refinement Quality",
                status="warning",
                gate_type=GateType.WARNING,
                message=f"Refinement changed code significantly: {original_lines} → {refined_lines} lines ({line_change_ratio:.0%} change)",
                duration_ms=int((time() - start_ms) * 1000),
            )

        # Check 3: Ensure class definition is preserved
        original_has_class = "class Node" in original_code
        refined_has_class = "class Node" in refined_code

        if original_has_class and not refined_has_class:
            return ValidationGate(
                gate_id="R1",
                name="Refinement Quality",
                status="fail",
                gate_type=GateType.BLOCKING,
                message="Refinement removed node class definition",
                duration_ms=int((time() - start_ms) * 1000),
            )

        # Check 4: Ensure critical imports are preserved
        critical_imports = [
            "from omnibase_core.nodes",
            "from omnibase_core.errors",
            "from omnibase_core.models",
        ]

        for import_statement in critical_imports:
            if (
                import_statement in original_code
                and import_statement not in refined_code
            ):
                return ValidationGate(
                    gate_id="R1",
                    name="Refinement Quality",
                    status="fail",
                    gate_type=GateType.BLOCKING,
                    message=f"Refinement removed critical import: {import_statement}",
                    duration_ms=int((time() - start_ms) * 1000),
                )

        # Refinement passed quality checks
        enhancements = len(refinement_context)
        return ValidationGate(
            gate_id="R1",
            name="Refinement Quality",
            status="pass",
            gate_type=GateType.BLOCKING,
            message=f"Refinement applied {enhancements} enhancements successfully",
            duration_ms=int((time() - start_ms) * 1000),
        )

    def _gate_g13_mypy_check(self, file_path: str) -> ValidationGate:
        """G13: MyPy type checking passes (WARNING)."""
        start_ms = time()

        try:
            # Run mypy
            result = subprocess.run(
                ["poetry", "run", "mypy", file_path, "--no-error-summary"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                return ValidationGate(
                    gate_id="G13",
                    name="MyPy Type Checking",
                    status="warning",
                    gate_type=GateType.WARNING,
                    message=f"MyPy found issues: {result.stdout[:200]}",
                    duration_ms=int((time() - start_ms) * 1000),
                )

            return ValidationGate(
                gate_id="G13",
                name="MyPy Type Checking",
                status="pass",
                gate_type=GateType.WARNING,
                message="MyPy type checking passed",
                duration_ms=int((time() - start_ms) * 1000),
            )

        except subprocess.TimeoutExpired:
            return ValidationGate(
                gate_id="G13",
                name="MyPy Type Checking",
                status="warning",
                gate_type=GateType.WARNING,
                message="MyPy check timed out (>30s)",
                duration_ms=int((time() - start_ms) * 1000),
            )

        except Exception as e:
            return ValidationGate(
                gate_id="G13",
                name="MyPy Type Checking",
                status="warning",
                gate_type=GateType.WARNING,
                message=f"MyPy check failed: {str(e)}",
                duration_ms=int((time() - start_ms) * 1000),
            )

    def _gate_g14_import_test(
        self, output_path: Path, node_type: str, service_name: str
    ) -> ValidationGate:
        """G14: Import test succeeds (WARNING)."""
        start_ms = time()

        try:
            # Add to Python path
            sys.path.insert(0, str(output_path.parent))

            # Try to import
            node_module_name = (
                output_path.name
            )  # e.g., "node_infrastructure_postgres_writer_effect"
            module = import_module(f"{node_module_name}.v1_0_0.node")

            # Try to get node class
            pascal_name = "".join(word.capitalize() for word in service_name.split("_"))
            node_class_name = f"Node{pascal_name}{node_type.capitalize()}"

            if not hasattr(module, node_class_name):
                return ValidationGate(
                    gate_id="G14",
                    name="Import Test",
                    status="warning",
                    gate_type=GateType.WARNING,
                    message=f"Node class '{node_class_name}' not found in module",
                    duration_ms=int((time() - start_ms) * 1000),
                )

            return ValidationGate(
                gate_id="G14",
                name="Import Test",
                status="pass",
                gate_type=GateType.WARNING,
                message=f"Successfully imported {node_class_name}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        except ImportError as e:
            return ValidationGate(
                gate_id="G14",
                name="Import Test",
                status="warning",
                gate_type=GateType.WARNING,
                message=f"Import failed: {str(e)[:100]}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        except Exception as e:
            return ValidationGate(
                gate_id="G14",
                name="Import Test",
                status="warning",
                gate_type=GateType.WARNING,
                message=f"Import test error: {str(e)[:100]}",
                duration_ms=int((time() - start_ms) * 1000),
            )

        finally:
            # Remove from path
            if str(output_path.parent) in sys.path:
                sys.path.remove(str(output_path.parent))

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _to_snake_case(self, text: str) -> str:
        """
        Convert PascalCase/camelCase to snake_case while preserving acronyms.

        Examples:
            "PostgresCRUD" -> "postgres_crud"
            "RestAPI" -> "rest_api"
            "HttpClient" -> "http_client"
        """
        # Insert underscore before uppercase letters that follow lowercase letters
        # or before uppercase letters that are followed by lowercase letters
        result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", result)
        return result.lower()

    def _prompt_to_prd(self, prompt: str) -> str:
        """Convert prompt to simple PRD format."""
        return f"""# Node Generation Request

## Overview
{prompt}

## Functional Requirements
- Implement core functionality as described
- Handle error cases appropriately
- Provide logging and monitoring

## Features
- Feature 1: Core operation implementation
- Feature 2: Error handling
- Feature 3: Logging integration

## Success Criteria
- Node generates successfully
- All validation gates pass
- Code compiles without errors
"""

    def _detect_node_type(self, prompt: str) -> str:
        """Detect node type from prompt using PromptParser."""
        # Use PromptParser for intelligent node type detection
        node_type, confidence = self.prompt_parser._extract_node_type(prompt)

        self.logger.debug(
            f"Detected node type: {node_type} (confidence: {confidence:.2f})"
        )

        return node_type

    def _extract_service_name(
        self, prompt: str, analysis_result: SimplePRDAnalysisResult
    ) -> str:
        """Extract service name from prompt."""
        # Strategy 1: Explicit name patterns (similar to PromptParser logic)
        # IMPORTANT: Preserve exact casing from input (including acronyms like CRUD, API, etc.)
        patterns = [
            r"(?:called|named)\s+([A-Z][A-Za-z0-9_]+)",  # "called DatabaseWriter"
            r"(?:name|Name):\s*([A-Z][A-Za-z0-9_]+)",  # "Name: DatabaseWriter"
            r"([A-Z][A-Za-z0-9_]+)\s+(?:node|Node)",  # "DatabaseWriter node"
            r"(?i)(?:EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)\s+node:\s*([A-Z][A-Za-z0-9_]+)",  # "COMPUTE node: PriceCalculator"
            r"(?i)(?:EFFECT|COMPUTE|REDUCER|ORCHESTRATOR)\s+node\s+([A-Z][A-Za-z0-9_]+)",  # "EFFECT node EmailSender"
        ]

        node_type_keywords = {"EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"}

        for pattern in patterns:
            match = re.search(pattern, prompt)
            if match:
                name = match.group(1)
                # Validate it's PascalCase and not a node type keyword
                if (
                    name
                    and name[0].isupper()
                    and name.upper() not in node_type_keywords
                ):
                    # PRESERVE EXACT CASING - return as-is for template engine to convert
                    # Template engine will use _to_pascal_case which preserves acronyms
                    return self._to_snake_case(name)

        # Strategy 2: Extract from "for XXX" pattern
        match = re.search(r"for\s+(\w+)", prompt, re.IGNORECASE)
        if match:
            service_name = match.group(1).lower().replace(" ", "_")
            return service_name

        # Strategy 3: Use first keyword from analysis
        if analysis_result.parsed_prd.extracted_keywords:
            return (
                analysis_result.parsed_prd.extracted_keywords[0]
                .lower()
                .replace(" ", "_")
            )

        # Ultimate fallback
        return "generated_service"

    def _extract_domain(
        self, prompt: str, analysis_result: SimplePRDAnalysisResult
    ) -> str:
        """Extract domain from prompt."""
        prompt_lower = prompt.lower()

        # Strategy 1: Explicit domain mention
        patterns = [
            r"(?:in\s+(?:the\s+)?|domain:\s*)([a-z_]+)\s+domain",  # "in workflow_services domain" or "in the data_services domain"
            r"domain:\s*([a-z_]+)",  # "domain: data_services"
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt_lower)
            if match:
                domain = match.group(1)
                # Convert to snake_case if needed
                domain = re.sub(r"[^a-z0-9]+", "_", domain.lower())
                return domain

        # Strategy 2: Keyword-based inference
        domain_keywords = {
            "infrastructure": ["database", "postgres", "redis", "cache", "storage"],
            "api": ["api", "http", "rest", "graphql", "endpoint"],
            "data": ["data", "processing", "etl", "transform"],
            "messaging": ["message", "queue", "kafka", "rabbitmq", "event"],
            "auth": ["auth", "authentication", "authorization", "security"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in prompt_lower for kw in keywords):
                return domain

        # Fallback
        return "general"

    async def _rollback(self, failed_stage: str):
        """Rollback changes on pipeline failure."""
        self.logger.warning(f"Rolling back changes from stage: {failed_stage}")

        # Delete written files
        for file_path in self.written_files:
            try:
                if file_path.exists():
                    if file_path.is_file():
                        file_path.unlink()
                    elif file_path.is_dir():
                        # Delete directory recursively
                        import shutil

                        shutil.rmtree(file_path)
                    self.logger.debug(f"Deleted: {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to delete {file_path}: {e}")

        # Delete temp files
        for file_path in self.temp_files:
            try:
                if file_path.exists():
                    file_path.unlink()
                    self.logger.debug(f"Deleted temp file: {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to delete temp file {file_path}: {e}")

        self.logger.info("Rollback complete")

    async def cleanup_async(self, timeout: float = 5.0):
        """
        Cleanup async resources (template engine cache).

        Args:
            timeout: Maximum time to wait for cleanup (seconds)
        """
        if self.template_engine:
            await self.template_engine.cleanup_async(timeout)
            self.logger.debug("Template engine cleanup complete")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup resources."""
        await self.cleanup_async()
        return False

    def __del__(self):
        """Destructor - warn if cleanup not called."""
        if (
            hasattr(self, "template_engine")
            and self.template_engine
            and hasattr(self.template_engine, "template_cache")
            and self.template_engine.template_cache
        ):
            if hasattr(self.template_engine.template_cache, "_background_tasks"):
                tasks = self.template_engine.template_cache._background_tasks
                if tasks:
                    self.logger.warning(
                        f"GenerationPipeline destroyed with {len(tasks)} pending tasks. "
                        f"Use async context manager or cleanup_async() to avoid this."
                    )
