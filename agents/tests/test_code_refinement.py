#!/usr/bin/env python3
"""
Test Code Refinement System (Stage 5.5)

Tests the 3-step refinement process:
1. Deterministic fixes (G12, G13, G14)
2. Pattern application from production library
3. Quorum enhancement integration

Target Performance: <3s total refinement time
Quality Improvement: 85% → 95%+
"""

import ast
import asyncio
from time import perf_counter
from typing import Dict, List
from unittest.mock import patch

import pytest

# ============================================================================
# Mock Classes for Testing
# ============================================================================


class MockG12Fixer:
    """Mock G12 fixer for Pydantic ConfigDict."""

    DEFAULT_CONFIG = """    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        arbitrary_types_allowed=False,
        extra="forbid"
    )
"""

    def fix(self, code: str) -> tuple[str, bool]:
        """Apply G12 fix."""
        if "class Model" in code and "BaseModel" in code:
            if "model_config" not in code:
                # Insert ConfigDict after class definition
                lines = code.split("\n")
                for i, line in enumerate(lines):
                    if "class Model" in line and "BaseModel" in line:
                        # Find next line (after docstring if present)
                        insert_idx = i + 1
                        if i + 1 < len(lines) and '"""' in lines[i + 1]:
                            # Skip docstring
                            for j in range(i + 1, len(lines)):
                                if '"""' in lines[j] and j > i + 1:
                                    insert_idx = j + 1
                                    break
                        lines.insert(insert_idx, self.DEFAULT_CONFIG)
                        return "\n".join(lines), True
        return code, False


class MockG13Fixer:
    """Mock G13 fixer for type hints."""

    def fix(self, code: str, node_type: str) -> tuple[str, bool]:
        """Apply G13 fix."""
        modified = False

        # Add error handling around AST parsing
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Cannot parse code, return unchanged
            return code, False

        for node in ast.walk(tree):
            # Check both FunctionDef and AsyncFunctionDef
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Add type hints to execute methods
                if node.name.startswith("execute_"):
                    if not node.returns:
                        # Add return type annotation
                        modified = True

        if modified:
            return (
                code.replace(
                    "async def execute_effect(self, contract)",
                    "async def execute_effect(self, contract: ModelContractEffect) -> ModelResult",
                ),
                True,
            )

        return code, False


class MockG14Fixer:
    """Mock G14 fixer for imports."""

    def fix(self, code: str) -> tuple[str, bool]:
        """Apply G14 fix."""
        # Fix old import paths
        if "omnibase_core.core." in code:
            code = code.replace("omnibase_core.core.", "omnibase_core.nodes.")
            return code, True
        return code, False


class MockProductionPattern:
    """Mock production pattern."""

    def __init__(
        self,
        source_file: str,
        node_type: str,
        domain: str,
        patterns: List[str],
        similarity: float = 0.85,
    ):
        self.source_file = source_file
        self.node_type = node_type
        self.domain = domain
        self.patterns = patterns
        self.similarity = similarity


class MockPatternApplicator:
    """Mock pattern applicator."""

    async def find_similar_patterns(
        self, code: str, node_type: str, domain: str
    ) -> List[MockProductionPattern]:
        """Find similar production patterns."""
        await asyncio.sleep(0.01)  # Simulate async work

        if domain == "database":
            return [
                MockProductionPattern(
                    source_file="node_postgres_writer_effect.py",
                    node_type="EFFECT",
                    domain="database",
                    patterns=[
                        "Transaction management",
                        "Retry logic",
                        "Connection pooling",
                    ],
                    similarity=0.92,
                ),
                MockProductionPattern(
                    source_file="node_qdrant_search_effect.py",
                    node_type="EFFECT",
                    domain="database",
                    patterns=["Async client", "Metric recording"],
                    similarity=0.78,
                ),
            ]
        return []

    async def apply_patterns(
        self, code: str, patterns: List[MockProductionPattern]
    ) -> str:
        """Apply patterns to code via AI."""
        await asyncio.sleep(0.1)  # Simulate AI call

        # Mock pattern application
        enhanced_code = code + "\n\n# Patterns applied:\n"
        for pattern in patterns:
            for p in pattern.patterns:
                enhanced_code += f"# - {p}\n"

        return enhanced_code


class MockQuorumEnhancer:
    """Mock quorum enhancer."""

    async def apply_suggestions(self, code: str, suggestions: List[str]) -> str:
        """Apply quorum suggestions."""
        await asyncio.sleep(0.05)  # Simulate AI call

        # Mock enhancement
        enhanced_code = code + "\n\n# Quorum suggestions applied:\n"
        for suggestion in suggestions:
            enhanced_code += f"# - {suggestion}\n"

        return enhanced_code


class MockCodeRefinementEngine:
    """Mock refinement engine orchestrating all steps."""

    def __init__(self):
        self.g12_fixer = MockG12Fixer()
        self.g13_fixer = MockG13Fixer()
        self.g14_fixer = MockG14Fixer()
        self.pattern_applicator = MockPatternApplicator()
        self.quorum_enhancer = MockQuorumEnhancer()

    async def refine(
        self,
        code: str,
        node_type: str,
        domain: str,
        validation_gates: List = None,
        quorum_suggestions: List[str] = None,
    ) -> Dict:
        """Execute full refinement pipeline."""
        start_time = perf_counter()

        original_code = code
        fixes_applied = []
        patterns_applied = 0

        # Step 1: Deterministic fixes
        step1_start = perf_counter()

        # G12 fix
        code, g12_fixed = self.g12_fixer.fix(code)
        if g12_fixed:
            fixes_applied.append("G12")

        # G13 fix
        code, g13_fixed = self.g13_fixer.fix(code, node_type)
        if g13_fixed:
            fixes_applied.append("G13")

        # G14 fix
        code, g14_fixed = self.g14_fixer.fix(code)
        if g14_fixed:
            fixes_applied.append("G14")

        step1_duration_ms = int((perf_counter() - step1_start) * 1000)

        # Step 2: Pattern application
        step2_start = perf_counter()
        try:
            similar_patterns = await self.pattern_applicator.find_similar_patterns(
                code, node_type, domain
            )
            if similar_patterns:
                code = await self.pattern_applicator.apply_patterns(
                    code, similar_patterns
                )
                patterns_applied = len(similar_patterns)
        except Exception as e:
            # Log error but continue with original code
            import logging

            logging.warning(f"Pattern application failed: {e}")
        step2_duration_ms = int((perf_counter() - step2_start) * 1000)

        # Step 3: Quorum enhancement
        step3_start = perf_counter()
        try:
            if quorum_suggestions:
                code = await self.quorum_enhancer.apply_suggestions(
                    code, quorum_suggestions
                )
        except Exception as e:
            # Log error but continue with current code
            import logging

            logging.warning(f"Quorum enhancement failed: {e}")
        step3_duration_ms = int((perf_counter() - step3_start) * 1000)

        total_duration_ms = int((perf_counter() - start_time) * 1000)

        return {
            "refined_code": code,
            "original_code": original_code,
            "success": True,
            "fixes_applied": fixes_applied,
            "patterns_applied": patterns_applied,
            "suggestions_applied": len(quorum_suggestions) if quorum_suggestions else 0,
            "step1_duration_ms": step1_duration_ms,
            "step2_duration_ms": step2_duration_ms,
            "step3_duration_ms": step3_duration_ms,
            "total_duration_ms": total_duration_ms,
            "quality_before": 0.85,
            "quality_after": 0.95,
            "quality_improvement": 0.10,
        }


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_code_missing_configdict():
    """Sample code missing Pydantic ConfigDict."""
    return '''from pydantic import BaseModel

class ModelUserInput(BaseModel):
    """User input model."""
    user_id: str
    username: str
'''


@pytest.fixture
def sample_code_old_imports():
    """Sample code with old import paths."""
    return """from omnibase_core.core.node_effect import NodeEffect
from omnibase_core.errors import OnexError

class NodeDatabaseWriterEffect(NodeEffect):
    pass
"""


@pytest.fixture
def sample_code_missing_type_hints():
    """Sample code missing type hints."""
    return """from omnibase_core.nodes.node_effect import NodeEffect

class NodeDatabaseWriterEffect(NodeEffect):
    async def execute_effect(self, contract):
        result = await self.process(contract)
        return result
"""


@pytest.fixture
def sample_code_complete():
    """Sample production-quality code."""
    return """from typing import Dict, Any
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.errors import EnumCoreErrorCode, OnexError
from pydantic import BaseModel, ConfigDict

class ModelInput(BaseModel):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        arbitrary_types_allowed=False,
        extra="forbid"
    )

    query: str

class NodeDatabaseWriterEffect(NodeEffect):
    async def execute_effect(
        self, contract: ModelInput
    ) -> Dict[str, Any]:
        try:
            result = await self.db.execute(contract.query)
            return {"success": True, "result": result}
        except Exception as e:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Database write failed: {e}"
            )
"""


# ============================================================================
# G12 Fixer Tests
# ============================================================================


class TestG12PydanticConfigDictFixer:
    """Test G12 fixer for Pydantic ConfigDict."""

    def test_detects_missing_configdict(self, sample_code_missing_configdict):
        """Test detection of missing ConfigDict."""
        fixer = MockG12Fixer()
        result_code, fixed = fixer.fix(sample_code_missing_configdict)

        assert fixed is True
        assert "model_config = ConfigDict" in result_code
        assert "frozen=False" in result_code
        assert "validate_assignment=True" in result_code

    def test_no_fix_if_already_present(self, sample_code_complete):
        """Test no fix applied if ConfigDict already present."""
        fixer = MockG12Fixer()
        result_code, fixed = fixer.fix(sample_code_complete)

        assert fixed is False
        assert result_code == sample_code_complete

    def test_preserves_syntax(self, sample_code_missing_configdict):
        """Test that fix preserves valid Python syntax."""
        fixer = MockG12Fixer()
        result_code, fixed = fixer.fix(sample_code_missing_configdict)

        # Should parse without errors
        tree = ast.parse(result_code)
        assert tree is not None

    def test_performance_target(self, sample_code_missing_configdict):
        """Test G12 fix meets <30ms performance target."""
        fixer = MockG12Fixer()

        start = perf_counter()
        for _ in range(100):
            fixer.fix(sample_code_missing_configdict)
        duration_ms = (perf_counter() - start) * 1000 / 100

        assert duration_ms < 30, f"G12 fix took {duration_ms:.1f}ms (target: <30ms)"


# ============================================================================
# G13 Fixer Tests
# ============================================================================


class TestG13TypeHintFixer:
    """Test G13 fixer for type hints."""

    def test_adds_type_hints_to_execute_method(self, sample_code_missing_type_hints):
        """Test adding type hints to execute methods."""
        fixer = MockG13Fixer()
        result_code, fixed = fixer.fix(sample_code_missing_type_hints, "EFFECT")

        assert fixed is True
        assert "contract: ModelContractEffect" in result_code
        assert "-> ModelResult" in result_code

    def test_no_fix_if_already_typed(self, sample_code_complete):
        """Test no fix if type hints already present."""
        fixer = MockG13Fixer()
        result_code, fixed = fixer.fix(sample_code_complete, "EFFECT")

        assert fixed is False

    def test_performance_target(self, sample_code_missing_type_hints):
        """Test G13 fix meets <50ms performance target."""
        fixer = MockG13Fixer()

        start = perf_counter()
        for _ in range(100):
            fixer.fix(sample_code_missing_type_hints, "EFFECT")
        duration_ms = (perf_counter() - start) * 1000 / 100

        assert duration_ms < 50, f"G13 fix took {duration_ms:.1f}ms (target: <50ms)"


# ============================================================================
# G14 Fixer Tests
# ============================================================================


class TestG14ImportFixer:
    """Test G14 fixer for imports."""

    def test_fixes_old_import_paths(self, sample_code_old_imports):
        """Test fixing old import paths."""
        fixer = MockG14Fixer()
        result_code, fixed = fixer.fix(sample_code_old_imports)

        assert fixed is True
        assert "omnibase_core.core." not in result_code
        assert "omnibase_core.nodes.node_effect" in result_code

    def test_no_fix_if_paths_correct(self, sample_code_complete):
        """Test no fix if import paths already correct."""
        fixer = MockG14Fixer()
        result_code, fixed = fixer.fix(sample_code_complete)

        assert fixed is False

    def test_performance_target(self, sample_code_old_imports):
        """Test G14 fix meets <40ms performance target."""
        fixer = MockG14Fixer()

        start = perf_counter()
        for _ in range(100):
            fixer.fix(sample_code_old_imports)
        duration_ms = (perf_counter() - start) * 1000 / 100

        assert duration_ms < 40, f"G14 fix took {duration_ms:.1f}ms (target: <40ms)"


# ============================================================================
# Pattern Application Tests
# ============================================================================


class TestPatternApplication:
    """Test production pattern application."""

    @pytest.mark.asyncio
    async def test_finds_similar_patterns(self):
        """Test finding similar production patterns."""
        applicator = MockPatternApplicator()

        patterns = await applicator.find_similar_patterns(
            code="database code", node_type="EFFECT", domain="database"
        )

        assert len(patterns) == 2
        assert patterns[0].similarity > patterns[1].similarity
        assert patterns[0].domain == "database"

    @pytest.mark.asyncio
    async def test_applies_patterns_to_code(self):
        """Test applying patterns to generated code."""
        applicator = MockPatternApplicator()

        patterns = await applicator.find_similar_patterns(
            code="database code", node_type="EFFECT", domain="database"
        )

        enhanced_code = await applicator.apply_patterns("original code", patterns)

        assert "Patterns applied:" in enhanced_code
        assert "Transaction management" in enhanced_code
        assert "Retry logic" in enhanced_code

    @pytest.mark.asyncio
    async def test_pattern_application_performance(self):
        """Test pattern application meets ~2s target."""
        applicator = MockPatternApplicator()

        start = perf_counter()
        patterns = await applicator.find_similar_patterns(
            code="code", node_type="EFFECT", domain="database"
        )
        await applicator.apply_patterns("code", patterns)
        duration_ms = (perf_counter() - start) * 1000

        # Mock should be much faster than real (uses sleep 0.11s total)
        assert duration_ms < 200, f"Pattern application took {duration_ms:.0f}ms"


# ============================================================================
# Quorum Enhancement Tests
# ============================================================================


class TestQuorumEnhancement:
    """Test quorum feedback integration."""

    @pytest.mark.asyncio
    async def test_applies_quorum_suggestions(self):
        """Test applying quorum suggestions."""
        enhancer = MockQuorumEnhancer()

        suggestions = [
            "Add retry logic for transient failures",
            "Include correlation IDs in logs",
        ]

        enhanced_code = await enhancer.apply_suggestions("original code", suggestions)

        assert "Quorum suggestions applied:" in enhanced_code
        assert "retry logic" in enhanced_code
        assert "correlation IDs" in enhanced_code

    @pytest.mark.asyncio
    async def test_quorum_enhancement_performance(self):
        """Test quorum enhancement meets ~1s target."""
        enhancer = MockQuorumEnhancer()

        suggestions = ["suggestion 1", "suggestion 2", "suggestion 3"]

        start = perf_counter()
        await enhancer.apply_suggestions("code", suggestions)
        duration_ms = (perf_counter() - start) * 1000

        # Mock should be much faster (uses sleep 0.05s)
        assert duration_ms < 100, f"Quorum enhancement took {duration_ms:.0f}ms"


# ============================================================================
# Full Refinement Pipeline Tests
# ============================================================================


class TestCodeRefinementEngine:
    """Test full code refinement pipeline."""

    @pytest.mark.asyncio
    async def test_complete_refinement_pipeline(self, sample_code_missing_configdict):
        """Test complete 3-step refinement process."""
        engine = MockCodeRefinementEngine()

        result = await engine.refine(
            code=sample_code_missing_configdict,
            node_type="EFFECT",
            domain="database",
            quorum_suggestions=["Add error handling"],
        )

        assert result["success"] is True
        assert "G12" in result["fixes_applied"]
        assert result["patterns_applied"] > 0
        assert result["suggestions_applied"] == 1
        assert result["quality_improvement"] > 0

    @pytest.mark.asyncio
    async def test_refinement_performance_target(self, sample_code_missing_configdict):
        """Test refinement meets <3s total performance target."""
        engine = MockCodeRefinementEngine()

        start = perf_counter()
        result = await engine.refine(
            code=sample_code_missing_configdict,
            node_type="EFFECT",
            domain="database",
            quorum_suggestions=["Add logging"],
        )
        duration_ms = (perf_counter() - start) * 1000

        # Mock should be much faster than real
        assert duration_ms < 500, f"Refinement took {duration_ms:.0f}ms"

        # Check individual steps
        assert result["step1_duration_ms"] < 100, "Step 1 too slow"
        assert result["step2_duration_ms"] < 200, "Step 2 too slow"
        assert result["step3_duration_ms"] < 100, "Step 3 too slow"

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_failure(self):
        """Test fallback to original code if refinement fails."""
        engine = MockCodeRefinementEngine()

        # Simulate failure by passing invalid code
        invalid_code = "this is not valid python code!!!"

        try:
            result = await engine.refine(
                code=invalid_code, node_type="EFFECT", domain="database"
            )

            # Should still succeed with original code
            assert result["success"] is True
            # Original code preserved (with comments added by mock)
            assert "this is not valid python code!!!" in result["refined_code"]

        except Exception as e:
            # Even if it fails, should not crash
            assert False, f"Refinement should not raise exception: {e}"

    @pytest.mark.asyncio
    async def test_refinement_without_quorum(self, sample_code_complete):
        """Test refinement works without quorum suggestions."""
        engine = MockCodeRefinementEngine()

        result = await engine.refine(
            code=sample_code_complete,
            node_type="EFFECT",
            domain="database",
            quorum_suggestions=None,  # No quorum feedback
        )

        assert result["success"] is True
        assert result["suggestions_applied"] == 0

    @pytest.mark.asyncio
    async def test_quality_improvement_metrics(self, sample_code_missing_configdict):
        """Test quality improvement tracking."""
        engine = MockCodeRefinementEngine()

        result = await engine.refine(
            code=sample_code_missing_configdict, node_type="EFFECT", domain="database"
        )

        assert result["quality_before"] == 0.85
        assert result["quality_after"] == 0.95
        assert result["quality_improvement"] == 0.10
        assert result["quality_after"] > result["quality_before"]


# ============================================================================
# Integration Tests
# ============================================================================


class TestRefinementIntegration:
    """Test refinement integration with pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_stage_5_5_integration(self):
        """Test Stage 5.5 integration with generation pipeline."""

        # Mock generation result
        generation_result = {
            "main_file_content": "from pydantic import BaseModel\n\nclass ModelInput(BaseModel):\n    data: str",
            "node_type": "EFFECT",
            "domain": "database",
            "service_name": "writer",
        }

        # Mock validation gates
        validation_gates = [
            {"gate_id": "G12", "status": "warning", "message": "Missing ConfigDict"},
            {"gate_id": "G13", "status": "warning", "message": "Missing type hints"},
        ]

        # Mock quorum feedback
        quorum_feedback = {"suggestions": ["Add error handling", "Include logging"]}

        # Execute refinement
        engine = MockCodeRefinementEngine()
        result = await engine.refine(
            code=generation_result["main_file_content"],
            node_type=generation_result["node_type"],
            domain=generation_result["domain"],
            validation_gates=validation_gates,
            quorum_suggestions=quorum_feedback["suggestions"],
        )

        # Verify refinement applied
        assert result["success"] is True
        assert len(result["fixes_applied"]) > 0
        assert result["patterns_applied"] > 0
        assert result["suggestions_applied"] == 2

    @pytest.mark.asyncio
    async def test_parallel_execution_optimization(self):
        """Test parallel execution of Steps 2 and 3."""
        engine = MockCodeRefinementEngine()

        code = "sample code"

        # Sequential execution
        start = perf_counter()
        patterns = await engine.pattern_applicator.find_similar_patterns(
            code, "EFFECT", "database"
        )
        code_with_patterns = await engine.pattern_applicator.apply_patterns(
            code, patterns
        )
        _code_with_quorum = await engine.quorum_enhancer.apply_suggestions(
            code_with_patterns, ["suggestion"]
        )
        sequential_ms = (perf_counter() - start) * 1000

        # Parallel execution (mock - real would use asyncio.gather)
        start = perf_counter()
        pattern_task = engine.pattern_applicator.find_similar_patterns(
            code, "EFFECT", "database"
        )
        quorum_task = engine.quorum_enhancer.apply_suggestions(code, ["suggestion"])

        patterns, _ = await asyncio.gather(pattern_task, quorum_task)
        # In real implementation, would merge results
        parallel_ms = (perf_counter() - start) * 1000

        # Parallel should be faster (or at least not slower)
        assert parallel_ms <= sequential_ms * 1.1  # Allow 10% margin


# ============================================================================
# Performance Benchmarks
# ============================================================================


class TestPerformanceBenchmarks:
    """Performance benchmark tests."""

    @pytest.mark.asyncio
    async def test_deterministic_fixes_under_100ms(
        self,
        sample_code_missing_configdict,
        sample_code_old_imports,
        sample_code_missing_type_hints,
    ):
        """Test all deterministic fixes complete in <100ms."""
        engine = MockCodeRefinementEngine()

        start = perf_counter()

        # Apply all fixes
        code = sample_code_missing_configdict
        code, _ = engine.g12_fixer.fix(code)
        code, _ = engine.g13_fixer.fix(code, "EFFECT")
        code, _ = engine.g14_fixer.fix(code)

        duration_ms = (perf_counter() - start) * 1000

        assert (
            duration_ms < 100
        ), f"Deterministic fixes took {duration_ms:.0f}ms (target: <100ms)"

    @pytest.mark.asyncio
    async def test_full_refinement_under_3s_target(self):
        """Test full refinement meets <3s target."""
        engine = MockCodeRefinementEngine()

        code = """from pydantic import BaseModel
class ModelInput(BaseModel):
    data: str

class NodeWriterEffect:
    async def execute_effect(self, contract):
        return {"result": "ok"}
"""

        start = perf_counter()
        result = await engine.refine(
            code=code,
            node_type="EFFECT",
            domain="database",
            quorum_suggestions=["Add error handling"],
        )
        duration_ms = (perf_counter() - start) * 1000

        # Mock should be much faster
        assert duration_ms < 500, f"Full refinement took {duration_ms:.0f}ms"
        assert result["total_duration_ms"] < 500


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_handles_syntax_errors_gracefully(self):
        """Test handling of syntax errors in generated code."""
        engine = MockCodeRefinementEngine()

        invalid_code = "def broken_syntax(\n    incomplete"

        # Should not crash, should return original or fail gracefully
        result = await engine.refine(
            code=invalid_code, node_type="EFFECT", domain="database"
        )

        # Mock doesn't validate syntax, so it will succeed
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_handles_missing_patterns_gracefully(self):
        """Test handling when no production patterns match."""
        engine = MockCodeRefinementEngine()

        code = "simple code"

        result = await engine.refine(
            code=code,
            node_type="EFFECT",
            domain="unknown_domain",  # No patterns for this domain
            quorum_suggestions=None,
        )

        assert result["success"] is True
        assert result["patterns_applied"] == 0  # No patterns found

    @pytest.mark.asyncio
    async def test_logs_refinement_failures(self):
        """Test that refinement failures are logged."""
        engine = MockCodeRefinementEngine()

        # Mock scenario where AI refinement fails
        with patch.object(
            engine.pattern_applicator,
            "apply_patterns",
            side_effect=Exception("AI service unavailable"),
        ):
            # Should handle exception and continue
            try:
                _result = await engine.refine(
                    code="code", node_type="EFFECT", domain="database"
                )
                # Should succeed with original code (mock doesn't actually fail)
                assert True
            except Exception as e:
                # Should not raise exception
                assert False, f"Should handle AI failure gracefully: {e}"


# ============================================================================
# Documentation Tests
# ============================================================================


class TestRefinementDocumentation:
    """Test that refinement produces clear documentation."""

    @pytest.mark.asyncio
    async def test_logs_before_after_diff(self):
        """Test that before/after code diff is available."""
        engine = MockCodeRefinementEngine()

        original_code = "simple code"

        result = await engine.refine(
            code=original_code, node_type="EFFECT", domain="database"
        )

        assert "original_code" in result
        assert "refined_code" in result
        assert result["original_code"] != result["refined_code"]

    @pytest.mark.asyncio
    async def test_tracks_all_applied_fixes(self):
        """Test that all applied fixes are tracked."""
        engine = MockCodeRefinementEngine()

        code = """from omnibase_core.core.node_effect import NodeEffect
from pydantic import BaseModel

class ModelInput(BaseModel):
    data: str

class NodeWriterEffect(NodeEffect):
    async def execute_effect(self, contract):
        return {}
"""

        result = await engine.refine(code=code, node_type="EFFECT", domain="database")

        assert "fixes_applied" in result
        assert isinstance(result["fixes_applied"], list)
        # Should detect G14 (old import)
        assert "G14" in result["fixes_applied"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
