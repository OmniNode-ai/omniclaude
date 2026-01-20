#!/usr/bin/env python3
"""
PRD Analyzer for Phase 0

A PRD analyzer that doesn't depend on legacy omniagent code.
Updated for Framework: ML-powered mixin recommendations.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from omnibase_core.errors import EnumCoreErrorCode, OnexError

# Framework: ML-powered mixin compatibility (optional import)
try:
    from .mixin_compatibility import MixinCompatibilityManager

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ParsedPRD:
    """Parsed PRD model"""

    title: str
    description: str
    functional_requirements: list[str]
    features: list[str]
    success_criteria: list[str]
    technical_details: list[str]
    dependencies: list[str]
    extracted_keywords: list[str]
    sections: list[str]
    word_count: int


@dataclass
class DecompositionResult:
    """Decomposition result"""

    tasks: list[dict[str, Any]]
    total_tasks: int
    verification_successful: bool


class PRDAnalyzer:
    """PRD analyzer for Phase 0"""

    def __init__(self, enable_ml_recommendations: bool = True):
        """
        Initialize PRD analyzer.

        Args:
            enable_ml_recommendations: Whether to use ML-powered mixin recommendations
        """
        self.logger = logging.getLogger(__name__)
        self.mixin_manager: MixinCompatibilityManager | None = None

        # Framework: Initialize ML-powered mixin compatibility manager
        self.enable_ml = enable_ml_recommendations and ML_AVAILABLE
        if self.enable_ml:
            try:
                self.mixin_manager = MixinCompatibilityManager(enable_ml=True)
                self.logger.info("ML-powered mixin recommendations enabled")
            except Exception as e:
                self.logger.warning(
                    f"Failed to initialize ML recommendations: {e}. Using rule-based fallback."
                )
                self.enable_ml = False
                self.mixin_manager = None

    async def analyze_prd(
        self, prd_content: str, workspace_context: dict[str, Any] | None = None
    ) -> "PRDAnalysisResult":
        """Analyze PRD content and extract requirements"""
        try:
            # Validate PRD content
            if not prd_content or not prd_content.strip():
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="PRD content cannot be empty",
                    details={"prd_length": len(prd_content) if prd_content else 0},
                )

            session_id = uuid4()
            correlation_id = uuid4()

            self.logger.info(f"Starting simple PRD analysis for session {session_id}")

            # Parse PRD content
            parsed_prd = self._parse_prd_content(prd_content)

            # Decompose into tasks
            decomposition_result = self._decompose_prd(parsed_prd)

            # Extract node type hints
            node_type_hints = self._extract_node_type_hints(parsed_prd)

            # Recommend mixins
            recommended_mixins = self._recommend_mixins(
                parsed_prd, decomposition_result
            )

            # Identify external systems
            external_systems = self._identify_external_systems(
                parsed_prd, decomposition_result
            )

            # Calculate quality baseline
            quality_baseline = self._calculate_quality_baseline(
                parsed_prd, decomposition_result
            )

            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                parsed_prd, decomposition_result, node_type_hints
            )

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

            self.logger.info(
                f"Simple PRD analysis completed for session {session_id} with confidence {confidence_score:.2f}"
            )
            return result

        except Exception as e:
            self.logger.error(f"Simple PRD analysis failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Simple PRD analysis failed: {str(e)}",
                details={"prd_length": len(prd_content) if prd_content else 0},
            )

    def _parse_prd_content(self, prd_content: str) -> ParsedPRD:
        """Parse PRD content using simple regex patterns"""
        # Extract title
        title_match = re.search(r"^#\s+(.+)$", prd_content, re.MULTILINE)
        title = title_match.group(1) if title_match else "Untitled PRD"

        # Extract description
        description_match = re.search(
            r"## Overview\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        description = description_match.group(1).strip() if description_match else ""

        # Extract functional requirements
        requirements = []
        req_match = re.search(
            r"## Functional Requirements\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        if req_match:
            req_text = req_match.group(1)
            requirements = [
                line.strip("- ").strip()
                for line in req_text.split("\n")
                if line.strip().startswith("-")
            ]

        # Extract features
        features = []
        features_match = re.search(
            r"## Features\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        if features_match:
            features_text = features_match.group(1)
            features = [
                line.strip("- ").strip()
                for line in features_text.split("\n")
                if line.strip().startswith("-")
            ]

        # Extract success criteria
        success_criteria = []
        success_match = re.search(
            r"## Success Criteria\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        if success_match:
            success_text = success_match.group(1)
            success_criteria = [
                line.strip("- ").strip()
                for line in success_text.split("\n")
                if line.strip().startswith("-")
            ]

        # Extract technical details
        technical_details = []
        tech_match = re.search(
            r"## Technical Details\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        if tech_match:
            tech_text = tech_match.group(1)
            technical_details = [
                line.strip("- ").strip()
                for line in tech_text.split("\n")
                if line.strip().startswith("-")
            ]

        # Extract dependencies
        dependencies = []
        deps_match = re.search(
            r"## Dependencies\s*\n(.+?)(?=\n##|\Z)", prd_content, re.DOTALL
        )
        if deps_match:
            deps_text = deps_match.group(1)
            dependencies = [
                line.strip("- ").strip()
                for line in deps_text.split("\n")
                if line.strip().startswith("-")
            ]

        # Extract keywords
        all_text = (
            title
            + " "
            + description
            + " "
            + " ".join(requirements)
            + " "
            + " ".join(features)
        )
        keywords = re.findall(r"\b[A-Z][a-z]+\b", all_text)
        keywords = list(set(keywords))[:10]  # Top 10 unique keywords

        # Extract sections
        sections = re.findall(r"^## (.+)$", prd_content, re.MULTILINE)

        # Count words
        word_count = len(prd_content.split())

        return ParsedPRD(
            title=title,
            description=description,
            functional_requirements=requirements,
            features=features,
            success_criteria=success_criteria,
            technical_details=technical_details,
            dependencies=dependencies,
            extracted_keywords=keywords,
            sections=sections,
            word_count=word_count,
        )

    def _decompose_prd(self, parsed_prd: ParsedPRD) -> DecompositionResult:
        """Decompose PRD into tasks"""
        tasks = []

        # Create tasks from functional requirements
        for i, req in enumerate(parsed_prd.functional_requirements):
            tasks.append(
                {
                    "id": f"task_{i+1}",
                    "title": req,
                    "description": f"Implement {req}",
                    "priority": (
                        "high"
                        if "authentication" in req.lower() or "security" in req.lower()
                        else "medium"
                    ),
                    "complexity": "high" if len(req.split()) > 10 else "medium",
                }
            )

        # Create tasks from features
        for i, feature in enumerate(parsed_prd.features):
            tasks.append(
                {
                    "id": f"feature_{i+1}",
                    "title": feature,
                    "description": f"Implement {feature}",
                    "priority": "medium",
                    "complexity": "medium",
                }
            )

        return DecompositionResult(
            tasks=tasks, total_tasks=len(tasks), verification_successful=True
        )

    def _extract_node_type_hints(self, parsed_prd: ParsedPRD) -> dict[str, float]:
        """Extract node type hints from parsed PRD"""
        hints = {"EFFECT": 0.0, "COMPUTE": 0.0, "REDUCER": 0.0, "ORCHESTRATOR": 0.0}

        # Analyze text for node type indicators
        all_text = (
            parsed_prd.title
            + " "
            + parsed_prd.description
            + " "
            + " ".join(parsed_prd.functional_requirements)
            + " "
            + " ".join(parsed_prd.features)
        ).lower()

        # EFFECT indicators
        effect_indicators = [
            "create",
            "update",
            "delete",
            "modify",
            "change",
            "write",
            "store",
        ]
        effect_score = sum(
            1 for indicator in effect_indicators if indicator in all_text
        )
        hints["EFFECT"] = min(effect_score / 10.0, 1.0)

        # COMPUTE indicators
        compute_indicators = [
            "calculate",
            "process",
            "analyze",
            "compute",
            "process",
            "algorithm",
        ]
        compute_score = sum(
            1 for indicator in compute_indicators if indicator in all_text
        )
        hints["COMPUTE"] = min(compute_score / 10.0, 1.0)

        # REDUCER indicators
        reducer_indicators = [
            "aggregate",
            "summarize",
            "reduce",
            "combine",
            "merge",
            "consolidate",
        ]
        reducer_score = sum(
            1 for indicator in reducer_indicators if indicator in all_text
        )
        hints["REDUCER"] = min(reducer_score / 10.0, 1.0)

        # ORCHESTRATOR indicators
        orchestrator_indicators = [
            "coordinate",
            "orchestrate",
            "manage",
            "workflow",
            "pipeline",
            "sequence",
        ]
        orchestrator_score = sum(
            1 for indicator in orchestrator_indicators if indicator in all_text
        )
        hints["ORCHESTRATOR"] = min(orchestrator_score / 10.0, 1.0)

        # If no strong hints, default to EFFECT
        if max(hints.values()) < 0.1:
            hints["EFFECT"] = 0.5

        return hints

    async def _recommend_mixins_async(
        self,
        parsed_prd: ParsedPRD,
        decomposition_result: DecompositionResult,
        node_type_hints: dict[str, float],
    ) -> list[str]:
        """
        Recommend mixins based on PRD analysis using ML when available.

        Args:
            parsed_prd: Parsed PRD content
            decomposition_result: Task decomposition result
            node_type_hints: Node type hints with scores

        Returns:
            List of recommended mixin names
        """
        # Extract required capabilities from PRD
        requirements_text = " ".join(
            parsed_prd.functional_requirements + parsed_prd.features
        ).lower()
        required_capabilities = self._extract_capabilities(requirements_text)

        # Determine primary node type
        primary_node_type = (
            max(node_type_hints.items(), key=lambda x: x[1])[0]
            if node_type_hints
            else "EFFECT"
        )

        # Use ML recommendations if available
        if self.enable_ml and self.mixin_manager:
            try:
                recommendations = await self.mixin_manager.recommend_mixins(
                    node_type=primary_node_type,
                    required_capabilities=required_capabilities,
                    existing_mixins=[],
                    max_recommendations=8,
                )

                # Extract mixin names from recommendations
                mixins = [
                    rec.mixin_name for rec in recommendations if rec.confidence >= 0.6
                ]

                # Validate mixin set for compatibility
                if mixins:
                    mixin_set = await self.mixin_manager.validate_mixin_set(
                        mixins, primary_node_type
                    )

                    if mixin_set.warnings:
                        self.logger.warning(
                            f"Mixin compatibility warnings: {mixin_set.warnings}"
                        )

                self.logger.info(f"ML recommendations: {mixins}")
                return mixins

            except Exception as e:
                self.logger.warning(
                    f"ML recommendation failed: {e}. Using rule-based fallback."
                )
                # Fall through to rule-based recommendations

        # Fallback to rule-based recommendations
        return self._recommend_mixins_rule_based(requirements_text)

    def _extract_capabilities(self, requirements_text: str) -> list[str]:
        """Extract required capabilities from requirements text"""
        capabilities = []

        capability_keywords = {
            "cache": ["cache", "caching", "performance", "speed"],
            "logging": ["log", "logging", "audit", "trace"],
            "metrics": ["metric", "monitoring", "analytics", "kpi"],
            "health": ["health", "monitoring", "status", "alive"],
            "events": ["event", "notification", "publish", "subscribe"],
            "retry": ["retry", "resilient", "fault", "error"],
            "circuit-breaker": ["circuit", "breaker", "fallback", "timeout"],
            "validation": ["validate", "validation", "check", "verify"],
            "security": ["security", "auth", "encrypt", "secure"],
            "transaction": ["transaction", "commit", "rollback", "atomic"],
        }

        for capability, keywords in capability_keywords.items():
            if any(keyword in requirements_text for keyword in keywords):
                capabilities.append(capability)

        return capabilities

    def _recommend_mixins(
        self,
        parsed_prd: ParsedPRD,
        decomposition_result: DecompositionResult,
    ) -> list[str]:
        """
        Synchronous wrapper for mixin recommendations (for backward compatibility).

        Note: This is deprecated. Use _recommend_mixins_async for ML-powered recommendations.
        """
        requirements_text = " ".join(
            parsed_prd.functional_requirements + parsed_prd.features
        ).lower()
        return self._recommend_mixins_rule_based(requirements_text)

    def _recommend_mixins_rule_based(self, requirements_text: str) -> list[str]:
        """Rule-based mixin recommendations (fallback when ML not available)"""
        mixins = []

        # Event-driven patterns
        if any(
            keyword in requirements_text
            for keyword in ["event", "notification", "publish", "subscribe"]
        ):
            mixins.append("MixinEventBus")

        # Caching patterns
        if any(
            keyword in requirements_text
            for keyword in ["cache", "caching", "performance", "speed"]
        ):
            mixins.append("MixinCaching")

        # Health monitoring
        if any(
            keyword in requirements_text
            for keyword in ["health", "monitoring", "status", "alive"]
        ):
            mixins.append("MixinHealthCheck")

        # Retry patterns
        if any(
            keyword in requirements_text
            for keyword in ["retry", "resilient", "fault", "error"]
        ):
            mixins.append("MixinRetry")

        # Circuit breaker patterns
        if any(
            keyword in requirements_text
            for keyword in ["circuit", "breaker", "fallback", "timeout"]
        ):
            mixins.append("MixinCircuitBreaker")

        # Logging patterns
        if any(
            keyword in requirements_text
            for keyword in ["log", "logging", "audit", "trace"]
        ):
            mixins.append("MixinLogging")

        # Metrics patterns
        if any(
            keyword in requirements_text
            for keyword in ["metric", "monitoring", "analytics", "kpi"]
        ):
            mixins.append("MixinMetrics")

        # Security patterns
        if any(
            keyword in requirements_text
            for keyword in ["security", "auth", "encrypt", "secure"]
        ):
            mixins.append("MixinSecurity")

        # Validation patterns
        if any(
            keyword in requirements_text
            for keyword in ["validate", "validation", "check", "verify"]
        ):
            mixins.append("MixinValidation")

        return mixins

    def _identify_external_systems(
        self,
        parsed_prd: ParsedPRD,
        decomposition_result: DecompositionResult,
    ) -> list[str]:
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
        self,
        parsed_prd: ParsedPRD,
        decomposition_result: DecompositionResult,
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
        parsed_prd: ParsedPRD,
        decomposition_result: DecompositionResult,
        node_type_hints: dict[str, float],
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


@dataclass
class PRDAnalysisResult:
    """Result of PRD analysis"""

    session_id: UUID
    correlation_id: UUID
    prd_content: str
    parsed_prd: ParsedPRD
    decomposition_result: DecompositionResult
    node_type_hints: dict[str, float]
    recommended_mixins: list[str]
    external_systems: list[str]
    quality_baseline: float
    confidence_score: float
    analysis_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.now(UTC).replace(tzinfo=None)
