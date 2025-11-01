#!/usr/bin/env python3
"""
OmniNode Template Engine

Uses omnibase_core models and contracts to generate OmniNode implementations.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Import from omnibase_core
from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError

from .models.intelligence_context import IntelligenceContext, get_default_intelligence

# Pattern learning imports (KV-002 integration)
from .pattern_library import PatternLibrary
from .patterns.pattern_storage import PatternStorage
from .prd_analyzer import PRDAnalysisResult
from .template_cache import TemplateCache
from .template_helpers import (
    format_best_practices,
    format_domain_patterns,
    format_error_scenarios,
    format_performance_targets,
    generate_pattern_code_blocks,
    generate_security_section,
    generate_testing_section,
)
from .version_config import get_config

# TODO: Add omnibase_spi imports when available
# from omnibase_spi.validation.tool_metadata_validator import ToolMetadataValidator


logger = logging.getLogger(__name__)


class NodeTemplate:
    """Template for generating OmniNode implementations"""

    def __init__(self, node_type: str, template_content: str):
        self.node_type = node_type
        self.template_content = template_content
        self.placeholders = self._extract_placeholders()

    def _extract_placeholders(self) -> Set[str]:
        """Extract placeholder variables from template"""
        pattern = r"\{([A-Z_]+)\}"
        return set(re.findall(pattern, self.template_content))

    def validate_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate template context before rendering.

        Args:
            context: Template context variables

        Returns:
            Validation result with missing/extra placeholders

        Raises:
            ModelOnexError: If validation fails critically
        """
        missing = self.placeholders - set(context.keys())
        extra = set(context.keys()) - self.placeholders

        validation_result = {
            "valid": len(missing) == 0,
            "missing_placeholders": list(missing),
            "extra_variables": list(extra),
            "total_placeholders": len(self.placeholders),
            "provided_variables": len(context),
        }

        # Log warnings for extra variables (not critical)
        if extra:
            logger.debug(f"Extra context variables provided (will be ignored): {extra}")

        # Critical error for missing placeholders
        if missing:
            logger.error(
                f"Missing required placeholders: {missing}. "
                f"Required: {self.placeholders}, Provided: {set(context.keys())}"
            )
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Template validation failed: Missing required placeholders",
                context={
                    "missing_placeholders": list(missing),
                    "required_placeholders": list(self.placeholders),
                    "provided_keys": list(context.keys()),
                },
            )

        return validation_result

    def render(self, context: Dict[str, Any]) -> str:
        """
        Render template with context variables after validation.

        Args:
            context: Template context variables

        Returns:
            Rendered template content

        Raises:
            ModelOnexError: If validation or rendering fails
        """
        # Validate context before rendering
        validation_result = self.validate_context(context)
        logger.debug(
            f"Template validation passed: {validation_result['total_placeholders']} "
            f"placeholders, {validation_result['provided_variables']} variables"
        )

        # Render template
        rendered = self.template_content

        for key, value in context.items():
            placeholder = f"{{{key}}}"
            if placeholder in rendered:
                # Validate value is not None
                if value is None:
                    logger.warning(
                        f"Placeholder {key} has None value, using empty string"
                    )
                    value = ""

                rendered = rendered.replace(placeholder, str(value))

        # Post-render validation: Check for unresolved placeholders
        unresolved = self._extract_placeholders_from_text(rendered)
        if unresolved:
            logger.error(
                f"Template rendering left unresolved placeholders: {unresolved}"
            )
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Template rendering incomplete: Unresolved placeholders remain",
                context={
                    "unresolved_placeholders": list(unresolved),
                    "node_type": self.node_type,
                },
            )

        return rendered

    def _extract_placeholders_from_text(self, text: str) -> Set[str]:
        """Extract placeholders from rendered text to detect unresolved ones"""
        pattern = r"\{([A-Z_]+)\}"
        return set(re.findall(pattern, text))


class OmniNodeTemplateEngine:
    """
    Thread-safe template engine for generating OmniNode implementations.

    Thread-Safety Guarantees:
    - Templates are loaded once and cached (read-only after initialization)
    - Template rendering uses immutable context dictionaries
    - File writes go to unique directories per node (domain/microservice/type)
    - Safe for concurrent use across multiple worker threads
    - Template cache (Agent Framework) provides thread-safe access

    Note: Each worker thread should create its own event loop but can share
    the template engine instance safely.
    """

    # Valid node types (ONEX 4-node architecture)
    VALID_NODE_TYPES = {"EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"}

    # Dangerous path patterns
    DANGEROUS_PATH_PATTERNS = {"..", "~", "/etc", "/var", "/sys", "/proc", "\\"}

    def __init__(self, enable_cache: bool = True, enable_pattern_learning: bool = True):
        self.config = get_config()
        self.templates_dir = Path(self.config.template_directory)
        # TODO: Initialize validator when omnibase_spi is available
        # self.metadata_validator = ToolMetadataValidator()
        self.logger = logging.getLogger(__name__)

        # Initialize template cache (Agent Framework)
        self.enable_cache = enable_cache
        if enable_cache:
            self.template_cache = TemplateCache(
                max_templates=100,
                max_size_mb=50,
                ttl_seconds=3600,
                enable_persistence=True,  # 1 hour
            )
            self.logger.info("Template caching enabled")
        else:
            self.template_cache = None
            self.logger.info("Template caching disabled")

        # Initialize pattern learning (KV-002 integration)
        self.enable_pattern_learning = enable_pattern_learning
        if enable_pattern_learning:
            try:
                self.pattern_library = PatternLibrary()
                self.pattern_storage = PatternStorage(
                    qdrant_url=getattr(
                        self.config, "qdrant_url", "http://localhost:6333"
                    ),
                    collection_name="code_generation_patterns",
                    use_in_memory=False,  # Try Qdrant first, fallback to in-memory if unavailable
                )
                self.logger.info("Pattern learning enabled (KV-002)")
            except Exception as e:
                self.logger.warning(
                    f"Pattern learning initialization failed (non-critical): {e}"
                )
                self.pattern_library = None
                self.pattern_storage = None
                self.enable_pattern_learning = False
        else:
            self.pattern_library = None
            self.pattern_storage = None
            self.logger.info("Pattern learning disabled")

        # Load templates (with caching if enabled)
        self.templates = self._load_templates()

        # Warmup cache on startup
        if enable_cache and self.template_cache:
            self._warmup_cache()

    def _load_templates(self) -> Dict[str, NodeTemplate]:
        """
        Load node templates from filesystem with optional caching.

        Uses template cache (Agent Framework) for 50% performance improvement.
        """
        templates = {}

        # Template types to load
        template_types = [
            ("EFFECT", "effect_node_template.py"),
            ("COMPUTE", "compute_node_template.py"),
            ("REDUCER", "reducer_node_template.py"),
            ("ORCHESTRATOR", "orchestrator_node_template.py"),
        ]

        for node_type, filename in template_types:
            template_path = self.templates_dir / filename

            if template_path.exists():
                if self.enable_cache and self.template_cache:
                    # Use cache for improved performance
                    content, cache_hit = self.template_cache.get(
                        template_name=f"{node_type}_template",
                        template_type=node_type,
                        file_path=template_path,
                        loader_func=lambda p: p.read_text(encoding="utf-8"),
                    )

                    if cache_hit:
                        self.logger.debug(f"Cache HIT for {node_type} template")
                    else:
                        self.logger.debug(f"Cache MISS for {node_type} template")
                else:
                    # Direct load without caching
                    with open(template_path, "r") as f:
                        content = f.read()

                templates[node_type] = NodeTemplate(node_type, content)
            else:
                self.logger.warning(f"Template file not found: {template_path}")

        return templates

    def _warmup_cache(self):
        """Warmup cache by preloading all templates"""
        if not self.enable_cache or not self.template_cache:
            return

        template_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
        self.logger.info(
            f"Warming up template cache for {len(template_types)} templates"
        )

        self.template_cache.warmup(
            templates_dir=self.templates_dir, template_types=template_types
        )

        # Log cache statistics after warmup
        stats = self.template_cache.get_stats()
        self.logger.info(
            f"Cache warmup complete: {stats['cached_templates']} templates loaded, "
            f"{stats['total_size_mb']}MB cached"
        )

    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get template cache statistics.

        Returns:
            Cache statistics or None if caching disabled
        """
        if self.enable_cache and self.template_cache:
            return self.template_cache.get_stats()
        return None

    def invalidate_cache(self, template_name: Optional[str] = None):
        """
        Invalidate template cache.

        Args:
            template_name: Specific template to invalidate, or None for all
        """
        if self.enable_cache and self.template_cache:
            if template_name:
                self.template_cache.invalidate(template_name)
                self.logger.info(f"Invalidated cache for template: {template_name}")
            else:
                self.template_cache.invalidate_all()
                self.logger.info("Invalidated all cached templates")

    def _validate_node_type(self, node_type: str):
        """
        Validate node type is one of the 4 ONEX types.

        Args:
            node_type: Node type to validate

        Raises:
            ModelOnexError: If node type is invalid
        """
        if node_type not in self.VALID_NODE_TYPES:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid node type: {node_type}",
                context={
                    "provided_type": node_type,
                    "valid_types": list(self.VALID_NODE_TYPES),
                },
            )

    def _validate_output_path(self, output_directory: str):
        """
        Validate output directory path for security.

        Args:
            output_directory: Directory path to validate

        Raises:
            ModelOnexError: If path is unsafe or invalid
        """
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATH_PATTERNS:
            if pattern in output_directory:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Unsafe path detected: Contains dangerous pattern '{pattern}'",
                    context={
                        "output_directory": output_directory,
                        "dangerous_pattern": pattern,
                    },
                )

        # Ensure path is not absolute to system directories
        path = Path(output_directory)
        try:
            # Resolve to absolute path safely
            resolved_path = path.resolve()

            # Check if path tries to escape to system directories
            system_dirs = ["/etc", "/var", "/sys", "/proc", "/boot", "/root"]
            for system_dir in system_dirs:
                if str(resolved_path).startswith(system_dir):
                    raise ModelOnexError(
                        error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                        message=f"Cannot write to system directory: {system_dir}",
                        context={
                            "output_directory": output_directory,
                            "resolved_path": str(resolved_path),
                        },
                    )
        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid output path: {str(e)}",
                context={"output_directory": output_directory},
            ) from e

    def _validate_file_path(self, file_path: str, base_directory: Path):
        """
        Validate file path is within base directory (prevent directory traversal).

        Args:
            file_path: File path to validate
            base_directory: Base directory that file must be within

        Raises:
            ModelOnexError: If path escapes base directory
        """
        try:
            # Resolve both paths
            full_path = (base_directory / file_path).resolve()
            base_path = base_directory.resolve()

            # Check if full_path is within base_path
            if not str(full_path).startswith(str(base_path)):
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="File path escapes base directory (directory traversal attempt)",
                    context={
                        "file_path": file_path,
                        "base_directory": str(base_directory),
                        "resolved_path": str(full_path),
                    },
                )
        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message=f"Invalid file path: {str(e)}",
                context={
                    "file_path": file_path,
                    "base_directory": str(base_directory),
                },
            ) from e

    def _validate_generation_inputs(
        self,
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        output_directory: str,
    ):
        """
        Validate all generation inputs before processing.

        Args:
            analysis_result: PRD analysis result
            node_type: Node type
            microservice_name: Microservice name
            domain: Domain name
            output_directory: Output directory

        Raises:
            ModelOnexError: If any validation fails
        """
        # Validate node type
        self._validate_node_type(node_type)

        # Validate output path
        self._validate_output_path(output_directory)

        # Validate names don't contain dangerous characters
        name_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")

        if not name_pattern.match(microservice_name):
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Microservice name contains invalid characters",
                context={
                    "microservice_name": microservice_name,
                    "allowed_pattern": "alphanumeric, underscore, hyphen only",
                },
            )

        if not name_pattern.match(domain):
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Domain name contains invalid characters",
                context={
                    "domain": domain,
                    "allowed_pattern": "alphanumeric, underscore, hyphen only",
                },
            )

        # Validate analysis result has required fields
        if not analysis_result.parsed_prd:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Analysis result missing parsed PRD",
                context={"analysis_result": "parsed_prd is None or empty"},
            )

        if not analysis_result.parsed_prd.description:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="PRD description is required but missing",
                context={"parsed_prd": "description field is empty"},
            )

    async def generate_node(
        self,
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        output_directory: str,
        intelligence: Optional[IntelligenceContext] = None,
    ) -> Dict[str, Any]:
        """
        Generate OmniNode implementation from PRD analysis with intelligence context.

        Args:
            analysis_result: PRD analysis result
            node_type: Type of node to generate (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
            microservice_name: Name of the microservice
            domain: Domain of the microservice
            output_directory: Directory to write generated files
            intelligence: Optional intelligence context for enhanced generation

        Returns:
            Dictionary with generated files and metadata

        Raises:
            ModelOnexError: If generation fails
        """
        try:
            self.logger.info(f"Generating {node_type} node: {microservice_name}")

            # VALIDATION PHASE: Validate all inputs before processing
            self._validate_generation_inputs(
                analysis_result, node_type, microservice_name, domain, output_directory
            )
            self.logger.debug("Input validation passed")

            # Use default intelligence if not provided
            if intelligence is None:
                self.logger.info(f"Using default intelligence for {node_type} node")
                intelligence = get_default_intelligence(node_type)

            # Get template for node type
            template = self.templates.get(node_type)
            if not template:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"No template found for node type: {node_type}",
                    context={"available_templates": list(self.templates.keys())},
                )

            # Prepare context for template rendering with intelligence
            context = self._prepare_template_context(
                analysis_result, node_type, microservice_name, domain, intelligence
            )

            # === PRE-GENERATION PATTERN QUERY (KV-002 Integration) ===
            # Query learned patterns to enhance code generation
            if self.enable_pattern_learning and self.pattern_library:
                try:
                    # Detect patterns from contract/context
                    detected_pattern = self.pattern_library.detect_pattern(
                        {
                            "capabilities": context.get("OPERATIONS", []),
                            "node_type": node_type,
                            "service_name": microservice_name,
                            "features": context.get("FEATURES", []),
                        },
                        min_confidence=0.7,
                    )

                    if detected_pattern and detected_pattern.get("matched"):
                        self.logger.info(
                            f"Pattern detected: {detected_pattern['pattern_name']} "
                            f"(confidence: {detected_pattern['confidence']:.2f})"
                        )

                        # Generate pattern-specific code
                        pattern_code_result = self.pattern_library.generate_pattern_code(
                            pattern_name=detected_pattern["pattern_name"],
                            contract=context,
                            node_type=node_type,
                            class_name=f"Node{self._to_pascal_case(microservice_name)}{node_type.capitalize()}",
                        )

                        if pattern_code_result and pattern_code_result.get("code"):
                            context["PATTERN_CODE"] = pattern_code_result["code"]
                            context["PATTERN_NAME"] = detected_pattern["pattern_name"]
                            context["PATTERN_CONFIDENCE"] = detected_pattern[
                                "confidence"
                            ]
                            self.logger.debug(
                                f"Added pattern code to context: {detected_pattern['pattern_name']}"
                            )
                    else:
                        self.logger.debug(
                            "No high-confidence patterns detected, using default generation"
                        )

                except Exception as e:
                    # Pattern detection failure should NOT break generation (non-blocking)
                    self.logger.warning(f"Pattern detection failed (non-critical): {e}")

            # Generate node implementation
            node_content = template.render(context)

            # Generate additional files
            generated_files = await self._generate_additional_files(
                analysis_result, node_type, microservice_name, domain, context
            )

            # Create output directory structure
            output_path = Path(output_directory)
            node_path = (
                output_path / f"node_{domain}_{microservice_name}_{node_type.lower()}"
            )
            node_path.mkdir(parents=True, exist_ok=True)

            # Write main node file
            main_file_path = node_path / "v1_0_0" / "node.py"
            main_file_path.parent.mkdir(exist_ok=True)
            with open(main_file_path, "w") as f:
                f.write(node_content)

            # Write additional files with validation
            for file_path, content in generated_files.items():
                # Validate file path doesn't escape node directory
                self._validate_file_path(file_path, node_path)

                full_path = node_path / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)

                # Additional validation: ensure content is not empty
                if not content or not content.strip():
                    self.logger.warning(
                        f"Generated file {file_path} has empty content, skipping"
                    )
                    continue

                with open(full_path, "w") as f:
                    f.write(content)

                self.logger.debug(f"Written file: {full_path} ({len(content)} bytes)")

            # Generate metadata
            metadata = self._generate_node_metadata(
                node_type, microservice_name, domain, analysis_result
            )

            # Build full file paths for generated_files
            full_file_paths = [
                str(node_path / file_path) for file_path in generated_files.keys()
            ]

            # === POST-GENERATION PATTERN EXTRACTION (KV-002 Integration) ===
            # Extract and store patterns from high-quality generations for future reuse
            quality_score = analysis_result.confidence_score
            if (
                self.enable_pattern_learning
                and self.pattern_storage
                and quality_score >= 0.8
            ):
                try:
                    # Import PatternExtractor dynamically to avoid circular imports
                    from .patterns.pattern_extractor import PatternExtractor

                    self.logger.debug(
                        f"Extracting patterns from high-quality generation (score: {quality_score:.2f})"
                    )

                    # Extract patterns from generated code
                    extractor = PatternExtractor(min_confidence=0.5)
                    extraction_result = extractor.extract_patterns(
                        generated_code=node_content,
                        context={
                            "framework": "onex",
                            "node_type": node_type,
                            "service_name": microservice_name,
                            "domain": domain,
                            "quality_score": quality_score,
                            "generation_date": datetime.now(timezone.utc).isoformat(),
                        },
                    )

                    # Store high-confidence patterns asynchronously (non-blocking)
                    import asyncio

                    high_confidence_patterns = (
                        extraction_result.high_confidence_patterns
                    )

                    if high_confidence_patterns:
                        self.logger.info(
                            f"Extracted {len(high_confidence_patterns)} high-confidence patterns "
                            f"for storage ({extraction_result.extraction_time_ms}ms)"
                        )

                        # Store patterns asynchronously (fire-and-forget style)
                        # Note: We use a simple embedding (zeros) for now - in production,
                        # you would use a real embedding model (e.g., sentence-transformers)
                        for pattern in high_confidence_patterns:
                            try:
                                # Generate a simple embedding (384 dimensions, all zeros for now)
                                # TODO: Replace with real embedding model
                                simple_embedding = [0.0] * 384

                                # Store pattern asynchronously
                                asyncio.create_task(
                                    self.pattern_storage.store_pattern(
                                        pattern, simple_embedding
                                    )
                                )
                            except Exception as store_error:
                                # Individual pattern storage failure should not break the process
                                self.logger.warning(
                                    f"Failed to store pattern {pattern.pattern_name} (non-critical): {store_error}"
                                )
                    else:
                        self.logger.debug(
                            "No high-confidence patterns extracted for storage"
                        )

                except Exception as e:
                    # Pattern extraction failure should NOT break generation (non-blocking)
                    self.logger.warning(
                        f"Pattern extraction failed (non-critical): {e}"
                    )
            elif quality_score < 0.8:
                self.logger.debug(
                    f"Skipping pattern extraction for low-quality generation (score: {quality_score:.2f} < 0.8)"
                )

            return {
                "node_type": node_type,
                "microservice_name": microservice_name,
                "domain": domain,
                "output_path": str(node_path),
                "main_file": str(main_file_path),
                "generated_files": full_file_paths,
                "metadata": {
                    "session_id": str(analysis_result.session_id),
                    "correlation_id": str(analysis_result.correlation_id),
                    "node_metadata": metadata,
                    "confidence_score": analysis_result.confidence_score,
                    "quality_baseline": analysis_result.quality_baseline,
                },
                "context": context,
            }

        except Exception as e:
            self.logger.error(f"Node generation failed: {str(e)}")
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Node generation failed: {str(e)}",
                context={
                    "node_type": node_type,
                    "microservice_name": microservice_name,
                    "domain": domain,
                },
            ) from e

    def _prepare_template_context(
        self,
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        intelligence: Optional[IntelligenceContext] = None,
    ) -> Dict[str, Any]:
        """Prepare context variables for template rendering with intelligence"""

        # Basic context
        context = {
            "DOMAIN": domain,
            "MICROSERVICE_NAME": microservice_name,
            "MICROSERVICE_NAME_PASCAL": self._to_pascal_case(microservice_name),
            "DOMAIN_PASCAL": self._to_pascal_case(domain),
            "NODE_TYPE": node_type,
            "BUSINESS_DESCRIPTION": analysis_result.parsed_prd.description,
            "REPOSITORY_NAME": "omniclaude",  # Default for now
        }

        # Add intelligence-driven context (NEW!)
        if intelligence:
            context["BEST_PRACTICES"] = intelligence.node_type_patterns
            context["COMMON_OPERATIONS"] = intelligence.common_operations
            context["REQUIRED_MIXINS"] = intelligence.required_mixins
            context["PERFORMANCE_TARGETS"] = intelligence.performance_targets
            context["ERROR_SCENARIOS"] = intelligence.error_scenarios
            context["DOMAIN_PATTERNS"] = intelligence.domain_best_practices
            context["ANTI_PATTERNS"] = intelligence.anti_patterns
            context["TESTING_RECOMMENDATIONS"] = intelligence.testing_recommendations
            context["SECURITY_CONSIDERATIONS"] = intelligence.security_considerations
            context["INTELLIGENCE_CONFIDENCE"] = intelligence.confidence_score

            # Add formatted versions for template use
            context["BEST_PRACTICES_FORMATTED"] = format_best_practices(
                intelligence.node_type_patterns
            )
            context["ERROR_SCENARIOS_FORMATTED"] = format_error_scenarios(
                intelligence.error_scenarios
            )
            context["PERFORMANCE_TARGETS_FORMATTED"] = format_performance_targets(
                intelligence.performance_targets
            )
            context["DOMAIN_PATTERNS_FORMATTED"] = format_domain_patterns(
                intelligence.domain_best_practices
            )
            context["PATTERN_CODE_BLOCKS"] = generate_pattern_code_blocks(
                intelligence.node_type_patterns, node_type
            )
            context["TESTING_SECTION"] = generate_testing_section(
                intelligence.testing_recommendations, node_type
            )
            context["SECURITY_SECTION"] = generate_security_section(
                intelligence.security_considerations, node_type
            )
        else:
            # Defaults if no intelligence provided
            context["BEST_PRACTICES"] = []
            context["COMMON_OPERATIONS"] = []
            context["REQUIRED_MIXINS"] = []
            context["PERFORMANCE_TARGETS"] = {}
            context["ERROR_SCENARIOS"] = []
            context["DOMAIN_PATTERNS"] = []
            context["ANTI_PATTERNS"] = []
            context["TESTING_RECOMMENDATIONS"] = []
            context["SECURITY_CONSIDERATIONS"] = []
            context["INTELLIGENCE_CONFIDENCE"] = 0.0

            # Add empty formatted versions
            context["BEST_PRACTICES_FORMATTED"] = "    - Standard ONEX patterns"
            context["ERROR_SCENARIOS_FORMATTED"] = "    - Standard error handling"
            context["PERFORMANCE_TARGETS_FORMATTED"] = (
                "    - Standard performance requirements"
            )
            context["DOMAIN_PATTERNS_FORMATTED"] = "    - Standard domain patterns"
            context["PATTERN_CODE_BLOCKS"] = ""
            context["TESTING_SECTION"] = generate_testing_section([], node_type)
            context["SECURITY_SECTION"] = generate_security_section([], node_type)

        # Add mixin information
        mixins = analysis_result.recommended_mixins
        context["MIXIN_IMPORTS"] = self._generate_mixin_imports(mixins)
        context["MIXIN_INHERITANCE"] = self._generate_mixin_inheritance(mixins)
        context["MIXIN_INITIALIZATION"] = self._generate_mixin_initialization(mixins)

        # Add business logic stub
        context["BUSINESS_LOGIC_STUB"] = self._generate_business_logic_stub(
            analysis_result, node_type, microservice_name
        )

        # Add operations from decomposition
        operations = self._extract_operations(analysis_result.decomposition_result)
        context["OPERATIONS"] = operations

        # Add features
        features = analysis_result.parsed_prd.features[:3]  # Top 3 features
        context["FEATURES"] = features

        return context

    def _to_pascal_case(self, text: str) -> str:
        """
        Convert text to PascalCase while preserving acronyms.

        Examples:
            "postgres_crud" -> "PostgresCRUD"
            "rest_api" -> "RestAPI"
            "http_client" -> "HttpClient"
            "sql_connector" -> "SQLConnector"
            "PostgresCRUD" -> "PostgresCRUD" (preserved)
        """
        # Core acronyms that should ALWAYS be uppercase (even as first word)
        CORE_ACRONYMS = {
            "CRUD",
            "API",
            "SQL",
            "JSON",
            "XML",
            "UUID",
            "URI",
            "URL",
            "JWT",
            "CSS",
            "HTML",
        }

        # Protocol/tech acronyms that should be uppercase only when NOT first word
        PROTOCOL_ACRONYMS = {
            "HTTP",
            "REST",
            "SMTP",
            "FTP",
            "SSH",
            "SSL",
            "TLS",
            "TCP",
            "UDP",
            "IP",
            "OAUTH",
        }

        # If already has mixed case (PascalCase), preserve it
        if any(c.isupper() for c in text) and any(c.islower() for c in text):
            # Already in PascalCase format, return as-is
            return text

        # Convert from snake_case or kebab-case
        words = text.replace("_", " ").replace("-", " ").split()
        result_parts = []

        for idx, word in enumerate(words):
            word_upper = word.upper()

            if word_upper in CORE_ACRONYMS:
                # Core acronyms always uppercase
                result_parts.append(word_upper)
            elif word_upper in PROTOCOL_ACRONYMS:
                if idx == 0:
                    # First word: capitalize first letter only (e.g., "rest" -> "Rest", "http" -> "Http")
                    result_parts.append(word.capitalize())
                else:
                    # Subsequent words: keep uppercase (e.g., "http" -> "HTTP")
                    result_parts.append(word_upper)
            else:
                # Capitalize normally
                result_parts.append(word.capitalize())

        return "".join(result_parts)

    def _generate_mixin_imports(self, mixins: List[str]) -> str:
        """Generate mixin import statements"""
        if not mixins:
            return ""

        # TODO: Re-enable when omnibase_core supports mixins
        # Temporarily disabled to avoid importing non-existent modules
        return ""

        # imports = []
        # for mixin in mixins:
        #     imports.append(f"from omnibase_core.mixins.{mixin.lower()} import {mixin}")
        # return "\n".join(imports)

    def _generate_mixin_inheritance(self, mixins: List[str]) -> str:
        """Generate mixin inheritance chain"""
        if not mixins:
            return ""

        # TODO: Re-enable when omnibase_core supports mixins
        # Temporarily disabled to avoid using non-existent mixin classes
        return ""

        # return ", " + ", ".join(mixins)

    def _generate_mixin_initialization(self, mixins: List[str]) -> str:
        """Generate mixin initialization code"""
        # Mixins handle their own initialization via __init__ methods
        # No explicit initialization code needed
        return ""

    def _generate_business_logic_stub(
        self,
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
    ) -> str:
        """Generate business logic stub based on analysis"""
        stub = (
            f"        # TODO: Implement {microservice_name} {node_type.lower()} logic\n"
        )
        stub += "        # Based on requirements:\n"

        for req in analysis_result.parsed_prd.functional_requirements[:3]:
            stub += f"        # - {req}\n"

        stub += "        # External systems:\n"
        for system in analysis_result.external_systems:
            stub += f"        # - {system}\n"

        return stub

    def _extract_operations(self, decomposition_result) -> List[str]:
        """Extract operations from task decomposition"""
        operations = []
        for task in decomposition_result.tasks[:3]:  # Top 3 tasks
            if isinstance(task, dict):
                operations.append(task.get("title", "Unknown Task"))
            else:
                operations.append(task.title)
        return operations

    async def _generate_additional_files(
        self,
        analysis_result: PRDAnalysisResult,
        node_type: str,
        microservice_name: str,
        domain: str,
        context: Dict[str, Any],
    ) -> Dict[str, str]:
        """Generate additional files (models, contracts, manifests, etc.)"""
        files = {}

        # Generate input model
        files["v1_0_0/models/model_{}_input.py".format(microservice_name)] = (
            self._generate_input_model(microservice_name, analysis_result)
        )

        # Generate output model
        files["v1_0_0/models/model_{}_output.py".format(microservice_name)] = (
            self._generate_output_model(microservice_name, analysis_result)
        )

        # Generate config model
        files["v1_0_0/models/model_{}_config.py".format(microservice_name)] = (
            self._generate_config_model(microservice_name, analysis_result)
        )

        # Generate contract model (NEW: Phase 6 enhancement)
        files[
            "v1_0_0/models/model_{}_{}_contract.py".format(
                microservice_name, node_type.lower()
            )
        ] = self._generate_contract_model(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate enum
        files["v1_0_0/enums/enum_{}_operation_type.py".format(microservice_name)] = (
            self._generate_operation_enum(microservice_name, analysis_result)
        )

        # Generate contract YAML (UPDATED: Phase 6 enhancement with full ONEX compliance)
        files["v1_0_0/contract.yaml"] = self._generate_contract_yaml(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate node manifest (NEW: Phase 6 enhancement)
        files["node.manifest.yaml"] = self._generate_node_manifest(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate version manifest (NEW: Phase 6 enhancement)
        files["v1_0_0/version.manifest.yaml"] = self._generate_version_manifest(
            microservice_name, node_type, domain, analysis_result, context
        )

        # Generate __init__.py files
        files["v1_0_0/__init__.py"] = self._generate_version_init()
        files["v1_0_0/models/__init__.py"] = self._generate_models_init(
            microservice_name, node_type
        )
        files["v1_0_0/enums/__init__.py"] = self._generate_enums_init(microservice_name)

        return files

    def _generate_input_model(
        self, microservice_name: str, analysis_result: PRDAnalysisResult
    ) -> str:
        """Generate input model"""
        pascal_name = self._to_pascal_case(microservice_name)

        return f'''#!/usr/bin/env python3
"""
Input model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

class Model{pascal_name}Input(BaseModel):
    """Input envelope for {microservice_name} operations"""

    # Add node-specific fields here
    operation_type: str = Field(..., description="Type of operation to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Operation parameters")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
'''

    def _generate_output_model(
        self, microservice_name: str, analysis_result: PRDAnalysisResult
    ) -> str:
        """Generate output model"""
        pascal_name = self._to_pascal_case(microservice_name)

        return f'''#!/usr/bin/env python3
"""
Output model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field

class Model{pascal_name}Output(BaseModel):
    """Output envelope for {microservice_name} operations"""

    # Add node-specific fields here
    result_data: Dict[str, Any] = Field(default_factory=dict, description="Operation result data")
    success: bool = Field(..., description="Operation success status")
    error_message: Optional[str] = Field(None, description="Error message if operation failed")
'''

    def _generate_config_model(
        self, microservice_name: str, analysis_result: PRDAnalysisResult
    ) -> str:
        """Generate config model"""
        pascal_name = self._to_pascal_case(microservice_name)

        return f'''#!/usr/bin/env python3
"""
Configuration model for {microservice_name} node
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class Model{pascal_name}Config(BaseModel):
    """Configuration for {microservice_name} node"""

    # Add configuration fields here
    timeout_seconds: int = Field(default=30, description="Operation timeout in seconds")
    retry_attempts: int = Field(default=3, description="Number of retry attempts")
    debug_mode: bool = Field(default=False, description="Enable debug logging")
'''

    def _generate_operation_enum(
        self, microservice_name: str, analysis_result: PRDAnalysisResult
    ) -> str:
        """Generate operation enum"""
        pascal_name = self._to_pascal_case(microservice_name)

        return f'''#!/usr/bin/env python3
"""
Operation type enum for {microservice_name} node
"""

from enum import Enum

class Enum{pascal_name}OperationType(Enum):
    """Operation types for {microservice_name} node"""

    # Add operation types here
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
'''

    def _generate_contract(
        self,
        microservice_name: str,
        node_type: str,
        analysis_result: PRDAnalysisResult,
    ) -> str:
        """Generate YAML contract"""
        return f"""# {microservice_name} {node_type.lower()} contract
version: "1.0.0"
name: "{microservice_name}_{node_type.lower()}"
type: "{node_type.lower()}"
description: "{analysis_result.parsed_prd.description}"

# Contract definition
input_schema:
  type: object
  properties:
    operation_type:
      type: string
      enum: ["create", "read", "update", "delete"]
    parameters:
      type: object
    metadata:
      type: object
  required: ["operation_type"]

output_schema:
  type: object
  properties:
    success:
      type: boolean
    result_data:
      type: object
    error_message:
      type: string
  required: ["success"]

# Mixin requirements
mixins:
{self._generate_mixin_requirements(analysis_result.recommended_mixins)}

# External system dependencies
external_systems:
{self._generate_external_system_requirements(analysis_result.external_systems)}
"""

    def _generate_mixin_requirements(self, mixins: List[str]) -> str:
        """Generate mixin requirements for contract"""
        if not mixins:
            return "  - none"

        requirements = []
        for mixin in mixins:
            requirements.append(f"  - {mixin}")
        return "\n".join(requirements)

    def _generate_external_system_requirements(
        self, external_systems: List[str]
    ) -> str:
        """Generate external system requirements for contract"""
        if not external_systems:
            return "  - none"

        systems = []
        for system in external_systems:
            systems.append(f"  - {system}")
        return "\n".join(systems)

    def _generate_version_init(self) -> str:
        """Generate version __init__.py"""
        return '''#!/usr/bin/env python3
"""
Version 1.0.0 exports
"""

from .node import *
from .models import *
from .enums import *
'''

    def _generate_models_init(
        self, microservice_name: str, node_type: str = None
    ) -> str:
        """Generate models __init__.py"""
        base_imports = f'''#!/usr/bin/env python3
"""
Models for {microservice_name}
"""

from .model_{microservice_name}_input import *
from .model_{microservice_name}_output import *
from .model_{microservice_name}_config import *
'''
        # Add contract model import if node_type is provided
        if node_type:
            base_imports += f"from .model_{microservice_name}_{node_type.lower()}_contract import *\n"

        return base_imports

    def _generate_enums_init(self, microservice_name: str) -> str:
        """Generate enums __init__.py"""
        return f'''#!/usr/bin/env python3
"""
Enums for {microservice_name}
"""

from .enum_{microservice_name}_operation_type import *
'''

    def _generate_contract_model(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: PRDAnalysisResult,
        context: Dict[str, Any],
    ) -> str:
        """Generate contract model (Python Pydantic) following ONEX patterns"""

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_pascal = node_type.capitalize()
        node_type_lower = node_type.lower()

        # Load contract model template
        template_path = self.templates_dir / "contract_model_template.py"
        if not template_path.exists():
            # Fallback if template doesn't exist yet
            return self._generate_contract_model_fallback(
                microservice_name, node_type, analysis_result
            )

        with open(template_path, "r") as f:
            template_content = f.read()

        # Determine performance fields based on node type
        performance_fields = self._get_performance_fields_for_node_type(node_type)

        # Determine service characteristics
        is_persistent = node_type in ["REDUCER", "ORCHESTRATOR"]
        requires_external_deps = len(analysis_result.external_systems) > 0

        # Render template
        rendered = template_content.format(
            MICROSERVICE_NAME=microservice_name,
            MICROSERVICE_NAME_PASCAL=pascal_name,
            NODE_TYPE=node_type,
            NODE_TYPE_PASCAL=node_type_pascal,
            NODE_TYPE_LOWER=node_type_lower,
            BUSINESS_DESCRIPTION=analysis_result.parsed_prd.description,
            PERFORMANCE_FIELDS=performance_fields,
            IS_PERSISTENT_SERVICE=str(is_persistent).capitalize(),
            REQUIRES_EXTERNAL_DEPS=str(requires_external_deps).capitalize(),
        )

        return rendered

    def _get_performance_fields_for_node_type(self, node_type: str) -> str:
        """Get performance fields specific to node type"""
        if node_type == "COMPUTE":
            return """single_operation_max_ms: int = Field(
        default=2000,
        ge=10,
        le=60000,
        description="Maximum milliseconds for single computation operation",
    )"""
        elif node_type == "EFFECT":
            return """max_response_time_ms: int = Field(
        default=500,
        ge=10,
        le=10000,
        description="Maximum response time in milliseconds for effect operations",
    )"""
        elif node_type == "REDUCER":
            return """aggregation_window_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        description="Time window in milliseconds for aggregation operations",
    )

    max_aggregation_delay_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Maximum delay allowed for aggregation completion",
    )"""
        elif node_type == "ORCHESTRATOR":
            return """workflow_timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        description="Maximum workflow execution time in milliseconds",
    )

    coordination_overhead_ms: int = Field(
        default=100,
        ge=10,
        le=5000,
        description="Expected overhead for workflow coordination",
    )"""
        else:
            return """max_execution_time_ms: int = Field(
        default=1000,
        ge=10,
        le=60000,
        description="Maximum execution time in milliseconds",
    )"""

    def _generate_contract_model_fallback(
        self,
        microservice_name: str,
        node_type: str,
        analysis_result: PRDAnalysisResult,
    ) -> str:
        """Fallback contract model generation if template doesn't exist"""
        pascal_name = self._to_pascal_case(microservice_name)
        node_type_pascal = node_type.capitalize()

        return f'''#!/usr/bin/env python3
"""
{pascal_name} {node_type} Contract Model - ONEX Standards Compliant.

VERSION: 1.0.0 - INTERFACE LOCKED FOR CODE GENERATION

{analysis_result.parsed_prd.description}

ZERO TOLERANCE: No Any types allowed in implementation.
"""

from typing import ClassVar
from pydantic import BaseModel, ConfigDict, Field
from omnibase_core.primitives.model_semver import ModelSemVer


class Model{pascal_name}{node_type_pascal}Contract(BaseModel):
    """Contract model for {microservice_name} {node_type} node."""

    INTERFACE_VERSION: ClassVar[ModelSemVer] = ModelSemVer(major=1, minor=0, patch=0)

    contract_version: ModelSemVer = Field(
        default=ModelSemVer(major=1, minor=0, patch=0),
        description="Contract version following semantic versioning",
    )

    node_name: str = Field(
        default="{microservice_name}_{node_type.lower()}",
        description="Unique identifier for this node",
    )

    description: str = Field(
        default="{analysis_result.parsed_prd.description}",
        description="Business description of this node",
    )

    node_type: str = Field(
        default="{node_type}",
        description="ONEX node type",
    )

    model_config = ConfigDict(
        extra="ignore",
        use_enum_values=False,
        validate_assignment=True,
    )
'''

    def _generate_contract_yaml(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: PRDAnalysisResult,
        context: Dict[str, Any],
    ) -> str:
        """Generate comprehensive ONEX-compliant contract YAML"""

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()

        # Build actions list
        actions_list = self._build_actions_list(analysis_result, node_type)

        # Build dependencies list
        dependencies_list = self._build_dependencies_list(analysis_result)

        # Build subcontracts based on node type and mixins
        subcontracts = self._build_subcontracts_list(
            node_type, analysis_result.recommended_mixins
        )

        # Build algorithm section (required for COMPUTE nodes)
        algorithm_section = self._build_algorithm_section(node_type, microservice_name)

        # Build performance requirements
        performance_requirements = self._build_performance_requirements(node_type)

        # Determine service characteristics
        is_persistent = "true" if node_type in ["REDUCER", "ORCHESTRATOR"] else "false"
        requires_external_deps = (
            "true" if len(analysis_result.external_systems) > 0 else "false"
        )

        # Build event configuration
        primary_events = self._build_primary_events(node_type, microservice_name)
        event_categories = f'["{domain}", "{node_type_lower}", "generated"]'
        publish_events = (
            "true" if node_type in ["EFFECT", "REDUCER", "ORCHESTRATOR"] else "false"
        )
        subscribe_events = "true" if node_type in ["ORCHESTRATOR"] else "false"

        # Build service resolution
        service_resolution = self._build_service_resolution(analysis_result)

        # Build infrastructure
        infrastructure = self._build_infrastructure(analysis_result)

        # Build constraint definitions
        constraint_definitions = self._build_constraint_definitions(
            microservice_name, node_type
        )

        contract_yaml = f"""# {pascal_name} {node_type} - ONEX Contract
# {node_type} node for {analysis_result.parsed_prd.description}

# === REQUIRED ROOT FIELDS ===
contract_version: {{major: 1, minor: 0, patch: 0}}
node_name: "{microservice_name}_{node_type_lower}"
node_version: {{major: 1, minor: 0, patch: 0}}
contract_name: "{microservice_name}_{node_type_lower}_contract"
description: "{analysis_result.parsed_prd.description}"
node_type: "{node_type}"
name: "{microservice_name}_{node_type_lower}"
version: {{major: 1, minor: 0, patch: 0}}
input_model: "Model{pascal_name}Input"
output_model: "Model{pascal_name}Output"

# === NODE CLASSIFICATION ===
# (node_type already defined above)

# === MODEL SPECIFICATIONS ===

{algorithm_section}

tool_specification:
  tool_name: "node_{domain}_{microservice_name}_{node_type_lower}"
  version: {{major: 1, minor: 0, patch: 0}}
  description: "{analysis_result.parsed_prd.description}"
  main_tool_class: "Node{pascal_name}{node_type.capitalize()}"
  container_injection: "ONEXContainer"
  business_logic_pattern: "{node_type_lower}"

# === METADATA ===
metadata:
  tier: 3
  specialization: "{node_type_lower}"
  category: "{domain}"
  architectural_pattern: "node_{node_type_lower}"
  complexity: "medium"

# === SERVICE CONFIGURATION ===
service_configuration:
  is_persistent_service: {is_persistent}
  requires_external_dependencies: {requires_external_deps}

# === INPUT/OUTPUT ===
input_state:
  object_type: "object"
  required: ["operation_type"]
  optional: ["parameters", "metadata", "correlation_id"]

output_state:
  object_type: "object"
  required: ["success", "result_data"]
  optional: ["error_message", "metadata"]

# === ACTIONS ===
actions:
{actions_list}

# === DEPENDENCIES ===
dependencies:
{dependencies_list}

# === PERFORMANCE ===
performance:
{performance_requirements}

# === EVENT TYPE CONFIGURATION ===
event_type:
  primary_events: {primary_events}
  event_categories: {event_categories}
  publish_events: {publish_events}
  subscribe_events: {subscribe_events}
  event_routing: "{domain}"

# === SERVICE RESOLUTION ===
service_resolution:
{service_resolution}

infrastructure:
{infrastructure}

# === ONEX COMPLIANCE ===
contract_driven: true
strong_typing: true
zero_any_types: true
protocol_based: true

# === VALIDATION ===
validation_rules:
  strict_typing_enabled: true
  input_validation_enabled: true
  output_validation_enabled: true
  performance_validation_enabled: true
  constraint_definitions:
{constraint_definitions}

# === SUBCONTRACTS ===
subcontracts:
{subcontracts}

# === DEFINITIONS (Required by ModelContractContent) ===
definitions:
  models: {{}}
  schemas: {{}}
  responses: {{}}
"""

        return contract_yaml

    def _build_actions_list(
        self, analysis_result: PRDAnalysisResult, node_type: str
    ) -> str:
        """Build actions list for contract"""
        actions = []

        # Extract operations from PRD
        operations = analysis_result.parsed_prd.functional_requirements[:3]

        for idx, req in enumerate(operations, 1):
            # Create action name from requirement
            action_name = self._requirement_to_action_name(req)
            actions.append(
                f"""  - name: "{action_name}"
    description: "{req}"
    inputs: ["input_data"]
    outputs: ["result"]"""
            )

        # Add standard actions
        actions.append(
            """  - name: "health_check"
    description: "Check node health status"
    inputs: []
    outputs: ["status"]"""
        )

        return "\n\n".join(actions) if actions else "  []"

    def _requirement_to_action_name(self, requirement: str) -> str:
        """Convert requirement to snake_case action name"""
        # Simple heuristic: take first few words, convert to snake_case
        words = requirement.lower().split()[:3]
        # Remove common words
        words = [w for w in words if w not in ["the", "a", "an", "and", "or", "with"]]
        return "_".join(words[:3])

    def _build_dependencies_list(self, analysis_result: PRDAnalysisResult) -> str:
        """Build dependencies list for contract"""
        if not analysis_result.external_systems:
            return "  []"

        deps = []
        for system in analysis_result.external_systems[:3]:
            system_lower = system.lower().replace(" ", "_")
            deps.append(
                f'''  - name: "{system_lower}"
    type: "external_service"
    class_name: "Protocol{system.replace(' ', '')}"
    module: "omnibase.protocol.protocol_{system_lower}"'''
            )

        return "\n".join(deps)

    def _build_subcontracts_list(self, node_type: str, mixins: List[str]) -> str:
        """Build subcontracts list based on node type and mixins"""
        subcontracts = []

        # Standard subcontracts for all nodes
        subcontracts.extend(
            [
                '''  - path: "../../subcontracts/health_check_subcontract.yaml"
    integration_field: "health_check_configuration"''',
                '''  - path: "../../subcontracts/introspection_subcontract.yaml"
    integration_field: "introspection_configuration"''',
                '''  - path: "../../subcontracts/performance_monitoring_subcontract.yaml"
    integration_field: "performance_monitoring_configuration"''',
                '''  - path: "../../subcontracts/request_response_subcontract.yaml"
    integration_field: "request_response_configuration"''',
            ]
        )

        # Add mixin-specific subcontracts
        if "MixinEventBus" in mixins or "MixinRetry" in mixins:
            subcontracts.append(
                '''  - path: "../../mixins/mixin_error_handling.yaml"
    integration_field: "error_handling_configuration"'''
            )

        return "\n".join(subcontracts)

    def _build_algorithm_section(self, node_type: str, microservice_name: str) -> str:
        """Build algorithm section (required for COMPUTE nodes)"""
        if node_type != "COMPUTE":
            return "# === NODE CONFIGURATION ===\n# No algorithm section required for non-COMPUTE nodes"

        return f"""# === ALGORITHM CONFIGURATION (Required for COMPUTE nodes) ===
algorithm:
  algorithm_type: "{microservice_name}_computation"
  factors:
    primary_computation:
      weight: 0.6
      calculation_method: "primary_algorithm"
      parameters:
        threshold: 0.8
      normalization_enabled: true
      caching_enabled: true
    secondary_computation:
      weight: 0.3
      calculation_method: "secondary_algorithm"
      parameters:
        factor: 1.5
      normalization_enabled: true
      caching_enabled: true
    validation:
      weight: 0.1
      calculation_method: "validation_check"
      parameters:
        strict_mode: true
      normalization_enabled: true
      caching_enabled: false"""

    def _build_performance_requirements(self, node_type: str) -> str:
        """Build performance requirements based on node type"""
        if node_type == "COMPUTE":
            return "  single_operation_max_ms: 2000"
        elif node_type == "EFFECT":
            return "  max_response_time_ms: 500"
        elif node_type == "REDUCER":
            return "  aggregation_window_ms: 1000\n  max_aggregation_delay_ms: 5000"
        elif node_type == "ORCHESTRATOR":
            return "  workflow_timeout_ms: 30000\n  coordination_overhead_ms: 100"
        else:
            return "  max_execution_time_ms: 1000"

    def _build_primary_events(self, node_type: str, microservice_name: str) -> str:
        """Build primary events list"""
        events = []
        if node_type == "EFFECT":
            events = [
                f"{microservice_name}_created",
                f"{microservice_name}_updated",
                f"{microservice_name}_deleted",
            ]
        elif node_type == "COMPUTE":
            events = [f"{microservice_name}_computed", f"{microservice_name}_validated"]
        elif node_type == "REDUCER":
            events = [f"{microservice_name}_aggregated", f"{microservice_name}_reduced"]
        elif node_type == "ORCHESTRATOR":
            events = [
                f"{microservice_name}_workflow_started",
                f"{microservice_name}_workflow_completed",
            ]
        else:
            events = [f"{microservice_name}_executed"]

        return f'["{events[0]}", "{events[1] if len(events) > 1 else events[0]}"]'

    def _build_service_resolution(self, analysis_result: PRDAnalysisResult) -> str:
        """Build service resolution configuration"""
        if "Kafka" in analysis_result.external_systems or "EventBus" in str(
            analysis_result.recommended_mixins
        ):
            return '''  event_bus:
    protocol: "ProtocolEventBus"
    strategy: "hybrid"
    primary: "kafka"
    fallback: "event_bus_client"
    discovery: "consul"'''
        else:
            return "  # No service resolution required"

    def _build_infrastructure(self, analysis_result: PRDAnalysisResult) -> str:
        """Build infrastructure configuration"""
        if "Kafka" in analysis_result.external_systems:
            return """  event_bus: {strategy: "hybrid", primary: "kafka", fallback: "http", consul_discovery: true}"""
        else:
            return "  # No special infrastructure requirements"

    def _build_constraint_definitions(
        self, microservice_name: str, node_type: str
    ) -> str:
        """Build constraint definitions"""
        return f'''    operation_type: "string type with values [create, read, update, delete]"
    input_data: "dict type required for {microservice_name} operations"
    result_data: "dict type for operation results"'''

    def _generate_node_manifest(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: PRDAnalysisResult,
        context: Dict[str, Any],
    ) -> str:
        """Generate node.manifest.yaml file"""
        import hashlib
        from uuid import uuid4

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()
        node_uuid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Generate hash (placeholder - in production would hash actual content)
        content_hash = hashlib.sha256(
            f"{microservice_name}_{node_type}_{now}".encode()
        ).hexdigest()

        # Build capabilities
        capabilities = self._build_capabilities_list(analysis_result, node_type)

        # Build protocols
        protocols = self._build_protocols_list(node_type)

        # Build dependencies for manifest
        dependencies_manifest = self._build_dependencies_manifest(analysis_result)

        # Build test cases
        canonical_test_cases = self._build_canonical_test_cases(
            microservice_name, node_type
        )

        # Build external endpoints
        external_endpoints = self._build_external_endpoints(analysis_result)

        # Build audit events
        audit_events = self._build_audit_events(microservice_name, node_type)

        # Build tags
        tags = self._build_tags(domain, node_type, analysis_result)

        # Determine configuration values
        initialization_order = 3
        max_memory_mb = 512
        max_cpu_percent = 40
        timeout_seconds = 120
        min_coverage = 85.0
        processes_sensitive_data = "false"
        data_classification = "internal"
        requires_network_access = (
            "true" if analysis_result.external_systems else "false"
        )

        manifest = f"""schema_version: {{major: 1, minor: 0, patch: 0}}
name: "node_{domain}_{microservice_name}_{node_type_lower}"
uuid: "{node_uuid}"
author: "OmniClaude Code Generation"
created_at: "{now}"
last_modified_at: "{now}"
description: "{analysis_result.parsed_prd.description}"
state_contract: "state_contract://{microservice_name}_{node_type_lower}_schema.json"
lifecycle: "active"
hash: "{content_hash}"
entrypoint:
  type: "python"
  target: "v1_0_0/node.py"
namespace: "omninode.generated.{domain}.node_{microservice_name}_{node_type_lower}"
meta_type: "node"
runtime_language_hint: "python>=3.11"

# === NODE CAPABILITIES ===
capabilities:
{capabilities}

protocols_supported:
{protocols}

dependencies:
{dependencies_manifest}

# === VERSION MANAGEMENT (via x_extensions) ===
x_extensions:
  version_management:
    # Current version information
    current_stable: {{major: 1, minor: 0, patch: 0}}
    current_development: null

    # Version catalog with lifecycle states
    versions:
      v1_0_0:
        version: {{major: 1, minor: 0, patch: 0}}
        status: "active"
        release_date: "{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        breaking_changes: false
        recommended: true
        deprecation_date: null
        end_of_life: null

    # Discovery configuration for services loading this node
    discovery:
      auto_load_strategy: "current_stable"
      fallback_versions: [{{major: 1, minor: 0, patch: 0}}]
      version_directory_pattern: "v{{major}}_{{minor}}_{{patch}}"
      implementation_file: "node.py"
      contract_file: "contract.yaml"
      main_class_name: "Node{pascal_name}{node_type.capitalize()}"

    # Service loading configuration
    service_integration:
      load_as_module: true
      requires_separate_port: false
      initialization_order: {initialization_order}
      shutdown_timeout: 30
      health_check_via_service: true

# === EXECUTION METADATA ===
execution_mode: "async"
execution_constraints:
  max_memory_mb: {max_memory_mb}
  max_cpu_percent: {max_cpu_percent}
  timeout_seconds: {timeout_seconds}

# === TESTING METADATA ===
testing:
  required_ci_tiers:
    - "mock"
    - "integration"
  minimum_coverage_percentage: {min_coverage}
  canonical_test_case_ids:
{canonical_test_cases}

# === SECURITY METADATA ===
data_handling_declaration:
  processes_sensitive_data: {processes_sensitive_data}
  data_classification: "{data_classification}"

security_context:
  requires_network_access: {requires_network_access}
  external_endpoints:
{external_endpoints}

# === LOGGING CONFIGURATION ===
logging_config:
  level: "info"
  format: "json"
  audit_events:
{audit_events}

tags:
{tags}
"""

        return manifest

    def _build_capabilities_list(
        self, analysis_result: PRDAnalysisResult, node_type: str
    ) -> str:
        """Build capabilities list for manifest"""
        capabilities = []

        # Extract from functional requirements
        for req in analysis_result.parsed_prd.functional_requirements[:3]:
            cap_name = self._requirement_to_action_name(req)
            capabilities.append(f'  - "{cap_name}"')

        # Add node type specific capabilities
        if node_type == "EFFECT":
            capabilities.append('  - "external_io"')
        elif node_type == "COMPUTE":
            capabilities.append('  - "pure_computation"')
        elif node_type == "REDUCER":
            capabilities.append('  - "state_aggregation"')
        elif node_type == "ORCHESTRATOR":
            capabilities.append('  - "workflow_coordination"')

        return "\n".join(capabilities) if capabilities else "  []"

    def _build_protocols_list(self, node_type: str) -> str:
        """Build protocols list for manifest"""
        protocols = []

        if node_type == "EFFECT":
            protocols = ['"ProtocolNodeEffect"', '"ProtocolEventBus"']
        elif node_type == "COMPUTE":
            protocols = ['"ProtocolNodeCompute"']
        elif node_type == "REDUCER":
            protocols = ['"ProtocolNodeReducer"', '"ProtocolEventBus"']
        elif node_type == "ORCHESTRATOR":
            protocols = [
                '"ProtocolNodeOrchestrator"',
                '"ProtocolEventBus"',
                '"ProtocolWorkflow"',
            ]

        return "\n  - " + "\n  - ".join(protocols) if protocols else "  []"

    def _build_dependencies_manifest(self, analysis_result: PRDAnalysisResult) -> str:
        """Build dependencies list for node manifest"""
        if not analysis_result.external_systems:
            return "  []"

        deps = []
        for system in analysis_result.external_systems[:3]:
            system_lower = system.lower().replace(" ", "_")

            # Proper URL scheme mapping with database name and config-based endpoints
            if "postgres" in system.lower() or "database" in system.lower():
                # Include database name in PostgreSQL URL
                target = f"postgresql://{self.config.postgres_host}:{self.config.postgres_port}/{self.config.postgres_db}"
            elif "redis" in system.lower() or "cache" in system.lower():
                target = f"redis://{self.config.redis_host}:{self.config.redis_port}"
            elif "kafka" in system.lower():
                # Handle kafka_bootstrap_servers that may already include scheme
                kafka_servers = self.config.kafka_bootstrap_servers
                if kafka_servers.startswith("kafka://"):
                    target = kafka_servers
                else:
                    target = f"kafka://{kafka_servers}"
            else:
                target = "http://localhost:8080"  # Default fallback

            deps.append(
                f'''  - name: "{system_lower}"
    type: "external_service"
    target: "{target}"
    binding: "runtime_lookup"
    optional: false
    description: "{system} service for data operations"'''
            )

        return "\n".join(deps)

    def _build_canonical_test_cases(
        self, microservice_name: str, node_type: str
    ) -> str:
        """Build canonical test cases list"""
        test_cases = [
            f'    - "test_{microservice_name}_{node_type.lower()}_basic"',
            f'    - "test_{microservice_name}_{node_type.lower()}_error_handling"',
            f'    - "test_{microservice_name}_{node_type.lower()}_performance"',
        ]
        return "\n".join(test_cases)

    def _build_external_endpoints(self, analysis_result: PRDAnalysisResult) -> str:
        """Build external endpoints list"""
        if not analysis_result.external_systems:
            return "    []"

        endpoints = []
        for system in analysis_result.external_systems[:3]:
            if "postgres" in system.lower() or "database" in system.lower():
                # Include database name in PostgreSQL URL
                endpoints.append(
                    f'    - "postgresql://{self.config.postgres_host}:{self.config.postgres_port}/{self.config.postgres_db}"'
                )
            elif "redis" in system.lower() or "cache" in system.lower():
                endpoints.append(
                    f'    - "redis://{self.config.redis_host}:{self.config.redis_port}"'
                )
            elif "kafka" in system.lower():
                # Handle kafka_bootstrap_servers that may already include scheme
                kafka_servers = self.config.kafka_bootstrap_servers
                if kafka_servers.startswith("kafka://"):
                    endpoints.append(f'    - "{kafka_servers}"')
                else:
                    endpoints.append(f'    - "kafka://{kafka_servers}"')

        return "\n".join(endpoints) if endpoints else "    []"

    def _build_audit_events(self, microservice_name: str, node_type: str) -> str:
        """Build audit events list"""
        events = [
            f'    - "{microservice_name}_initialized"',
            f'    - "{microservice_name}_executed"',
            f'    - "{microservice_name}_completed"',
            f'    - "{microservice_name}_error_occurred"',
        ]
        return "\n".join(events)

    def _build_tags(
        self, domain: str, node_type: str, analysis_result: PRDAnalysisResult
    ) -> str:
        """Build tags list"""
        tags = [
            f'  - "{domain}"',
            f'  - "{node_type.lower()}"',
            '  - "generated"',
            '  - "omniclaude"',
        ]

        # Add keywords from PRD
        for keyword in analysis_result.parsed_prd.extracted_keywords[:3]:
            tags.append(f'  - "{keyword}"')

        return "\n".join(tags)

    def _generate_version_manifest(
        self,
        microservice_name: str,
        node_type: str,
        domain: str,
        analysis_result: PRDAnalysisResult,
        context: Dict[str, Any],
    ) -> str:
        """Generate version.manifest.yaml file"""

        pascal_name = self._to_pascal_case(microservice_name)
        node_type_lower = node_type.lower()
        release_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Determine entry point
        if node_type == "EFFECT":
            entry_point = "execute_effect"
        elif node_type == "COMPUTE":
            entry_point = "execute_compute"
        elif node_type == "REDUCER":
            entry_point = "execute_reduction"
        elif node_type == "ORCHESTRATOR":
            entry_point = "orchestrate_workflow"
        else:
            entry_point = "execute"

        # Configuration values
        min_coverage = 85
        min_memory_mb = 64
        max_memory_mb = 512
        cpu_cores = 2
        event_bus_required = (
            "true" if node_type in ["EFFECT", "REDUCER", "ORCHESTRATOR"] else "false"
        )
        processes_sensitive_data = "false"
        code_coverage = 85
        cyclomatic_complexity = 10
        maintainability_index = 80
        technical_debt_ratio = 0.08

        manifest = f"""# ONEX Version Manifest - {pascal_name} {node_type.capitalize()} v1.0.0
# Tier 3: Version-specific implementation details

# === VERSION IDENTITY ===
version: {{major: 1, minor: 0, patch: 0}}
version_string: {{major: 1, minor: 0, patch: 0}}
status: "active"
release_date: "{release_date}"
security_profile: "SP0_BOOTSTRAP"

# === IMPLEMENTATION ===
implementation:
  contract_file: "contract.yaml"
  main_implementation: "node.py"
  module_init: "__init__.py"

  model_files:
    - "models/model_{microservice_name}_input.py"
    - "models/model_{microservice_name}_output.py"
    - "models/model_{microservice_name}_config.py"
    - "models/model_{microservice_name}_{node_type_lower}_contract.py"

  enum_files:
    - "enums/enum_{microservice_name}_operation_type.py"

  contract_files:
    - "contract.yaml"

# === VALIDATION ===
validation:
  contract_compliance:
    onex_pattern: true
    required_fields: ["contract_version", "node_name", "node_type", "input_model", "output_model"]
    strong_typing: true

  testing_requirements:
    unit_tests: true
    integration_tests: true
    contract_validation: true
    coverage_minimum: {min_coverage}

# === DEPLOYMENT ===
deployment:
  execution_constraints:
    min_memory_mb: {min_memory_mb}
    max_memory_mb: {max_memory_mb}
    cpu_cores: {cpu_cores}

  runtime_requirements:
    python_version: ">=3.11"
    container_support: true
    event_bus_required: {event_bus_required}

# === SECURITY ===
security:
  data_handling:
    input_validation: "strict"
    output_sanitization: true
    sensitive_data: {processes_sensitive_data}

  security_context:
    sp0_compliant: true
    authentication_required: true
    authorization_levels: ["service"]

# === API SURFACE ===
api_surface:
  primary_entry_point: "{entry_point}"
  model_contracts:
    input: "Model{pascal_name}Input"
    output: "Model{pascal_name}Output"
    contract: "Model{pascal_name}{node_type.capitalize()}Contract"

# === QUALITY METRICS ===
quality_metrics:
  code_coverage: {code_coverage}
  cyclomatic_complexity: {cyclomatic_complexity}
  maintainability_index: {maintainability_index}
  technical_debt_ratio: {technical_debt_ratio}
"""

        return manifest

    def _generate_node_metadata(
        self,
        node_type: str,
        microservice_name: str,
        domain: str,
        analysis_result: PRDAnalysisResult,
    ) -> str:
        """Generate OmniNode Tool Metadata for generated node"""
        return f"""# === OmniNode:Tool_Metadata ===
metadata_version: 0.1
name: {microservice_name}_{node_type.lower()}
namespace: omninode.generated.{domain}
version: 1.0.0
type: node
category: generated
description: |
  {analysis_result.parsed_prd.description}
tags: [generated, {node_type.lower()}, {domain}]
author: OmniClaude Code Generation
license: MIT
autoupdate: false
test_suite: true
test_status: pending
classification:
  maturity: generated
  trust_score: {int(analysis_result.confidence_score * 100)}
# === /OmniNode:Tool_Metadata ===
"""

    async def cleanup_async(self, timeout: float = 5.0):
        """
        Cleanup template cache background tasks.

        Args:
            timeout: Maximum time to wait for tasks to complete (seconds)
        """
        if self.enable_cache and self.template_cache:
            await self.template_cache.cleanup_async(timeout)
            self.logger.debug("Template cache cleanup complete")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup cache."""
        await self.cleanup_async()
        return False

    def __del__(self):
        """Destructor - warn if cache has pending tasks."""
        if (
            self.enable_cache
            and self.template_cache
            and hasattr(self.template_cache, "_background_tasks")
        ):
            if self.template_cache._background_tasks:
                self.logger.warning(
                    f"OmniNodeTemplateEngine destroyed with template cache having "
                    f"{len(self.template_cache._background_tasks)} pending tasks. "
                    f"Use async context manager or cleanup_async() to avoid this."
                )
