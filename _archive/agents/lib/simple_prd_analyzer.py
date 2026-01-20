#!/usr/bin/env python3
"""
Simple PRD Analyzer for Phase 0

A simplified PRD analyzer that doesn't depend on legacy omniagent code.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

# Import from omnibase_core
from omnibase_core.errors import EnumCoreErrorCode, OnexError

logger = logging.getLogger(__name__)


@dataclass
class SimpleParsedPRD:
    """Simple parsed PRD model"""

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
class SimpleDecompositionResult:
    """Simple decomposition result"""

    tasks: list[dict[str, Any]]
    total_tasks: int
    verification_successful: bool


class SimplePRDAnalyzer:
    """Simple PRD analyzer for Phase 0"""

    def __init__(self, enable_ml_recommendations: bool = False) -> None:
        """
        Initialize simple PRD analyzer.

        Args:
            enable_ml_recommendations: Whether to enable ML recommendations.
                This parameter exists for API compatibility with PRDAnalyzer
                but is not used in the simple implementation.
        """
        self.logger = logging.getLogger(__name__)
        # Store for API compatibility (not used in simple implementation)
        self.enable_ml = enable_ml_recommendations

    async def analyze_prd(
        self, prd_content: str, workspace_context: dict[str, Any] | None = None
    ) -> "SimplePRDAnalysisResult":
        """Analyze PRD content and extract requirements"""
        try:
            # Validate PRD content is not empty
            if not prd_content or not prd_content.strip():
                raise OnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="PRD content cannot be empty",
                    context={
                        "prd_content_length": len(prd_content) if prd_content else 0
                    },
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

            result = SimplePRDAnalysisResult(
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

    def _parse_prd_content(self, prd_content: str) -> SimpleParsedPRD:
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

        return SimpleParsedPRD(
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

    def _decompose_prd(self, parsed_prd: SimpleParsedPRD) -> SimpleDecompositionResult:
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

        return SimpleDecompositionResult(
            tasks=tasks, total_tasks=len(tasks), verification_successful=True
        )

    def _extract_node_type_hints(self, parsed_prd: SimpleParsedPRD) -> dict[str, float]:
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

    def _recommend_mixins(
        self,
        parsed_prd: SimpleParsedPRD,
        decomposition_result: SimpleDecompositionResult,
    ) -> list[str]:
        """Recommend mixins based on PRD analysis"""
        mixins = []

        # Analyze requirements for mixin needs
        requirements_text = " ".join(
            parsed_prd.functional_requirements + parsed_prd.features
        ).lower()

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
        parsed_prd: SimpleParsedPRD,
        decomposition_result: SimpleDecompositionResult,
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
        parsed_prd: SimpleParsedPRD,
        decomposition_result: SimpleDecompositionResult,
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
        parsed_prd: SimpleParsedPRD,
        decomposition_result: SimpleDecompositionResult,
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
class SimplePRDAnalysisResult:
    """Result of simple PRD analysis"""

    session_id: UUID
    correlation_id: UUID
    prd_content: str
    parsed_prd: SimpleParsedPRD
    decomposition_result: SimpleDecompositionResult
    node_type_hints: dict[str, float]
    recommended_mixins: list[str]
    external_systems: list[str]
    quality_baseline: float
    confidence_score: float
    analysis_timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# Aliases for compatibility
ParsedPRD = SimpleParsedPRD
DecompositionResult = SimpleDecompositionResult
PRDAnalyzer = SimplePRDAnalyzer
PRDAnalysisResult = SimplePRDAnalysisResult
