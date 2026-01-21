#!/usr/bin/env python3
"""
Pattern Extractor - Extract reusable patterns from generated code.

Part of KV-002 (Pattern Recognition) quality gate integration.
Analyzes code to identify reusable patterns for future generation.

Pattern Types Extracted:
1. Workflow Patterns: Stage sequences, orchestration flows
2. Code Patterns: Common implementations, reusable functions
3. Naming Patterns: ONEX conventions, naming rules
4. Architecture Patterns: Design patterns (Factory, Strategy, etc.)
5. Error Handling Patterns: Try-catch structures, error propagation
6. Testing Patterns: Test structure, mocking, fixtures

ONEX v2.0 Compliance:
- AST-based code analysis
- Type-safe pattern extraction
- Performance tracking (<300ms target)
"""

import ast
import re
from datetime import UTC, datetime
from typing import Any

from ..models.model_code_pattern import (
    EnumPatternType,
    ModelCodePattern,
    ModelPatternExtractionResult,
)


class PatternExtractor:
    """
    Extract reusable patterns from generated code.

    Uses AST parsing, regex analysis, and heuristics to identify
    patterns worth storing for future reuse.

    Example:
        extractor = PatternExtractor()
        result = extractor.extract_patterns(
            generated_code="class NodeMyEffect...",
            context={"node_type": "effect", "framework": "onex"}
        )
        for pattern in result.patterns:
            print(f"Found {pattern.pattern_type}: {pattern.pattern_name}")
    """

    def __init__(self, min_confidence: float = 0.5) -> None:
        """
        Initialize pattern extractor.

        Args:
            min_confidence: Minimum confidence score for pattern extraction (0.0-1.0)
        """
        self.min_confidence = min_confidence

    def extract_patterns(
        self, generated_code: str, context: dict[str, Any]
    ) -> ModelPatternExtractionResult:
        """
        Extract all patterns from generated code.

        Analyzes code using multiple strategies:
        - AST parsing for structural patterns
        - Regex for naming patterns
        - Heuristics for workflow patterns

        Args:
            generated_code: The generated code to analyze
            context: Generation context (node_type, framework, etc.)

        Returns:
            ModelPatternExtractionResult with all extracted patterns
        """
        start_time = datetime.now(UTC)
        patterns: list[ModelCodePattern] = []

        # Extract each pattern type
        try:
            # 1. Workflow patterns (stage sequences, orchestration)
            workflow_patterns = self._extract_workflow_patterns(generated_code, context)
            patterns.extend(workflow_patterns)

            # 2. Code patterns (common implementations)
            code_patterns = self._extract_code_patterns(generated_code, context)
            patterns.extend(code_patterns)

            # 3. Naming patterns (ONEX conventions)
            naming_patterns = self._extract_naming_patterns(generated_code, context)
            patterns.extend(naming_patterns)

            # 4. Architecture patterns (design patterns)
            arch_patterns = self._extract_architecture_patterns(generated_code, context)
            patterns.extend(arch_patterns)

            # 5. Error handling patterns
            error_patterns = self._extract_error_handling_patterns(
                generated_code, context
            )
            patterns.extend(error_patterns)

            # 6. Testing patterns
            testing_patterns = self._extract_testing_patterns(generated_code, context)
            patterns.extend(testing_patterns)

        except Exception as e:
            # Extraction errors should not fail the entire process
            print(f"Warning: Pattern extraction error: {e}")

        # Filter by minimum confidence
        patterns = [p for p in patterns if p.confidence_score >= self.min_confidence]

        end_time = datetime.now(UTC)
        extraction_time_ms = int((end_time - start_time).total_seconds() * 1000)

        return ModelPatternExtractionResult(  # type: ignore[call-arg]
            patterns=patterns,
            extraction_time_ms=extraction_time_ms,
            source_context=context,
            extraction_method="ast_regex_heuristic",
            metadata={
                "code_length": len(generated_code),
                "min_confidence": self.min_confidence,
            },
        )

    def _extract_workflow_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract workflow execution patterns.

        Identifies:
        - Stage sequences (6-stage ONEX generation)
        - Orchestration patterns (parallel coordination)
        - Delegation patterns (agent handoffs)

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of workflow patterns
        """
        patterns: list[ModelCodePattern] = []

        # Look for stage-based workflow (e.g., 6-stage ONEX generation)
        stage_pattern = re.findall(
            r"(async\s+def\s+execute_stage_\w+|def\s+_stage_\w+)", code
        )
        if len(stage_pattern) >= 3:  # At least 3 stages
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.WORKFLOW,
                    pattern_name="Multi-stage workflow execution",
                    pattern_description=f"Workflow with {len(stage_pattern)} sequential stages",
                    confidence_score=min(0.8 + len(stage_pattern) * 0.02, 0.95),
                    pattern_template=self._extract_stage_template(code, stage_pattern),
                    example_usage=[code[:500]],  # First 500 chars as example
                    source_context=context,
                    reuse_conditions=[
                        "multi-stage workflow needed",
                        "sequential stage execution",
                    ],
                )
            )

        # Look for orchestration patterns (parallel coordination)
        orchestration_keywords = ["asyncio.gather", "await.*await", "parallel"]
        if any(re.search(kw, code) for kw in orchestration_keywords):
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.WORKFLOW,
                    pattern_name="Parallel orchestration pattern",
                    pattern_description="Orchestrates multiple parallel async tasks",
                    confidence_score=0.75,
                    pattern_template=self._extract_orchestration_template(code),
                    example_usage=[code[:500]],
                    source_context=context,
                    reuse_conditions=[
                        "parallel execution needed",
                        "task orchestration",
                    ],
                )
            )

        return patterns

    def _extract_code_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract code implementation patterns.

        Uses AST parsing to identify:
        - Reusable functions
        - Design patterns (Factory, Strategy, etc.)
        - Common class structures

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of code patterns
        """
        patterns: list[ModelCodePattern] = []

        try:
            tree = ast.parse(code)

            # Extract class patterns
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check for ONEX node pattern (NodeXxxEffect, etc.)
                    if node.name.startswith("Node") and any(
                        node.name.endswith(suffix)
                        for suffix in ["Effect", "Compute", "Reducer", "Orchestrator"]
                    ):
                        patterns.append(
                            ModelCodePattern(  # type: ignore[call-arg]
                                pattern_type=EnumPatternType.CODE,
                                pattern_name=f"ONEX {node.name} class pattern",
                                pattern_description=f"ONEX node class: {node.name}",
                                confidence_score=0.9,
                                pattern_template=ast.unparse(node),
                                example_usage=[ast.unparse(node)[:300]],
                                source_context=context,
                                reuse_conditions=[
                                    "ONEX node generation",
                                    f"node_type: {node.name.split('Node')[1]}",
                                ],
                            )
                        )

                # Extract decorator patterns
                if isinstance(node, ast.FunctionDef) and node.decorator_list:
                    decorator_names = [
                        d.id if isinstance(d, ast.Name) else ast.unparse(d)
                        for d in node.decorator_list
                    ]
                    if decorator_names:
                        patterns.append(
                            ModelCodePattern(  # type: ignore[call-arg]
                                pattern_type=EnumPatternType.CODE,
                                pattern_name=f"Function with decorators: {', '.join(decorator_names)}",
                                pattern_description=f"Function decorated with {decorator_names}",
                                confidence_score=0.7,
                                pattern_template=ast.unparse(node),
                                example_usage=[ast.unparse(node)[:300]],
                                source_context=context,
                                reuse_conditions=[
                                    f"decorator: {dec}" for dec in decorator_names
                                ],
                            )
                        )

        except SyntaxError:
            # Not valid Python, skip AST parsing
            pass

        return patterns

    def _extract_naming_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract naming convention patterns.

        Identifies:
        - Class naming (NodeXxxEffect, ModelXxx, EnumXxx)
        - Method naming (execute_xxx, validate_xxx, etc.)
        - Variable naming conventions

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of naming patterns
        """
        patterns: list[ModelCodePattern] = []

        # ONEX class naming patterns
        class_patterns = {
            "Node classes": r"class\s+Node\w+(Effect|Compute|Reducer|Orchestrator)",
            "Model classes": r"class\s+Model[A-Z]\w+",
            "Enum classes": r"class\s+Enum[A-Z]\w+",
        }

        for name, pattern in class_patterns.items():
            matches = re.findall(pattern, code)
            if matches:
                patterns.append(
                    ModelCodePattern(  # type: ignore[call-arg]
                        pattern_type=EnumPatternType.NAMING,
                        pattern_name=f"ONEX {name} naming convention",
                        pattern_description=f"ONEX naming pattern for {name}",
                        confidence_score=0.85,
                        pattern_template=pattern,
                        example_usage=matches[:3],  # First 3 examples
                        source_context=context,
                        reuse_conditions=["ONEX compliance", "naming conventions"],
                    )
                )

        # Method naming patterns
        method_patterns = {
            "execute methods": r"async\s+def\s+execute_\w+",
            "validate methods": r"async\s+def\s+validate_\w+",
            "private methods": r"def\s+_\w+",
        }

        for name, pattern in method_patterns.items():
            matches = re.findall(pattern, code)
            if len(matches) >= 2:  # At least 2 instances
                patterns.append(
                    ModelCodePattern(  # type: ignore[call-arg]
                        pattern_type=EnumPatternType.NAMING,
                        pattern_name=f"{name.capitalize()} naming pattern",
                        pattern_description=f"Consistent naming for {name}",
                        confidence_score=0.75,
                        pattern_template=pattern,
                        example_usage=matches[:3],
                        source_context=context,
                        reuse_conditions=["method naming", "ONEX compliance"],
                    )
                )

        return patterns

    def _extract_architecture_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract architectural design patterns.

        Identifies:
        - Dependency injection
        - Factory pattern
        - Strategy pattern
        - Observer pattern

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of architecture patterns
        """
        patterns: list[ModelCodePattern] = []

        # Dependency injection pattern
        if re.search(r"def\s+__init__\s*\(self,.*:\s*\w+", code):
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.ARCHITECTURE,
                    pattern_name="Dependency injection pattern",
                    pattern_description="Constructor with typed dependencies",
                    confidence_score=0.8,
                    pattern_template="def __init__(self, dep: Type): ...",
                    example_usage=[code[:300]],
                    source_context=context,
                    reuse_conditions=["dependency injection", "SOLID principles"],
                )
            )

        # Factory pattern
        if re.search(r"@(classmethod|staticmethod).*\s+def\s+create", code):
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.ARCHITECTURE,
                    pattern_name="Factory method pattern",
                    pattern_description="Class/static method for object creation",
                    confidence_score=0.85,
                    pattern_template="@classmethod\ndef create(...): ...",
                    example_usage=[code[:300]],
                    source_context=context,
                    reuse_conditions=["object creation", "factory pattern"],
                )
            )

        return patterns

    def _extract_error_handling_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract error handling patterns.

        Identifies:
        - Try-catch structures
        - Error propagation
        - OnexError usage

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of error handling patterns
        """
        patterns: list[ModelCodePattern] = []

        # Try-except with specific exception types
        try_except_matches = re.findall(r"try:.*?except\s+(\w+Error)", code, re.DOTALL)
        if try_except_matches:
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.ERROR_HANDLING,
                    pattern_name="Typed exception handling",
                    pattern_description=f"Try-except with specific error types: {set(try_except_matches)}",
                    confidence_score=0.8,
                    pattern_template="try:\n    ...\nexcept SpecificError as e:\n    ...",
                    example_usage=[code[:400]],
                    source_context=context,
                    reuse_conditions=["error handling", "exception management"],
                )
            )

        return patterns

    def _extract_testing_patterns(
        self, code: str, context: dict[str, Any]
    ) -> list[ModelCodePattern]:
        """
        Extract testing patterns.

        Identifies:
        - Test structure (pytest, unittest)
        - Mocking patterns
        - Fixture usage

        Args:
            code: Generated code
            context: Generation context

        Returns:
            List of testing patterns
        """
        patterns: list[ModelCodePattern] = []

        # Pytest patterns
        if re.search(r"@pytest\.(fixture|mark)", code):
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.TESTING,
                    pattern_name="Pytest fixture/marker pattern",
                    pattern_description="Pytest decorators for test organization",
                    confidence_score=0.85,
                    pattern_template="@pytest.fixture\ndef fixture_name(): ...",
                    example_usage=[code[:300]],
                    source_context=context,
                    reuse_conditions=["pytest", "test fixtures"],
                )
            )

        # Async test patterns
        if re.search(r"async\s+def\s+test_", code):
            patterns.append(
                ModelCodePattern(  # type: ignore[call-arg]
                    pattern_type=EnumPatternType.TESTING,
                    pattern_name="Async test pattern",
                    pattern_description="Async test function pattern",
                    confidence_score=0.8,
                    pattern_template="async def test_xxx(): ...",
                    example_usage=[code[:300]],
                    source_context=context,
                    reuse_conditions=["async testing", "pytest-asyncio"],
                )
            )

        return patterns

    def _extract_stage_template(self, code: str, stage_matches: list[str]) -> str:
        """Extract template for multi-stage workflow."""
        # Simplified template extraction
        return (
            "{% for stage in stages %}async def execute_{{ stage }}(): ...{% endfor %}"
        )

    def _extract_orchestration_template(self, code: str) -> str:
        """Extract template for orchestration pattern."""
        return "results = await asyncio.gather(*[task1(), task2(), ...])"

    def _calculate_pattern_confidence(self, pattern: dict[str, Any]) -> float:
        """
        Calculate confidence score for pattern quality.

        Factors:
        - Frequency in successful generations
        - Pattern complexity
        - Reuse potential

        Args:
            pattern: Pattern metadata

        Returns:
            Confidence score (0.0-1.0)
        """
        base_score = 0.5

        # Adjust based on pattern type (some are more reliable)
        type_weights = {
            "workflow": 0.9,
            "architecture": 0.85,
            "naming": 0.8,
            "code": 0.75,
            "error_handling": 0.7,
            "testing": 0.7,
        }
        base_score = type_weights.get(pattern.get("type", ""), 0.5)

        # Adjust based on context richness
        if pattern.get("source_context"):
            base_score += 0.05

        # Adjust based on reuse conditions
        if pattern.get("reuse_conditions"):
            base_score += 0.05

        return min(base_score, 1.0)
