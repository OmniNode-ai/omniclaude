#!/usr/bin/env python3
"""
Correction Generator for AI Quality Enforcement System
Generates correction suggestions using RAG intelligence from ONEX Intelligence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

logger = logging.getLogger(__name__)


# Protocol for Intelligence client (external optional dependency)
# Note: The external archon_intelligence package uses `archon_url` parameter name.
# We keep this in the Protocol for compatibility with the external package.
@runtime_checkable
class IntelligenceClientProtocol(Protocol):
    """Protocol for Intelligence service client interface."""

    def __init__(self, archon_url: str | None = None, timeout: float = 5.0) -> None:
        """Initialize the client."""
        ...

    async def gather_domain_standards(
        self, agent_type: str, task_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Gather domain standards from RAG."""
        ...


# Lazy import helper for optional Intelligence client
def _get_intelligence_client_class() -> type[IntelligenceClientProtocol] | None:
    """
    Lazy import of Intelligence client class.

    Returns:
        Intelligence client class if available, None otherwise.
    """
    try:
        from archon_intelligence import ArchonIntelligence

        return cast(type[IntelligenceClientProtocol], ArchonIntelligence)
    except ImportError:
        logger.debug("archon_intelligence not available - using fallback mode")
        return None


# Stub implementation for when Intelligence client is not available
class IntelligenceClientStub:
    """Stub implementation when real Intelligence client is unavailable."""

    def __init__(self, archon_url: str | None = None, timeout: float = 5.0) -> None:
        self.archon_url = archon_url
        self.timeout = timeout
        logger.debug("Using IntelligenceClientStub - RAG intelligence unavailable")

    async def gather_domain_standards(
        self, agent_type: str, task_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Return fallback response when RAG is unavailable."""
        return {"fallback": True, "results": [], "error": "intelligence client not available"}


@dataclass
class Violation:
    """Represents a naming convention violation."""

    type: str  # variable, function, class, constant, interface
    name: str
    line: int
    column: int
    severity: str  # error, warning
    rule: str
    suggestion: str | None = None


class CorrectionGenerator:
    """Generate intelligent corrections for naming violations using RAG intelligence."""

    def __init__(self, intelligence_url: str | None = None, timeout: float = 5.0) -> None:
        """
        Initialize the correction generator.

        Args:
            intelligence_url: ONEX Intelligence server URL (defaults to env or localhost:8051)
            timeout: Request timeout in seconds
        """
        # Try to use real Intelligence client, fall back to stub if unavailable
        intelligence_class = _get_intelligence_client_class()
        if intelligence_class is not None:
            self.intelligence_client: IntelligenceClientProtocol = intelligence_class(
                archon_url=intelligence_url, timeout=timeout
            )
        else:
            self.intelligence_client = IntelligenceClientStub(
                archon_url=intelligence_url, timeout=timeout
            )
        self._cache: dict[str, dict[str, Any]] = {}  # Cache RAG results during session

    async def generate_corrections(
        self, violations: list[Violation], content: str, file_path: str, language: str
    ) -> list[dict[str, Any]]:
        """
        Generate corrections for all violations.

        Args:
            violations: List of violations to correct
            content: Full file content
            file_path: Path to the file being corrected
            language: Programming language (python, typescript, javascript, etc.)

        Returns:
            List of correction dictionaries with structure:
            {
                'violation': Violation object,
                'old_name': str,
                'new_name': str,
                'rag_context': Dict,
                'confidence': float,
                'explanation': str,
                'code_context': str
            }
        """
        corrections = []

        for violation in violations:
            # Extract code context around the violation
            code_context = self._extract_context(content, violation)

            # Get RAG intelligence for this violation type
            rag_result = await self._get_naming_intelligence(
                language=language,
                violation_type=violation.type,
                code_context=code_context,
                violation_name=violation.name,
            )

            # Generate the correction
            correction = {
                "violation": violation,
                "old_name": violation.name,
                "new_name": violation.suggestion or self._infer_correction(violation, rag_result),
                "rag_context": rag_result,
                "confidence": self._calculate_base_confidence(violation, rag_result),
                "explanation": self._generate_explanation(violation, rag_result),
                "code_context": code_context,
                "file_path": file_path,
                "language": language,
            }

            corrections.append(correction)

        return corrections

    def _extract_context(self, content: str, violation: Violation, context_lines: int = 3) -> str:
        """
        Extract surrounding context for the violation.

        Args:
            content: Full file content
            violation: Violation to extract context for
            context_lines: Number of lines before/after to include

        Returns:
            Code context as a string with line numbers
        """
        lines = content.split("\n")
        start = max(0, violation.line - context_lines - 1)  # -1 for 0-indexed
        end = min(len(lines), violation.line + context_lines)

        context_with_numbers = []
        for i in range(start, end):
            line_num = i + 1
            marker = ">>>" if line_num == violation.line else "   "
            context_with_numbers.append(f"{marker} {line_num:4d} | {lines[i]}")

        return "\n".join(context_with_numbers)

    async def _get_naming_intelligence(
        self, language: str, violation_type: str, code_context: str, violation_name: str
    ) -> dict[str, Any]:
        """
        Query RAG for naming conventions and best practices.

        Args:
            language: Programming language
            violation_type: Type of violation (variable, function, class, etc.)
            code_context: Code context around the violation
            violation_name: The violating name

        Returns:
            RAG query result with intelligence about naming conventions
        """
        # Check cache first
        cache_key = f"{language}:{violation_type}:{violation_name}"
        if cache_key in self._cache:
            cached: dict[str, Any] = self._cache[cache_key]
            return cached

        # Build intelligent query for RAG

        # Execute RAG query with domain standards context
        task_context = {
            "domain": f"{language}_naming_conventions",
            "violation_type": violation_type,
            "code_context": code_context,
        }

        try:
            result: dict[str, Any] = await self.intelligence_client.gather_domain_standards(
                agent_type="naming_correction", task_context=task_context
            )

            # Cache the result
            self._cache[cache_key] = result
            return result

        except Exception as e:
            # Return fallback with error info
            return {"error": str(e), "fallback": True, "results": []}

    def _infer_correction(self, violation: Violation, rag_result: dict[str, Any]) -> str:
        """
        Infer correction from RAG results or validator suggestion.

        Args:
            violation: The violation to correct
            rag_result: RAG query results

        Returns:
            Corrected name suggestion
        """
        # First priority: Use validator suggestion if available
        if violation.suggestion:
            return violation.suggestion

        # Second priority: Try to extract from RAG results
        if not rag_result.get("fallback", False):
            results = rag_result.get("results", [])
            if results:
                # Look for examples in the first result
                content = results[0].get("content", {})
                examples = content.get("examples", [])
                if examples and isinstance(examples, list) and len(examples) > 0:
                    # Use first example as template
                    return str(examples[0])

        # Fallback: Apply basic transformation based on violation type
        return self._apply_basic_transformation(violation)

    def _apply_basic_transformation(self, violation: Violation) -> str:
        """
        Apply basic naming transformation when no better suggestion is available.

        Args:
            violation: The violation to transform

        Returns:
            Transformed name
        """
        name = violation.name

        transformations: dict[str, Any] = {
            "function": self._to_snake_case,
            "variable": self._to_snake_case,
            "class": self._to_pascal_case,
            "constant": self._to_upper_snake_case,
            "interface": lambda n: f"I{CorrectionGenerator._to_pascal_case(n.lstrip('I'))}",
        }

        transform_func = transformations.get(violation.type, lambda x: x)
        result: str = transform_func(name)
        return result

    def _generate_explanation(self, violation: Violation, rag_result: dict[str, Any]) -> str:
        """
        Generate human-readable explanation for the correction.

        Args:
            violation: The violation being corrected
            rag_result: RAG query results

        Returns:
            Explanation string
        """
        # Try to get explanation from RAG results
        if not rag_result.get("fallback", False):
            results = rag_result.get("results", [])
            if results:
                content = results[0].get("content", {})
                description = content.get("description", "")
                if description:
                    return str(description)

        # Fallback to violation rule
        explanation = violation.rule

        # Enhance with basic guidance
        enhancement_map = {
            "function": "Functions should use snake_case to improve readability and follow language conventions.",
            "variable": "Variables should use snake_case for consistency with language standards.",
            "class": "Classes should use PascalCase to distinguish them from functions and variables.",
            "constant": "Constants should use UPPER_SNAKE_CASE to indicate immutability.",
            "interface": 'Interfaces should start with "I" and use PascalCase for clear type distinction.',
        }

        enhancement = enhancement_map.get(violation.type, "")
        if enhancement:
            explanation += f" {enhancement}"

        return explanation

    def _calculate_base_confidence(self, violation: Violation, rag_result: dict[str, Any]) -> float:
        """
        Calculate base confidence score for the correction.

        This will be enhanced by AI scoring in Phase 4.

        Args:
            violation: The violation being corrected
            rag_result: RAG query results

        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 0.5  # Base confidence

        # Increase confidence if validator provided a suggestion
        if violation.suggestion:
            confidence += 0.2

        # Increase confidence if RAG returned results
        if not rag_result.get("fallback", False):
            results = rag_result.get("results", [])
            if results:
                # More results = higher confidence
                confidence += min(len(results) * 0.1, 0.3)

        # Cap at 1.0
        return min(confidence, 1.0)

    # Naming transformation utilities
    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert name to snake_case."""
        # Insert underscores before uppercase letters
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        return s2.lower()

    @staticmethod
    def _to_camel_case(name: str) -> str:
        """Convert name to camelCase."""
        components = re.split(r"[_\-]", name)
        return components[0].lower() + "".join(x.title() for x in components[1:])

    @staticmethod
    def _to_pascal_case(name: str) -> str:
        """Convert name to PascalCase."""
        components = re.split(r"[_\-]", name)
        return "".join(x.title() for x in components)

    @staticmethod
    def _to_upper_snake_case(name: str) -> str:
        """Convert name to UPPER_SNAKE_CASE."""
        return CorrectionGenerator._to_snake_case(name).upper()

    async def close(self) -> None:
        """
        Cleanup resources.

        Note: Intelligence client uses httpx.AsyncClient internally.
        In Phase 2, we'll add proper cleanup for the RAG client.
        """
        # Currently, Intelligence client creates clients per-request
        # No cleanup needed in Phase 1
        pass


# Example usage and testing
async def main() -> None:
    """Example usage of the CorrectionGenerator."""

    # Example violations
    violations = [
        Violation(
            type="function",
            name="MyFunction",
            line=10,
            column=5,
            severity="error",
            rule="Python: function names should be snake_case",
            suggestion="my_function",
        ),
        Violation(
            type="class",
            name="my_class",
            line=20,
            column=7,
            severity="error",
            rule="Python: class names should be PascalCase",
            suggestion="MyClass",
        ),
    ]

    # Example content
    content = """
import os

def someHelper():
    pass

class my_class:
    def MyFunction(self):
        pass

SOME_CONSTANT = 42
"""

    # Create generator
    generator = CorrectionGenerator()

    # Generate corrections
    corrections = await generator.generate_corrections(
        violations=violations,
        content=content,
        file_path="example.py",
        language="python",
    )

    # Display results
    print(f"\nGenerated {len(corrections)} corrections:\n")
    for i, correction in enumerate(corrections, 1):
        print(f"Correction {i}:")
        print(f"  Old name: {correction['old_name']}")
        print(f"  New name: {correction['new_name']}")
        print(f"  Confidence: {correction['confidence']:.2f}")
        print(f"  Explanation: {correction['explanation']}")
        print("\n  Code context:")
        for line in correction["code_context"].split("\n"):
            print(f"    {line}")
        print()

    # Cleanup
    await generator.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
