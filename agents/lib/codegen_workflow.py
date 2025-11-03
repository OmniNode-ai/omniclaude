#!/usr/bin/env python3
"""
Code Generation Workflow Integration

Integrates PRD analysis and template generation into the existing workflow.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .omninode_template_engine import OmniNodeTemplateEngine
from .parallel_generator import GenerationJob, ParallelGenerator
from .persistence import CodegenPersistence
from .prd_intelligence_client import PRDIntelligenceClient

# Local imports
from .simple_prd_analyzer import PRDAnalysisResult, PRDAnalyzer
from .version_config import get_config

logger = logging.getLogger(__name__)


class CodegenWorkflowResult:
    """Result of code generation workflow"""

    def __init__(
        self,
        session_id: UUID,
        correlation_id: UUID,
        prd_analysis: PRDAnalysisResult,
        generated_nodes: List[Dict[str, Any]],
        total_files: int,
        success: bool,
        error_message: Optional[str] = None,
    ):
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.prd_analysis = prd_analysis
        self.generated_nodes = generated_nodes
        self.total_files = total_files
        self.success = success
        self.error_message = error_message
        self.completed_at = datetime.now(timezone.utc)


class CodegenWorkflow:
    """Code generation workflow orchestrator"""

    def __init__(self, enable_parallel: bool = True, max_workers: int = 3):
        self.config = get_config()
        self.prd_analyzer = PRDAnalyzer()
        self.template_engine = OmniNodeTemplateEngine()
        self.logger = logging.getLogger(__name__)
        self.persistence = CodegenPersistence()
        self.prd_intel = PRDIntelligenceClient()

        # Parallel generation support
        self.enable_parallel = enable_parallel
        self.parallel_generator = (
            ParallelGenerator(
                max_workers=max_workers, timeout_seconds=120, enable_metrics=True
            )
            if enable_parallel
            else None
        )

    async def generate_from_prd(
        self,
        prd_content: str,
        output_directory: str,
        workspace_context: Optional[Dict[str, Any]] = None,
        parallel: Optional[bool] = None,
    ) -> CodegenWorkflowResult:
        """
        Generate OmniNode implementations from PRD content.

        Args:
            prd_content: Raw PRD markdown content
            output_directory: Directory to write generated files
            workspace_context: Optional workspace context
            parallel: Enable parallel generation (None=auto, True=force, False=disable)

        Returns:
            CodegenWorkflowResult with generation results

        Raises:
            OnexError: If generation fails
        """
        try:
            session_id = uuid4()
            correlation_id = uuid4()

            self.logger.info(
                f"Starting code generation workflow for session {session_id}"
            )

            # Step 1: Analyze PRD
            self.logger.info("Step 1: Analyzing PRD content")
            # Persist session start (non-fatal if persistence unavailable)
            try:
                await self.persistence.upsert_session(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    prd_content=prd_content,
                    status="started",
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to persist session start (continuing anyway): {e}"
                )
            if getattr(self.config, "enable_event_driven_analysis", False):
                try:
                    resp = await self.prd_intel.analyze(
                        prd_content=prd_content,
                        workspace_context=workspace_context or {},
                        timeout_seconds=float(
                            getattr(self.config, "analysis_timeout_seconds", 30)
                        ),
                    )
                    if resp and isinstance(resp, dict) and resp.get("analysis"):
                        local = await self.prd_analyzer.analyze_prd(
                            prd_content, workspace_context
                        )
                        hints = resp["analysis"].get("node_type_hints") or {}
                        mixins = resp["analysis"].get("recommended_mixins") or []
                        local.node_type_hints.update(hints)
                        if mixins:
                            local.recommended_mixins = list(
                                {*local.recommended_mixins, *mixins}
                            )
                        prd_analysis = local
                    else:
                        prd_analysis = await self.prd_analyzer.analyze_prd(
                            prd_content, workspace_context
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Event-driven analysis failed, falling back to local: {e}"
                    )
                    prd_analysis = await self.prd_analyzer.analyze_prd(
                        prd_content, workspace_context
                    )
            else:
                prd_analysis = await self.prd_analyzer.analyze_prd(
                    prd_content, workspace_context
                )

            # Step 2: Determine node types to generate
            self.logger.info("Step 2: Determining node types")
            node_types = self._determine_node_types(prd_analysis)

            # Step 3: Generate nodes
            self.logger.info("Step 3: Generating OmniNode implementations")

            # Extract microservice name and domain from PRD
            microservice_name = self._extract_microservice_name(prd_analysis)
            domain = self._extract_domain(prd_analysis)

            # Determine if parallel generation should be used
            use_parallel = self._should_use_parallel(node_types, parallel)

            if use_parallel and self.parallel_generator:
                # Parallel generation
                self.logger.info(
                    f"Using parallel generation for {len(node_types)} nodes"
                )
                generated_nodes, total_files = await self._generate_nodes_parallel(
                    session_id=session_id,
                    node_types=node_types,
                    prd_analysis=prd_analysis,
                    microservice_name=microservice_name,
                    domain=domain,
                    output_directory=output_directory,
                )
            else:
                # Sequential generation (existing code)
                self.logger.info(
                    f"Using sequential generation for {len(node_types)} nodes"
                )
                generated_nodes, total_files = await self._generate_nodes_sequential(
                    session_id=session_id,
                    node_types=node_types,
                    prd_analysis=prd_analysis,
                    microservice_name=microservice_name,
                    domain=domain,
                    output_directory=output_directory,
                )

            # Step 4: Validate generated code
            self.logger.info("Step 4: Validating generated code")
            await self._validate_generated_code(generated_nodes)

            # Step 5: Log cache performance (Agent Framework)
            await self._log_cache_performance(session_id)

            # Create result
            result = CodegenWorkflowResult(
                session_id=session_id,
                correlation_id=correlation_id,
                prd_analysis=prd_analysis,
                generated_nodes=generated_nodes,
                total_files=total_files,
                success=True,
            )
            # Mark session complete (non-fatal if persistence unavailable)
            try:
                await self.persistence.complete_session(session_id)
            except Exception as e:
                self.logger.warning(
                    f"Failed to mark session complete (continuing anyway): {e}"
                )

            # Close persistence connection
            try:
                await self.persistence.close()
            except Exception as e:
                self.logger.warning(
                    f"Failed to close persistence (continuing anyway): {e}"
                )

            self.logger.info(
                f"Code generation workflow completed for session {session_id}"
            )
            self.logger.info(
                f"Generated {len(generated_nodes)} nodes with {total_files} total files"
            )

            return result

        except Exception as e:
            self.logger.error(f"Code generation workflow failed: {str(e)}")
            return CodegenWorkflowResult(
                session_id=session_id,
                correlation_id=correlation_id,
                prd_analysis=None,
                generated_nodes=[],
                total_files=0,
                success=False,
                error_message=str(e),
            )

    def _should_use_parallel(
        self, node_types: List[str], parallel: Optional[bool]
    ) -> bool:
        """
        Determine if parallel generation should be used.

        Args:
            node_types: List of node types to generate
            parallel: User preference (None=auto, True=force, False=disable)

        Returns:
            True if parallel generation should be used
        """
        # User explicitly disabled
        if parallel is False:
            return False

        # User explicitly enabled
        if parallel is True:
            return True and self.enable_parallel

        # Auto mode: use parallel for 2+ nodes
        return len(node_types) >= 2 and self.enable_parallel

    async def _generate_nodes_parallel(
        self,
        session_id: UUID,
        node_types: List[str],
        prd_analysis: PRDAnalysisResult,
        microservice_name: str,
        domain: str,
        output_directory: str,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Generate nodes in parallel using worker pool.

        Args:
            session_id: Session ID for tracking
            node_types: List of node types to generate
            prd_analysis: PRD analysis result
            microservice_name: Microservice name
            domain: Domain name
            output_directory: Output directory

        Returns:
            Tuple of (generated_nodes, total_files)
        """
        # Create generation jobs
        jobs = [
            GenerationJob(
                job_id=uuid4(),
                node_type=node_type,
                microservice_name=microservice_name,
                domain=domain,
                analysis_result=prd_analysis,
                output_directory=output_directory,
            )
            for node_type in node_types
        ]

        # Execute parallel generation
        results = await self.parallel_generator.generate_nodes_parallel(
            jobs=jobs, session_id=session_id
        )

        # Extract successful generations
        generated_nodes = []
        for result in results:
            if result.success and result.node_result:
                generated_nodes.append(result.node_result)

                # Persist artifacts when available
                try:
                    files = result.node_result.get("generated_files", [])
                    for file_path in files:
                        # Read file content if it's just a path string
                        if isinstance(file_path, str):
                            from pathlib import Path

                            path_obj = Path(file_path)
                            if path_obj.exists():
                                content = path_obj.read_text(encoding="utf-8")
                            else:
                                content = ""
                        else:
                            # Assume it's a dict with path and content
                            path_obj = file_path.get("path") or file_path.get(
                                "file_path"
                            )
                            content = file_path.get("content", "")

                        if path_obj:
                            await self.persistence.insert_artifact(
                                session_id=session_id,
                                artifact_id=uuid4(),
                                artifact_type=result.node_type,
                                file_path=str(path_obj),
                                content=content,
                                quality_score=None,
                                validation_status=None,
                                template_version=None,
                            )
                except Exception as e:
                    # Non-fatal for MVP
                    self.logger.debug(f"Non-fatal artifact persistence failure: {e}")

        # Calculate total files
        total_files = sum(
            len(node.get("generated_files", [])) + 1 for node in generated_nodes
        )  # +1 for main file

        return generated_nodes, total_files

    async def _generate_nodes_sequential(
        self,
        session_id: UUID,
        node_types: List[str],
        prd_analysis: PRDAnalysisResult,
        microservice_name: str,
        domain: str,
        output_directory: str,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Generate nodes sequentially (original implementation).

        Args:
            session_id: Session ID for tracking
            node_types: List of node types to generate
            prd_analysis: PRD analysis result
            microservice_name: Microservice name
            domain: Domain name
            output_directory: Output directory

        Returns:
            Tuple of (generated_nodes, total_files)
        """
        generated_nodes = []
        total_files = 0

        for node_type in node_types:
            self.logger.info(f"Generating {node_type} node")

            # Generate node
            node_result = await self.template_engine.generate_node(
                analysis_result=prd_analysis,
                node_type=node_type,
                microservice_name=microservice_name,
                domain=domain,
                output_directory=output_directory,
            )

            generated_nodes.append(node_result)
            total_files += (
                len(node_result.get("generated_files", [])) + 1
            )  # +1 for main file

            # Persist artifacts when available
            try:
                files = node_result.get("generated_files", [])
                for file_path in files:
                    # Read file content if it's just a path string
                    if isinstance(file_path, str):
                        from pathlib import Path

                        path_obj = Path(file_path)
                        if path_obj.exists():
                            content = path_obj.read_text(encoding="utf-8")
                        else:
                            content = ""
                    else:
                        # Assume it's a dict with path and content
                        path_obj = file_path.get("path") or file_path.get("file_path")
                        content = file_path.get("content", "")

                    if path_obj:
                        await self.persistence.insert_artifact(
                            session_id=session_id,
                            artifact_id=uuid4(),
                            artifact_type=node_type,
                            file_path=str(path_obj),
                            content=content,
                            quality_score=None,
                            validation_status=None,
                            template_version=None,
                        )
            except Exception as e:
                # Non-fatal for MVP
                self.logger.debug(f"Non-fatal artifact persistence failure: {e}")

        return generated_nodes, total_files

    def _determine_node_types(self, analysis_result: PRDAnalysisResult) -> List[str]:
        """Determine which node types to generate based on analysis"""
        node_types = []

        # Get node type hints from analysis
        hints = analysis_result.node_type_hints

        # Add node types with confidence > 0.3
        for node_type, confidence in hints.items():
            if confidence > 0.3:
                node_types.append(node_type)

        # If no confident hints, default to EFFECT
        if not node_types:
            node_types = ["EFFECT"]

        # Limit to 2 nodes max for MVP
        return node_types[:2]

    def _extract_microservice_name(self, analysis_result: PRDAnalysisResult) -> str:
        """Extract microservice name from PRD analysis"""
        # Use first word of title as microservice name
        title = analysis_result.parsed_prd.title
        if title:
            # Clean and extract first word
            words = title.lower().split()
            if words:
                # Remove common words and take first meaningful word
                meaningful_words = [
                    w for w in words if w not in ["the", "a", "an", "and", "or", "but"]
                ]
                if meaningful_words:
                    return meaningful_words[0]

        return "microservice"

    def _extract_domain(self, analysis_result: PRDAnalysisResult) -> str:
        """Extract domain from PRD analysis"""
        # Use second word of title as domain, or default
        title = analysis_result.parsed_prd.title
        if title:
            words = title.lower().split()
            if len(words) > 1:
                return words[1]

        return "domain"

    async def _validate_generated_code(
        self, generated_nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Validate generated code using omnibase_spi validators"""
        validation_results = {}

        # Only validate if the analyzer has the validation method
        if not hasattr(self.prd_analyzer, "validate_generated_metadata"):
            self.logger.debug(
                "Metadata validation not available, skipping validation step"
            )
            return validation_results

        for node in generated_nodes:
            node_type = node.get("node_type")
            microservice_name = node.get("microservice_name")

            # Validate metadata
            metadata = node.get("metadata", "")
            if metadata:
                try:
                    validation_result = (
                        await self.prd_analyzer.validate_generated_metadata(metadata)
                    )
                    validation_results[f"{microservice_name}_{node_type}"] = (
                        validation_result
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Validation failed for {microservice_name}_{node_type}: {e}"
                    )

        return validation_results

    async def _log_cache_performance(self, session_id: UUID):
        """
        Log template cache performance metrics (Agent Framework).

        Args:
            session_id: Current session ID for tracking
        """
        try:
            # Get cache stats from template engine
            cache_stats = self.template_engine.get_cache_stats()

            if cache_stats:
                self.logger.info("Template Cache Performance:")
                self.logger.info(f"  Hit rate: {cache_stats['hit_rate']:.1%}")
                self.logger.info(
                    f"  Hits: {cache_stats['hits']}, Misses: {cache_stats['misses']}"
                )
                self.logger.info(
                    f"  Cached templates: {cache_stats['cached_templates']}"
                )
                self.logger.info(f"  Cache size: {cache_stats['total_size_mb']:.2f}MB")
                self.logger.info(
                    f"  Avg cached load time: {cache_stats.get('avg_cached_load_ms', 0):.3f}ms"
                )
                self.logger.info(
                    f"  Performance improvement: {cache_stats.get('improvement_percent', 0):.1f}%"
                )

                # Log to database for analytics (non-fatal if persistence unavailable)
                try:
                    await self.persistence.insert_performance_metric(
                        session_id=session_id,
                        node_type="template_cache",
                        phase="cache_performance",
                        duration_ms=int(
                            cache_stats.get("avg_cached_load_ms", 0)
                            * cache_stats["hits"]
                        ),
                        cache_hit=True,
                        metadata={
                            "hit_rate": float(cache_stats["hit_rate"]),
                            "hits": cache_stats["hits"],
                            "misses": cache_stats["misses"],
                            "cached_templates": cache_stats["cached_templates"],
                            "total_size_mb": float(cache_stats["total_size_mb"]),
                            "improvement_percent": float(
                                cache_stats.get("improvement_percent", 0)
                            ),
                            "time_saved_ms": float(cache_stats.get("time_saved_ms", 0)),
                        },
                    )
                except Exception as e:
                    self.logger.debug(f"Failed to persist cache metrics: {e}")
            else:
                self.logger.debug("Template caching not enabled for this session")

        except Exception as e:
            # Don't fail workflow due to cache metrics logging
            self.logger.warning(f"Failed to log cache performance: {e}")

    async def generate_single_node(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        business_description: str,
        output_directory: str,
    ) -> Dict[str, Any]:
        """
        Generate a single node without full PRD analysis.

        Args:
            node_type: Type of node to generate
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            business_description: Business description
            output_directory: Directory to write generated files

        Returns:
            Dictionary with generation results
        """
        try:
            # Create mock analysis result using simple models
            from .simple_prd_analyzer import DecompositionResult, ParsedPRD

            mock_parsed_prd = ParsedPRD(
                title=f"{microservice_name} {node_type}",
                description=business_description,
                functional_requirements=[
                    f"Implement {microservice_name} {node_type.lower()} functionality"
                ],
                features=[f"{microservice_name} {node_type.lower()} operations"],
                success_criteria=[
                    f"Successful {microservice_name} {node_type.lower()} implementation"
                ],
                technical_details=[f"{node_type} node implementation"],
                dependencies=[],
                extracted_keywords=[microservice_name, node_type.lower()],
                sections=[],
                word_count=len(business_description.split()),
            )

            mock_decomposition = DecompositionResult(
                tasks=[], total_tasks=0, verification_successful=True
            )

            mock_analysis = PRDAnalysisResult(
                session_id=uuid4(),
                correlation_id=uuid4(),
                prd_content=business_description,
                parsed_prd=mock_parsed_prd,
                decomposition_result=mock_decomposition,
                node_type_hints={node_type: 1.0},
                recommended_mixins=["MixinLogging", "MixinHealthCheck"],
                external_systems=[],
                quality_baseline=0.8,
                confidence_score=0.9,
            )

            # Generate node
            result = await self.template_engine.generate_node(
                analysis_result=mock_analysis,
                node_type=node_type,
                microservice_name=microservice_name,
                domain=domain,
                output_directory=output_directory,
            )

            return result

        except Exception as e:
            self.logger.error(f"Single node generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Single node generation failed: {str(e)}",
                details={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain,
                },
            )
