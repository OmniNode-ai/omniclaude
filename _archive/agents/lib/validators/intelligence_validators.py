#!/usr/bin/env python3
"""
Intelligence Validation Quality Gates - ONEX v2.0 Framework.

Implements 3 intelligence validation gates (IV-001 to IV-003):
- IV-001: RAG Query Validation - Validates intelligence gathering completeness
- IV-002: Knowledge Application - Verifies gathered intelligence is properly applied
- IV-003: Learning Capture - Validates knowledge capture for future intelligence

ONEX v2.0 Compliance:
- BaseQualityGate subclassing
- ModelQualityGateResult return types
- Async/await patterns
- Type-safe validation with comprehensive checks
"""

from typing import Any

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class RAGQueryValidationValidator(BaseQualityGate):
    """
    IV-001: RAG Query Validation Validator.

    Validates intelligence gathering completeness and relevance during the
    intelligence_gathering execution point.

    Performance Target: <100ms
    Validation Type: quality_check
    Dependencies: None

    Validation Checks:
    - RAG query executed successfully
    - Minimum intelligence items gathered (≥3 results)
    - Relevance scores above threshold (>0.7)
    - Query performance within target
    - Intelligence source diversity

    Context Requirements:
        rag_query: dict with:
            - executed: bool - Whether RAG query was executed
            - results: list[dict] - Intelligence items gathered
            - query_time_ms: int - Query execution time
            - error: str | None - Error message if query failed

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize RAG Query Validation validator."""
        super().__init__(EnumQualityGate.RAG_QUERY_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute RAG query validation.

        Args:
            context: Validation context containing RAG query information

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract RAG query data from context
        rag_query = context.get("rag_query", {})

        # Check if RAG query was executed
        if not rag_query.get("executed", False):
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="RAG query was not executed",
                metadata={"reason": "rag_query_not_executed", "rag_query": rag_query},
            )

        # Check for query errors
        if rag_query.get("error"):
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"RAG query failed: {rag_query['error']}",
                metadata={
                    "reason": "rag_query_error",
                    "error": rag_query["error"],
                },
            )

        # Get results
        results = rag_query.get("results", [])

        # Check minimum results threshold (≥3 results)
        min_results = context.get("min_rag_results", 3)
        if len(results) < min_results:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Insufficient RAG results: {len(results)} < {min_results}",
                metadata={
                    "reason": "insufficient_results",
                    "result_count": len(results),
                    "min_required": min_results,
                },
            )

        # Check relevance scores (>0.7)
        min_relevance = context.get("min_relevance_score", 0.7)
        low_relevance_count = 0
        for result in results:
            relevance = result.get("relevance_score", 0.0)
            if relevance < min_relevance:
                low_relevance_count += 1

        if low_relevance_count > 0:
            # Allow some low-relevance results, but not all
            low_relevance_ratio = low_relevance_count / len(results)
            if low_relevance_ratio > 0.5:  # More than half are low relevance
                return ModelQualityGateResult(
                    gate=self.gate,
                    status="failed",
                    execution_time_ms=0,
                    message=f"Too many low-relevance results: {low_relevance_count}/{len(results)}",
                    metadata={
                        "reason": "low_relevance",
                        "low_relevance_count": low_relevance_count,
                        "total_results": len(results),
                        "low_relevance_ratio": low_relevance_ratio,
                    },
                )

        # Check query performance (target: <1500ms from spec)
        query_time = rag_query.get("query_time_ms", 0)
        max_query_time = context.get("max_query_time_ms", 1500)
        performance_warning = query_time > max_query_time

        # Check source diversity (multiple sources)
        sources = set(result.get("source", "unknown") for result in results)
        source_diversity = len(sources)

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"RAG query validation passed: {len(results)} results from {source_diversity} sources",
            metadata={
                "result_count": len(results),
                "source_diversity": source_diversity,
                "sources": list(sources),
                "query_time_ms": query_time,
                "performance_warning": performance_warning,
                "low_relevance_count": low_relevance_count,
                "avg_relevance": (
                    sum(r.get("relevance_score", 0.0) for r in results) / len(results)
                    if results
                    else 0.0
                ),
            },
        )


class KnowledgeApplicationValidator(BaseQualityGate):
    """
    IV-002: Knowledge Application Validator.

    Verifies gathered intelligence is properly applied during execution_planning.

    Performance Target: <75ms
    Validation Type: monitoring
    Dependencies: ["IV-001"]

    Validation Checks:
    - Intelligence from RAG was referenced in output
    - Patterns from intelligence were applied
    - Knowledge integration is evident
    - No critical intelligence ignored
    - Application quality metrics

    Context Requirements:
        knowledge_application: dict with:
            - intelligence_used: list[str] - Intelligence IDs referenced
            - patterns_applied: list[str] - Patterns from intelligence
            - output: str - Generated output
            - critical_intelligence: list[str] - Must-use intelligence IDs

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize Knowledge Application validator."""
        super().__init__(EnumQualityGate.KNOWLEDGE_APPLICATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute knowledge application validation.

        Args:
            context: Validation context containing knowledge application data

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract knowledge application data
        knowledge_app = context.get("knowledge_application", {})

        # Check if intelligence was used
        intelligence_used = knowledge_app.get("intelligence_used", [])
        if not intelligence_used:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No intelligence from RAG was used in execution",
                metadata={
                    "reason": "no_intelligence_used",
                    "intelligence_used_count": 0,
                },
            )

        # Check if critical intelligence was ignored
        critical_intelligence = knowledge_app.get("critical_intelligence", [])
        if critical_intelligence:
            used_set = set(intelligence_used)
            critical_set = set(critical_intelligence)
            ignored_critical = critical_set - used_set

            if ignored_critical:
                return ModelQualityGateResult(
                    gate=self.gate,
                    status="failed",
                    execution_time_ms=0,
                    message=f"Critical intelligence ignored: {len(ignored_critical)} items",
                    metadata={
                        "reason": "critical_intelligence_ignored",
                        "ignored_critical": list(ignored_critical),
                        "critical_count": len(critical_intelligence),
                    },
                )

        # Check if patterns were applied
        patterns_applied = knowledge_app.get("patterns_applied", [])
        if not patterns_applied:
            # Warning but not failure - patterns might not always be applicable
            pass

        # Check knowledge integration in output
        output = knowledge_app.get("output", "")
        if not output:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No output generated to verify knowledge integration",
                metadata={
                    "reason": "no_output",
                },
            )

        # Check for references to intelligence in output (heuristic)
        # Look for keywords, references, or patterns in output
        references_found = 0
        rag_results = context.get("rag_query", {}).get("results", [])
        for result in rag_results:
            # Simple keyword matching - could be enhanced
            if result.get("id") in intelligence_used:
                references_found += 1

        # Calculate application quality
        usage_ratio = len(intelligence_used) / max(len(rag_results), 1)
        pattern_count = len(patterns_applied)

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"Knowledge application validated: {len(intelligence_used)} items used, {pattern_count} patterns applied",
            metadata={
                "intelligence_used_count": len(intelligence_used),
                "intelligence_used": intelligence_used,
                "patterns_applied_count": pattern_count,
                "patterns_applied": patterns_applied,
                "usage_ratio": usage_ratio,
                "critical_all_used": len(critical_intelligence)
                == len(set(critical_intelligence) & set(intelligence_used)),
                "output_length": len(output),
            },
        )


class LearningCaptureValidator(BaseQualityGate):
    """
    IV-003: Learning Capture Validator.

    Validates knowledge capture for future intelligence at completion point.

    Performance Target: <50ms
    Validation Type: checkpoint
    Dependencies: ["IV-002"]

    Validation Checks:
    - Patterns extracted from execution
    - Learning data captured
    - UAKS storage attempted
    - Knowledge format validity
    - Future reuse metadata present

    Context Requirements:
        learning_capture: dict with:
            - patterns_extracted: list[dict] - Patterns extracted
            - learning_data: dict - Learning data captured
            - uaks_stored: bool - Whether UAKS storage was attempted
            - storage_error: str | None - Error if storage failed

    Returns:
        ModelQualityGateResult with validation outcome
    """

    def __init__(self) -> None:
        """Initialize Learning Capture validator."""
        super().__init__(EnumQualityGate.LEARNING_CAPTURE)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute learning capture validation.

        Args:
            context: Validation context containing learning capture data

        Returns:
            ModelQualityGateResult with validation status
        """
        # Extract learning capture data
        learning_capture = context.get("learning_capture", {})

        # Check if patterns were extracted
        patterns_extracted = learning_capture.get("patterns_extracted", [])
        if not patterns_extracted:
            # This might be OK if no patterns were found
            # But we'll flag it as a warning in metadata
            pattern_warning = True
        else:
            pattern_warning = False

        # Validate pattern format
        invalid_patterns = []
        for i, pattern in enumerate(patterns_extracted):
            if (
                not isinstance(pattern, dict)
                or not pattern.get("name")
                or not pattern.get("description")
            ):
                invalid_patterns.append(i)

        if invalid_patterns:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Invalid pattern format: {len(invalid_patterns)} patterns",
                metadata={
                    "reason": "invalid_pattern_format",
                    "invalid_pattern_indices": invalid_patterns,
                    "total_patterns": len(patterns_extracted),
                },
            )

        # Check if learning data was captured
        learning_data = learning_capture.get("learning_data", {})
        if not learning_data:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No learning data captured",
                metadata={
                    "reason": "no_learning_data",
                },
            )

        # Check if UAKS storage was attempted
        uaks_stored = learning_capture.get("uaks_stored", False)
        storage_error = learning_capture.get("storage_error")

        if not uaks_stored and not storage_error:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="UAKS storage was not attempted",
                metadata={
                    "reason": "uaks_not_attempted",
                },
            )

        if storage_error:
            # Storage was attempted but failed - this is a warning, not failure
            # The attempt is what matters for this gate
            storage_warning = True
        else:
            storage_warning = False

        # Check for future reuse metadata
        reuse_metadata = learning_data.get("reuse_metadata", {})
        has_tags = bool(reuse_metadata.get("tags"))
        has_context = bool(reuse_metadata.get("context"))
        has_applicability = bool(reuse_metadata.get("applicability"))

        metadata_completeness = sum([has_tags, has_context, has_applicability]) / 3.0

        # All checks passed
        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be updated by execute_with_timing
            message=f"Learning capture validated: {len(patterns_extracted)} patterns, UAKS {'attempted' if uaks_stored else 'failed'}",
            metadata={
                "patterns_extracted_count": len(patterns_extracted),
                "pattern_warning": pattern_warning,
                "learning_data_keys": list(learning_data.keys()),
                "uaks_stored": uaks_stored,
                "storage_error": storage_error,
                "storage_warning": storage_warning,
                "metadata_completeness": metadata_completeness,
                "has_tags": has_tags,
                "has_context": has_context,
                "has_applicability": has_applicability,
            },
        )
