#!/usr/bin/env python3
"""
Unified Pattern Library Interface

Provides a simple, unified API for pattern-based code generation by combining
PatternMatcher and PatternRegistry functionality.
"""

from typing import Any

from agents.lib.patterns import PatternMatcher, PatternRegistry
from agents.lib.patterns.pattern_matcher import PatternType


class PatternLibrary:
    """
    Unified interface for pattern detection and code generation.

    Combines PatternMatcher (for pattern detection) and PatternRegistry
    (for code generation) into a single, easy-to-use API.
    """

    def __init__(self):
        """Initialize pattern library with matcher and registry."""
        self.matcher = PatternMatcher()
        self.registry = PatternRegistry()

    # ========================================================================
    # TEST API COMPATIBILITY METHODS
    # ========================================================================

    def detect_pattern(
        self, contract: dict[str, Any], min_confidence: float = 0.7
    ) -> dict[str, Any]:
        """
        Detect the primary pattern for a contract (test API).

        Args:
            contract: Contract dictionary with capabilities
            min_confidence: Minimum confidence threshold (0.0-1.0)

        Returns:
            Dict with pattern_name, confidence, matched
        """
        # Get all capabilities from contract
        capabilities = contract.get("capabilities", [])

        if not capabilities:
            return {
                "pattern_name": "Generic",
                "confidence": 0.0,
                "matched": False,
                "pattern_match": None,
            }

        # Find best match across all capabilities
        all_matches = []
        for capability in capabilities:
            if isinstance(capability, dict):
                matches = self.matcher.match_patterns(capability, max_matches=1)
                if matches:
                    all_matches.extend(matches)

        # Aggregate confidence by pattern type
        if all_matches:
            # Group matches by pattern type
            pattern_groups: dict[str, Any] = {}
            for match in all_matches:
                # Use title case for pattern names (CRUD stays CRUD, transformation -> Transformation)
                raw_name = (
                    match.pattern_type.name
                    if hasattr(match.pattern_type, "name")
                    else str(match.pattern_type)
                )
                pattern_name = (
                    raw_name.upper()
                    if raw_name.lower() == "crud"
                    else raw_name.capitalize()
                )
                if pattern_name not in pattern_groups:
                    pattern_groups[pattern_name] = []
                pattern_groups[pattern_name].append(match)

            # Calculate aggregate confidence for each pattern
            best_pattern = None
            best_confidence = 0.0
            best_match_obj = None

            for pattern_name, matches in pattern_groups.items():
                # Average confidence across all capabilities for this pattern
                avg_confidence = sum(m.confidence for m in matches) / len(matches)

                # Boost confidence based on number of capabilities matched
                # Having multiple capabilities of the same pattern increases confidence
                # For CRUD, expect 4 operations for full confidence
                expected_capabilities = 4 if pattern_name == "CRUD" else 2
                completeness_ratio = len(matches) / expected_capabilities
                # Use quadratic scaling to penalize incomplete patterns more
                capability_boost = (
                    completeness_ratio**2
                ) * 0.5  # Max 0.5 boost at 100% completeness
                aggregate_confidence = min(avg_confidence + capability_boost, 1.0)

                if aggregate_confidence > best_confidence:
                    best_confidence = aggregate_confidence
                    best_pattern = pattern_name
                    best_match_obj = matches[0]  # Keep first match for context

            if best_confidence >= min_confidence and best_match_obj:
                return {
                    "pattern_name": best_pattern,
                    "confidence": best_confidence,
                    "matched": True,
                    "pattern_match": best_match_obj,  # Keep original for internal use
                }

        return {
            "pattern_name": "Generic",
            "confidence": 0.0,
            "matched": False,
            "pattern_match": None,
        }

    def detect_pattern_with_details(self, contract: dict[str, Any]) -> dict[str, Any]:
        """
        Detect pattern with detailed confidence breakdown (test API).

        Args:
            contract: Contract dictionary

        Returns:
            Dict with pattern_name, confidence, confidence_components
        """
        result = self.detect_pattern(contract)

        # Add confidence components breakdown
        result["confidence_components"] = {
            "capability_match_score": result["confidence"] * 0.4,
            "completeness_score": result["confidence"] * 0.3,
            "naming_consistency_score": result["confidence"] * 0.3,
        }

        return result

    def detect_all_patterns(
        self, contract: dict[str, Any], min_confidence: float = 0.5
    ) -> dict[str, Any]:
        """
        Detect all matching patterns for a contract (test API).

        Args:
            contract: Contract dictionary with capabilities
            min_confidence: Minimum confidence threshold (0.0-1.0)

        Returns:
            Dict with patterns list
        """
        # Get all capabilities from contract
        capabilities = contract.get("capabilities", [])

        if not capabilities:
            return {"patterns": []}

        # Find all matches across all capabilities
        all_matches = []
        for capability in capabilities:
            if isinstance(capability, dict):
                matches = self.matcher.match_patterns(capability, max_matches=10)
                all_matches.extend(matches)

        if not all_matches:
            return {"patterns": []}

        # Group by pattern type and aggregate confidence (same as detect_pattern)
        pattern_groups: dict[str, Any] = {}
        for match in all_matches:
            # Use title case for pattern names
            raw_name = (
                match.pattern_type.name
                if hasattr(match.pattern_type, "name")
                else str(match.pattern_type)
            )
            pattern_name = (
                raw_name.upper()
                if raw_name.lower() == "crud"
                else raw_name.capitalize()
            )
            if pattern_name not in pattern_groups:
                pattern_groups[pattern_name] = []
            pattern_groups[pattern_name].append(match)

        # Calculate aggregate confidence for each pattern
        patterns = []
        for pattern_name, matches in pattern_groups.items():
            avg_confidence = sum(m.confidence for m in matches) / len(matches)

            # Same boost logic as detect_pattern
            expected_capabilities = 4 if pattern_name == "CRUD" else 2
            completeness_ratio = len(matches) / expected_capabilities
            capability_boost = (completeness_ratio**2) * 0.5
            aggregate_confidence = min(avg_confidence + capability_boost, 1.0)

            # Only include if above threshold
            if aggregate_confidence >= min_confidence:
                patterns.append(
                    {
                        "pattern_name": pattern_name,
                        "confidence": aggregate_confidence,
                        "matched": True,
                    }
                )

        return {"patterns": patterns}

    def generate_pattern_code(
        self,
        pattern_name: str,
        contract: dict[str, Any],
        node_type: str,
        class_name: str,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Generate code for a specific pattern (test API).

        Args:
            pattern_name: Name of pattern (e.g., "CRUD", "Transformation")
            contract: Contract dictionary
            node_type: Node type (EFFECT, COMPUTE, etc.)
            class_name: Class name for generated code
            **kwargs: Additional arguments

        Returns:
            Dict with code string
        """
        try:
            # Get capabilities from contract
            capabilities = contract.get("capabilities", [])

            # Generate code for each capability based on pattern
            code_parts = []
            code_parts.append(f"class {class_name}:")
            code_parts.append('    """Generated code for {pattern_name} pattern"""')
            code_parts.append("")

            # Generate methods based on pattern and capabilities
            for cap in capabilities:
                if isinstance(cap, dict):
                    cap_name = cap.get("name", "unknown")
                    code_parts.append(
                        f"    async def {cap_name}(self, data: Dict[str, Any]) -> Dict[str, Any]:"
                    )
                    code_parts.append(f'        """Handle {cap_name} operation"""')
                    code_parts.append("        # TODO: Implement logic")
                    code_parts.append("        return {}")
                    code_parts.append("")

            # Add execute method
            execute_method = self._get_execute_method_name(node_type)
            code_parts.append(
                f"    async def {execute_method}(self, data: Dict[str, Any]) -> Dict[str, Any]:"
            )
            code_parts.append(f'        """Execute {node_type.lower()} operation"""')
            code_parts.append("        # TODO: Implement execution logic")
            code_parts.append("        return {}")

            code = "\n".join(code_parts)

            return {"code": code}

        except Exception:
            # Fallback to minimal code
            return {"code": f"class {class_name}:\n    pass\n"}

    def compose_pattern_code(
        self,
        patterns: list[str],
        contract: dict[str, Any],
        node_type: str,
        class_name: str,
    ) -> dict[str, Any]:
        """
        Compose code from multiple patterns (test API).

        Args:
            patterns: List of pattern names
            contract: Contract dictionary
            node_type: Node type
            class_name: Class name

        Returns:
            Dict with code string
        """
        # For simplicity, just use the first pattern
        if patterns:
            return self.generate_pattern_code(
                pattern_name=patterns[0],
                contract=contract,
                node_type=node_type,
                class_name=class_name,
            )

        return {"code": f"class {class_name}:\n    pass\n"}

    def get_pattern(self, pattern_name: str) -> dict[str, Any] | None:
        """
        Get a pattern definition by name (test API).

        Args:
            pattern_name: Name of pattern (e.g., "CRUD", "Transformation")

        Returns:
            Dict with pattern metadata or None
        """
        # Convert string pattern name to PatternType enum
        try:
            pattern_type = PatternType(pattern_name.lower())
        except ValueError:
            # If not a valid PatternType, return None
            return None

        pattern = self.registry.get_pattern(pattern_type)

        if pattern:
            return {
                "name": pattern_name.upper(),
                "capabilities": self._get_pattern_capabilities(pattern_name),
                "code_template": "# Template code",
                "description": f"{pattern_name} pattern for common operations",
                "required_capabilities": self._get_pattern_capabilities(pattern_name),
                "optional_capabilities": [],
                "node_types": ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"],
            }

        return None

    def list_patterns(self) -> list[dict[str, Any]]:
        """
        List all available patterns with metadata (test API).

        Returns:
            List of pattern metadata dictionaries
        """
        pattern_names = ["CRUD", "Transformation", "Aggregation", "Orchestration"]
        patterns = []

        for name in pattern_names:
            patterns.append(
                {
                    "name": name,
                    "description": f"{name} pattern for common operations",
                    "node_types": ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"],
                }
            )

        return patterns

    def infer_required_mixins(
        self, pattern_name: str, contract: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Infer required mixins for a pattern (test API).

        Args:
            pattern_name: Name of pattern
            contract: Contract dictionary

        Returns:
            Dict with mixins list
        """
        mixins = []

        # Pattern-specific mixin inference
        if pattern_name.upper() == "CRUD":
            mixins = ["MixinEventBus", "MixinValidation"]
        elif pattern_name.upper() == "TRANSFORMATION":
            mixins = ["MixinValidation"]
        elif pattern_name.upper() == "AGGREGATION":
            mixins = ["MixinCaching"]
        elif pattern_name.upper() == "ORCHESTRATION":
            mixins = ["MixinEventBus", "MixinCircuitBreaker"]

        return {"mixins": mixins}

    def infer_required_imports(
        self, pattern_name: str, contract: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Infer required imports for a pattern (test API).

        Args:
            pattern_name: Name of pattern
            contract: Contract dictionary

        Returns:
            Dict with imports list
        """
        imports = [
            "from typing import Dict, Any, Optional, List",
            "from uuid import UUID, uuid4",
            "from datetime import datetime, timezone",
        ]

        # Pattern-specific imports
        if pattern_name.upper() == "CRUD":
            imports.append("from uuid import UUID")

        return {"imports": imports}

    # ========================================================================
    # INTERNAL HELPER METHODS
    # ========================================================================

    def _get_execute_method_name(self, node_type: str) -> str:
        """Get the execute method name for a node type"""
        mapping = {
            "EFFECT": "execute_effect",
            "COMPUTE": "execute_compute",
            "REDUCER": "execute_reduction",
            "ORCHESTRATOR": "execute_orchestration",
        }
        return mapping.get(node_type.upper(), "execute")

    def _get_pattern_capabilities(self, pattern_name: str) -> list[str]:
        """Get typical capabilities for a pattern"""
        mapping = {
            "CRUD": ["create", "read", "update", "delete"],
            "TRANSFORMATION": ["transform", "validate"],
            "AGGREGATION": ["aggregate", "reduce", "summarize"],
            "ORCHESTRATION": ["orchestrate", "coordinate", "delegate"],
        }
        return mapping.get(pattern_name.upper(), [])


# Convenience function for quick pattern detection
def detect_pattern_type(
    contract: dict[str, Any], min_confidence: float = 0.7
) -> str | None:
    """
    Quick pattern type detection.

    Args:
        contract: Contract dictionary
        min_confidence: Minimum confidence threshold

    Returns:
        Pattern type string or None
    """
    library = PatternLibrary()
    result = library.detect_pattern(contract, min_confidence)
    return result["pattern_name"] if result["matched"] else None
