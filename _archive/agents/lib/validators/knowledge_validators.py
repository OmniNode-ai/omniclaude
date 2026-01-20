#!/usr/bin/env python3
"""
Knowledge Validation Quality Gates - KV-001 to KV-002

Validates knowledge capture, UAKS integration, and pattern recognition
for the ONEX Agent Framework.

ONEX v2.0 Compliance:
- UAKS (Unified Agent Knowledge System) integration validation
- Pattern extraction and quality scoring
- Learning contribution verification
- Performance targets: KV-001 (50ms), KV-002 (40ms)

Quality Gates:
- KV-001: UAKS Integration - Validates knowledge system contribution
- KV-002: Pattern Recognition - Validates pattern extraction and learning
"""

from typing import Any
from uuid import UUID

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class UAKSIntegrationValidator(BaseQualityGate):
    """
    KV-001: UAKS Integration Validator

    Validates unified agent knowledge system contribution at completion.

    Validation Checks:
    - UAKS storage attempted (even if placeholder)
    - Knowledge format valid (JSON/dict structure)
    - Required metadata present (execution_id, timestamp, agent_type, etc.)
    - Storage operation completed (or gracefully degraded)
    - Knowledge quality metrics included

    Performance Target: 50ms
    Execution Point: completion
    Validation Type: checkpoint
    Dependencies: None

    UAKS Knowledge Structure:
    {
        "execution_id": str(UUID),
        "timestamp": datetime,
        "agent_type": str,
        "success": bool,
        "duration_ms": int,
        "patterns_extracted": list[dict],
        "intelligence_used": list[dict],
        "quality_metrics": dict,
        "metadata": dict
    }

    Example:
        validator = UAKSIntegrationValidator()
        result = await validator.validate({
            "uaks_knowledge": {
                "execution_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc),
                "agent_type": "code_generator",
                "success": True,
                "duration_ms": 1500,
                "patterns_extracted": [...],
                "intelligence_used": [...],
                "quality_metrics": {"code_quality": 0.85},
                "metadata": {"context": "test"}
            }
        })
    """

    def __init__(self) -> None:
        """Initialize KV-001 validator."""
        super().__init__(EnumQualityGate.UAKS_INTEGRATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate UAKS integration and knowledge capture.

        Args:
            context: Must contain:
                - uaks_knowledge: Knowledge object to validate
                - Optional: uaks_storage_result: Storage operation result

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        # Check if UAKS knowledge is present
        uaks_knowledge = context.get("uaks_knowledge")
        if not uaks_knowledge:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="UAKS knowledge not found in context",
                metadata={"error": "missing_uaks_knowledge"},
            )

        # Validate knowledge is dict-like
        if not isinstance(uaks_knowledge, dict):
            issues.append(
                f"Knowledge must be dict, got {type(uaks_knowledge).__name__}"
            )

        # Check required metadata fields
        required_fields = [
            "execution_id",
            "timestamp",
            "agent_type",
            "success",
        ]

        missing_fields = [
            field for field in required_fields if field not in uaks_knowledge
        ]

        if missing_fields:
            issues.append(f"Missing required fields: {', '.join(missing_fields)}")

        # Validate execution_id format (should be UUID string)
        if "execution_id" in uaks_knowledge:
            try:
                UUID(str(uaks_knowledge["execution_id"]))
                metadata["execution_id_valid"] = True
            except (ValueError, AttributeError):
                issues.append(
                    f"Invalid execution_id format: {uaks_knowledge['execution_id']}"
                )
                metadata["execution_id_valid"] = False

        # Check recommended fields (warnings if missing)
        recommended_fields = [
            "duration_ms",
            "patterns_extracted",
            "intelligence_used",
            "quality_metrics",
            "metadata",
        ]

        missing_recommended = [
            field for field in recommended_fields if field not in uaks_knowledge
        ]

        if missing_recommended:
            warnings.append(
                f"Missing recommended fields: {', '.join(missing_recommended)}"
            )

        # Validate patterns_extracted if present
        if "patterns_extracted" in uaks_knowledge:
            patterns = uaks_knowledge["patterns_extracted"]
            if not isinstance(patterns, list):
                issues.append(
                    f"patterns_extracted must be list, got {type(patterns).__name__}"
                )
            else:
                metadata["patterns_count"] = len(patterns)

        # Validate quality_metrics if present
        if "quality_metrics" in uaks_knowledge:
            metrics = uaks_knowledge["quality_metrics"]
            if not isinstance(metrics, dict):
                issues.append(
                    f"quality_metrics must be dict, got {type(metrics).__name__}"
                )
            else:
                metadata["quality_metrics_count"] = len(metrics)

        # Check storage result if provided
        storage_result = context.get("uaks_storage_result")
        if storage_result:
            metadata["storage_attempted"] = True
            metadata["storage_success"] = storage_result.get("success", False)

            if not storage_result.get("success"):
                # Storage failed but not critical (graceful degradation)
                warnings.append(
                    f"UAKS storage failed: {storage_result.get('error', 'unknown')}"
                )
        else:
            # Storage not attempted yet (might be async)
            metadata["storage_attempted"] = False
            warnings.append("UAKS storage result not available")

        # Determine validation status
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"UAKS integration validation failed: {'; '.join(issues)}",
                metadata={
                    **metadata,
                    "issues": issues,
                    "warnings": warnings,
                },
            )

        # Build success message
        message_parts = ["UAKS integration validated"]
        if warnings:
            message_parts.append(f"({len(warnings)} warnings)")

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message="; ".join(message_parts),
            metadata={
                **metadata,
                "warnings": warnings,
                "validation_complete": True,
            },
        )


class PatternRecognitionValidator(BaseQualityGate):
    """
    KV-002: Pattern Recognition Validator

    Validates pattern extraction and learning contribution at completion.

    Validation Checks:
    - Patterns extracted from execution (≥1 pattern)
    - Pattern structure valid (type, name, description, confidence, etc.)
    - Pattern quality score >0.6
    - Patterns categorized correctly
    - Pattern storage attempted

    Performance Target: 40ms
    Execution Point: completion
    Validation Type: checkpoint
    Dependencies: KV-001

    Pattern Structure:
    {
        "pattern_type": str,  # "workflow", "code", "naming", etc.
        "pattern_name": str,
        "pattern_description": str,
        "confidence_score": float,  # 0.0-1.0
        "source_context": dict,
        "reuse_conditions": list[str],
        "examples": list[dict]
    }

    Example:
        validator = PatternRecognitionValidator()
        result = await validator.validate({
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "sequential_validation",
                    "pattern_description": "Input -> Process -> Output validation flow",
                    "confidence_score": 0.85,
                    "source_context": {"agent": "code_generator"},
                    "reuse_conditions": ["validation_workflows"],
                    "examples": [{"input": "...", "output": "..."}]
                }
            ]
        })
    """

    # Valid pattern types
    VALID_PATTERN_TYPES = {
        "workflow",
        "code",
        "naming",
        "architecture",
        "error_handling",
        "performance",
        "testing",
        "integration",
    }

    # Minimum confidence for pattern quality
    MIN_CONFIDENCE_SCORE = 0.6

    def __init__(self) -> None:
        """Initialize KV-002 validator."""
        super().__init__(EnumQualityGate.PATTERN_RECOGNITION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Validate pattern extraction and quality.

        Args:
            context: Must contain:
                - patterns_extracted: List of extracted patterns
                - Optional: pattern_storage_result: Storage operation result

        Returns:
            ModelQualityGateResult with validation outcome
        """
        issues: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {}

        # Check if patterns are present
        patterns = context.get("patterns_extracted")
        if patterns is None:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="No patterns extracted from execution",
                metadata={"error": "missing_patterns"},
            )

        # Validate patterns is a list
        if not isinstance(patterns, list):
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Patterns must be list, got {type(patterns).__name__}",
                metadata={"error": "invalid_patterns_type"},
            )

        # Must have at least 1 pattern
        if len(patterns) == 0:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message="At least 1 pattern required",
                metadata={"error": "empty_patterns_list"},
            )

        metadata["patterns_count"] = len(patterns)

        # Validate each pattern structure
        valid_patterns = 0
        low_quality_patterns = 0
        invalid_types = set()

        for idx, pattern in enumerate(patterns):
            pattern_issues = self._validate_pattern_structure(pattern, idx)

            if pattern_issues:
                issues.extend(pattern_issues)
            else:
                valid_patterns += 1

                # Check pattern type
                if pattern["pattern_type"] not in self.VALID_PATTERN_TYPES:
                    invalid_types.add(pattern["pattern_type"])
                    warnings.append(
                        f"Pattern {idx}: Unknown type '{pattern['pattern_type']}'"
                    )

                # Check quality score
                confidence = pattern.get("confidence_score", 0.0)
                if confidence < self.MIN_CONFIDENCE_SCORE:
                    low_quality_patterns += 1
                    warnings.append(
                        f"Pattern {idx} '{pattern['pattern_name']}': "
                        f"Low confidence ({confidence:.2f} < {self.MIN_CONFIDENCE_SCORE})"
                    )

        metadata["valid_patterns"] = valid_patterns
        metadata["invalid_patterns"] = len(patterns) - valid_patterns
        metadata["low_quality_patterns"] = low_quality_patterns
        metadata["unknown_pattern_types"] = list(invalid_types)

        # Check pattern storage if provided
        storage_result = context.get("pattern_storage_result")
        if storage_result:
            metadata["storage_attempted"] = True
            metadata["storage_success"] = storage_result.get("success", False)

            if not storage_result.get("success"):
                warnings.append(
                    f"Pattern storage failed: {storage_result.get('error', 'unknown')}"
                )
        else:
            metadata["storage_attempted"] = False
            warnings.append("Pattern storage result not available")

        # Determine validation status
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=(
                    f"Pattern recognition validation failed: "
                    f"{len(issues)} structural issues found"
                ),
                metadata={
                    **metadata,
                    "issues": issues[:10],  # Limit issues in metadata
                    "warnings": warnings,
                },
            )

        # Build success message
        message_parts = [
            f"{valid_patterns} patterns validated",
        ]

        if low_quality_patterns > 0:
            message_parts.append(f"{low_quality_patterns} below quality threshold")

        if warnings:
            message_parts.append(f"({len(warnings)} warnings)")

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message="; ".join(message_parts),
            metadata={
                **metadata,
                "warnings": warnings,
                "validation_complete": True,
            },
        )

    def _validate_pattern_structure(self, pattern: Any, idx: int) -> list[str]:
        """
        Validate individual pattern structure.

        Args:
            pattern: Pattern object to validate
            idx: Pattern index for error messages

        Returns:
            List of validation issues (empty if valid)
        """
        issues: list[str] = []

        # Must be dict
        if not isinstance(pattern, dict):
            issues.append(f"Pattern {idx}: Must be dict, got {type(pattern).__name__}")
            return issues

        # Required fields
        required_fields = [
            "pattern_type",
            "pattern_name",
            "pattern_description",
            "confidence_score",
        ]

        for field in required_fields:
            if field not in pattern:
                issues.append(f"Pattern {idx}: Missing required field '{field}'")

        # Validate confidence_score is float 0.0-1.0
        if "confidence_score" in pattern:
            confidence = pattern["confidence_score"]
            if not isinstance(confidence, (int, float)):
                issues.append(
                    f"Pattern {idx}: confidence_score must be numeric, "
                    f"got {type(confidence).__name__}"
                )
            elif not (0.0 <= confidence <= 1.0):
                issues.append(
                    f"Pattern {idx}: confidence_score must be 0.0-1.0, got {confidence}"
                )

        # Recommended fields (not required but useful)
        recommended_fields = [
            "source_context",
            "reuse_conditions",
            "examples",
        ]

        for field in recommended_fields:
            if field not in pattern:
                # Don't add to issues, just note it's missing
                pass

        # Validate reuse_conditions if present
        if "reuse_conditions" in pattern:
            conditions = pattern["reuse_conditions"]
            if not isinstance(conditions, list):
                issues.append(
                    f"Pattern {idx}: reuse_conditions must be list, "
                    f"got {type(conditions).__name__}"
                )

        # Validate examples if present
        if "examples" in pattern:
            examples = pattern["examples"]
            if not isinstance(examples, list):
                issues.append(
                    f"Pattern {idx}: examples must be list, "
                    f"got {type(examples).__name__}"
                )

        return issues
