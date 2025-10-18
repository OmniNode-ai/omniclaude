#!/usr/bin/env python3
"""
PRD Analyzer for Autonomous Code Generation

Uses omnibase_core and omnibase_spi dependencies to analyze PRDs and extract
requirements for OmniNode generation.
"""

import logging
from typing import Dict, Any, List, Optional
from uuid import UUID, uuid4
from datetime import datetime

# Import from omnibase_core
from omnibase_core.errors import OnexError, CoreErrorCode

# TODO: Add omnibase_spi imports when available
# from omnibase_spi.validation.tool_metadata_validator import ToolMetadataValidator
# from omnibase_spi.validation.one_protocol_compliance import ONEProtocolComplianceChecker

# Import legacy omniagent code
from .legacy.prd_parser import PRDParser, ModelParsedPRD
from .legacy.prd_decomposition_service import PRDDecompositionService, PRDDecompositionResult
from .version_config import get_config

logger = logging.getLogger(__name__)


class PRDAnalysisResult:
    """Result of PRD analysis with intelligence"""

    def __init__(
        self,
        session_id: UUID,
        correlation_id: UUID,
        prd_content: str,
        parsed_prd: ModelParsedPRD,
        decomposition_result: PRDDecompositionResult,
        node_type_hints: Dict[str, float],
        recommended_mixins: List[str],
        external_systems: List[str],
        quality_baseline: float,
        confidence_score: float,
    ):
        self.session_id = session_id
        self.correlation_id = correlation_id
        self.prd_content = prd_content
        self.parsed_prd = parsed_prd
        self.decomposition_result = decomposition_result
        self.node_type_hints = node_type_hints
        self.recommended_mixins = recommended_mixins
        self.external_systems = external_systems
        self.quality_baseline = quality_baseline
        self.confidence_score = confidence_score
        self.analysis_timestamp = datetime.utcnow()


class PRDAnalyzer:
    """PRD analyzer using omnibase_core and omnibase_spi"""

    def __init__(self):
        self.config = get_config()
        self.prd_parser = PRDParser()
        self.decomposition_service = PRDDecompositionService()
        # TODO: Initialize validators when omnibase_spi is available
        # self.metadata_validator = ToolMetadataValidator()
        # self.compliance_checker = ONEProtocolComplianceChecker()
        self.logger = logging.getLogger(__name__)

    async def analyze_prd(
        self, prd_content: str, workspace_context: Optional[Dict[str, Any]] = None
    ) -> PRDAnalysisResult:
        """
        Analyze PRD content and extract requirements for OmniNode generation.

        Args:
            prd_content: Raw PRD markdown content
            workspace_context: Optional workspace context

        Returns:
            PRDAnalysisResult with analysis and intelligence

        Raises:
            OnexError: If analysis fails
        """
        try:
            # Generate session and correlation IDs
            session_id = uuid4()
            correlation_id = uuid4()

            self.logger.info(f"Starting PRD analysis for session {session_id}")

            # Parse PRD content
            parsed_prd = await self._parse_prd_content(prd_content)

            # Decompose into tasks
            decomposition_result = await self._decompose_prd(parsed_prd)

            # Extract node type hints
            node_type_hints = self._extract_node_type_hints(parsed_prd)

            # Recommend mixins
            recommended_mixins = self._recommend_mixins(parsed_prd, decomposition_result)

            # Identify external systems
            external_systems = self._identify_external_systems(parsed_prd, decomposition_result)

            # Calculate quality baseline
            quality_baseline = self._calculate_quality_baseline(parsed_prd, decomposition_result)

            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(parsed_prd, decomposition_result, node_type_hints)

            result = PRDAnalysisResult(
                session_id=session_id,
                correlation_id=correlation_id,
                prd_content=prd_content,
                parsed_prd=parsed_prd,
                decomposition_result=decomposition_result,
                node_type_hints=node_type_hints,
                recommended_mixins=recommended_mixins,
                external_systems=external_systems,
                quality_baseline=quality_baseline,
                confidence_score=confidence_score,
            )

            self.logger.info(f"PRD analysis completed for session {session_id} with confidence {confidence_score:.2f}")
            return result

        except Exception as e:
            self.logger.error(f"PRD analysis failed: {str(e)}")
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message=f"PRD analysis failed: {str(e)}",
                details={"prd_length": len(prd_content) if prd_content else 0},
            )

    async def _parse_prd_content(self, prd_content: str) -> ModelParsedPRD:
        """Parse PRD content using legacy omniagent parser"""
        try:
            return self.prd_parser.parse(prd_content)
        except Exception as e:
            raise OnexError(
                code=CoreErrorCode.VALIDATION_ERROR,
                message=f"PRD parsing failed: {str(e)}",
                details={"content_length": len(prd_content)},
            )

    async def _decompose_prd(self, parsed_prd: ModelParsedPRD) -> PRDDecompositionResult:
        """Decompose PRD into tasks using legacy omniagent service"""
        try:
            # Convert parsed PRD to decomposition input format
            prd_text = f"# {parsed_prd.title}\n\n{parsed_prd.description}\n\n"
            prd_text += "## Functional Requirements\n"
            for req in parsed_prd.functional_requirements:
                prd_text += f"- {req}\n"
            prd_text += "\n## Features\n"
            for feature in parsed_prd.features:
                prd_text += f"- {feature}\n"

            return await self.decomposition_service.decompose_prd(prd_text)
        except Exception as e:
            raise OnexError(
                code=CoreErrorCode.OPERATION_FAILED,
                message=f"PRD decomposition failed: {str(e)}",
                details={"prd_title": parsed_prd.title},
            )

    def _extract_node_type_hints(self, parsed_prd: ModelParsedPRD) -> Dict[str, float]:
        """Extract node type hints from parsed PRD"""
        hints = {"EFFECT": 0.0, "COMPUTE": 0.0, "REDUCER": 0.0, "ORCHESTRATOR": 0.0}

        # Use omniagent parser's classification hints
        classification_hints = self.prd_parser.get_classification_hints(parsed_prd)

        # Map to our node types
        hints["EFFECT"] = classification_hints.get("EFFECT", 0.0)
        hints["COMPUTE"] = classification_hints.get("COMPUTE", 0.0)
        hints["REDUCER"] = classification_hints.get("REDUCER", 0.0)
        hints["ORCHESTRATOR"] = classification_hints.get("ORCHESTRATOR", 0.0)

        return hints

    def _recommend_mixins(self, parsed_prd: ModelParsedPRD, decomposition_result: PRDDecompositionResult) -> List[str]:
        """Recommend mixins based on PRD analysis"""
        mixins = []

        # Analyze requirements for mixin needs
        requirements_text = " ".join(parsed_prd.functional_requirements + parsed_prd.features).lower()

        # Event-driven patterns
        if any(keyword in requirements_text for keyword in ["event", "notification", "publish", "subscribe"]):
            mixins.append("MixinEventBus")

        # Caching patterns
        if any(keyword in requirements_text for keyword in ["cache", "caching", "performance", "speed"]):
            mixins.append("MixinCaching")

        # Health monitoring
        if any(keyword in requirements_text for keyword in ["health", "monitoring", "status", "alive"]):
            mixins.append("MixinHealthCheck")

        # Retry patterns
        if any(keyword in requirements_text for keyword in ["retry", "resilient", "fault", "error"]):
            mixins.append("MixinRetry")

        # Circuit breaker patterns
        if any(keyword in requirements_text for keyword in ["circuit", "breaker", "fallback", "timeout"]):
            mixins.append("MixinCircuitBreaker")

        # Logging patterns
        if any(keyword in requirements_text for keyword in ["log", "logging", "audit", "trace"]):
            mixins.append("MixinLogging")

        # Metrics patterns
        if any(keyword in requirements_text for keyword in ["metric", "monitoring", "analytics", "kpi"]):
            mixins.append("MixinMetrics")

        # Security patterns
        if any(keyword in requirements_text for keyword in ["security", "auth", "encrypt", "secure"]):
            mixins.append("MixinSecurity")

        # Validation patterns
        if any(keyword in requirements_text for keyword in ["validate", "validation", "check", "verify"]):
            mixins.append("MixinValidation")

        return mixins

    def _identify_external_systems(
        self, parsed_prd: ModelParsedPRD, decomposition_result: PRDDecompositionResult
    ) -> List[str]:
        """Identify external systems from PRD analysis"""
        external_systems = []

        # Check dependencies
        for dep in parsed_prd.dependencies:
            dep_lower = dep.lower()
            if "postgres" in dep_lower or "database" in dep_lower:
                external_systems.append("PostgreSQL")
            elif "redis" in dep_lower:
                external_systems.append("Redis")
            elif "kafka" in dep_lower or "redpanda" in dep_lower:
                external_systems.append("Kafka/Redpanda")
            elif "api" in dep_lower:
                external_systems.append("External API")
            elif "s3" in dep_lower or "storage" in dep_lower:
                external_systems.append("Object Storage")

        # Check technical details
        tech_text = " ".join(parsed_prd.technical_details).lower()
        if "postgres" in tech_text:
            external_systems.append("PostgreSQL")
        if "redis" in tech_text:
            external_systems.append("Redis")
        if "kafka" in tech_text:
            external_systems.append("Kafka/Redpanda")

        return list(set(external_systems))  # Remove duplicates

    def _calculate_quality_baseline(
        self, parsed_prd: ModelParsedPRD, decomposition_result: PRDDecompositionResult
    ) -> float:
        """Calculate quality baseline for generated code"""
        baseline = 0.5  # Start with 50%

        # Increase based on PRD completeness
        if parsed_prd.title and parsed_prd.description:
            baseline += 0.1
        if parsed_prd.functional_requirements:
            baseline += 0.1
        if parsed_prd.features:
            baseline += 0.1
        if parsed_prd.success_criteria:
            baseline += 0.1

        # Increase based on decomposition quality
        if decomposition_result.verification_successful:
            baseline += 0.1

        # Increase based on technical details
        if parsed_prd.technical_details:
            baseline += 0.1

        return min(baseline, 1.0)  # Cap at 100%

    def _calculate_confidence_score(
        self,
        parsed_prd: ModelParsedPRD,
        decomposition_result: PRDDecompositionResult,
        node_type_hints: Dict[str, float],
    ) -> float:
        """Calculate confidence score for the analysis"""
        confidence = 0.0

        # Base confidence from parsing
        if parsed_prd.word_count > 100:
            confidence += 0.2
        if parsed_prd.sections:
            confidence += 0.1

        # Confidence from decomposition
        if decomposition_result.verification_successful:
            confidence += 0.2
        if decomposition_result.total_tasks > 0:
            confidence += 0.1

        # Confidence from node type hints
        max_hint = max(node_type_hints.values()) if node_type_hints else 0.0
        confidence += max_hint * 0.3

        # Confidence from extracted keywords
        if parsed_prd.extracted_keywords:
            confidence += 0.1

        return min(confidence, 1.0)  # Cap at 100%

    async def validate_generated_metadata(self, metadata_content: str) -> Dict[str, Any]:
        """Validate generated node metadata using omnibase_spi"""
        # TODO: Implement when omnibase_spi is available
        return {
            "is_valid": True,
            "score": 0.8,
            "violations": [],
            "warnings": [],
            "suggestions": [],
            "compliance_level": "basic",
        }

    async def validate_code_compliance(self, code_content: str, node_type: str) -> Dict[str, Any]:
        """Validate generated code for O.N.E. protocol compliance"""
        # TODO: Implement when omnibase_spi is available
        return {
            "is_compliant": True,
            "compliance_score": 0.8,
            "violations": [],
            "warnings": [],
            "protocol_version": "0.1",
        }
