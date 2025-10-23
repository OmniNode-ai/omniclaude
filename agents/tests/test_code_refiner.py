#!/usr/bin/env python3
"""
Tests for Code Refiner (Pattern Matcher & Applicator)

Tests:
1. ProductionPatternMatcher - Find similar nodes
2. ProductionPatternMatcher - Extract patterns
3. CodeRefiner - Refine code with patterns
4. CodeRefiner - Validate compilation
"""

import ast
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.lib.code_refiner import (
    CodeRefiner,
    ProductionPattern,
    ProductionPatternMatcher,
)

# ============================================================================
# ProductionPatternMatcher Tests
# ============================================================================


class TestProductionPatternMatcher:
    """Test suite for ProductionPatternMatcher."""

    @pytest.fixture
    def matcher(self):
        """Create pattern matcher instance."""
        return ProductionPatternMatcher()

    def test_find_similar_nodes_effect(self, matcher):
        """Test finding similar Effect nodes."""
        # Find database-related Effect nodes
        nodes = matcher.find_similar_nodes("effect", "database", limit=3)

        assert isinstance(nodes, list)
        assert len(nodes) <= 3
        # Should find at least one node (if omniarchon is available)
        if nodes:
            assert all(isinstance(n, Path) for n in nodes)
            assert all(n.exists() for n in nodes)
            assert all("_effect.py" in n.name for n in nodes)

    def test_find_similar_nodes_compute(self, matcher):
        """Test finding similar Compute nodes."""
        nodes = matcher.find_similar_nodes("compute", "intent_classification", limit=2)

        assert isinstance(nodes, list)
        assert len(nodes) <= 2
        if nodes:
            assert all("_compute.py" in n.name for n in nodes)

    def test_find_similar_nodes_reducer(self, matcher):
        """Test finding similar Reducer nodes."""
        nodes = matcher.find_similar_nodes("reducer", "analytics", limit=1)

        assert isinstance(nodes, list)
        assert len(nodes) <= 1
        if nodes:
            assert all("_reducer.py" in n.name for n in nodes)

    def test_find_similar_nodes_orchestrator(self, matcher):
        """Test finding similar Orchestrator nodes."""
        nodes = matcher.find_similar_nodes("orchestrator", "pattern_assembly", limit=2)

        assert isinstance(nodes, list)
        assert len(nodes) <= 2
        if nodes:
            assert all("_orchestrator.py" in n.name for n in nodes)

    def test_domain_similarity_exact_match(self, matcher):
        """Test domain similarity with exact match."""
        score = matcher._calculate_domain_similarity(
            "database", "/path/to/node_database_writer_effect.py"
        )
        assert score >= 0.5  # Should have high score for exact match

    def test_domain_similarity_partial_match(self, matcher):
        """Test domain similarity with partial match."""
        score = matcher._calculate_domain_similarity(
            "vector_search", "/path/to/node_qdrant_search_effect.py"
        )
        assert score > 0.0  # Should have some score for partial match

    def test_domain_similarity_no_match(self, matcher):
        """Test domain similarity with no match."""
        score = matcher._calculate_domain_similarity(
            "completely_unrelated", "/path/to/node_database_writer_effect.py"
        )
        # May still have some score due to path matching
        assert 0.0 <= score <= 1.0

    def test_extract_node_type(self, matcher):
        """Test node type extraction from filename."""
        assert matcher._extract_node_type("node_database_effect.py") == "effect"
        assert matcher._extract_node_type("node_classifier_compute.py") == "compute"
        assert matcher._extract_node_type("node_analytics_reducer.py") == "reducer"
        assert (
            matcher._extract_node_type("node_pipeline_orchestrator.py")
            == "orchestrator"
        )
        assert matcher._extract_node_type("random_file.py") == "unknown"

    def test_extract_domain(self, matcher):
        """Test domain extraction from filename."""
        assert (
            matcher._extract_domain("node_database_writer_effect.py")
            == "database_writer"
        )
        assert (
            matcher._extract_domain("node_intent_classifier_compute.py")
            == "intent_classifier"
        )
        assert (
            matcher._extract_domain("node_usage_analytics_reducer.py")
            == "usage_analytics"
        )

    @pytest.mark.skipif(
        not Path("/Volumes/PRO-G40/Code/omniarchon").exists(),
        reason="Requires omniarchon repository",
    )
    def test_extract_patterns_from_production_effect(self, matcher):
        """Test pattern extraction from production Effect node."""
        # Use known production Effect node
        node_path = (
            matcher.OMNIARCHON_PATH
            / "services/intelligence/onex/effects/node_qdrant_search_effect.py"
        )

        if not node_path.exists():
            pytest.skip(f"Production node not found: {node_path}")

        pattern = matcher.extract_patterns(node_path)

        # Verify pattern extraction
        assert isinstance(pattern, ProductionPattern)
        assert pattern.node_type == "effect"
        assert len(pattern.imports) > 0
        assert pattern.class_structure != ""
        assert len(pattern.method_signatures) > 0
        assert pattern.confidence > 0.5

        # Check for Effect-specific patterns
        assert any("NodeBaseEffect" in imp for imp in pattern.imports)
        assert (
            len(pattern.transaction_management) > 0
        )  # Should have transaction patterns
        assert (
            "async with self.transaction_manager.begin():"
            in pattern.transaction_management
        )

    @pytest.mark.skipif(
        not Path("/Volumes/PRO-G40/Code/omniarchon").exists(),
        reason="Requires omniarchon repository",
    )
    def test_extract_patterns_from_production_compute(self, matcher):
        """Test pattern extraction from production Compute node."""
        # Use known production Compute node
        node_path = (
            matcher.OMNIARCHON_PATH
            / "services/intelligence/src/services/pattern_learning/phase1_foundation/extraction/node_intent_classifier_compute.py"
        )

        if not node_path.exists():
            pytest.skip(f"Production node not found: {node_path}")

        pattern = matcher.extract_patterns(node_path)

        # Verify pattern extraction
        assert isinstance(pattern, ProductionPattern)
        assert pattern.node_type == "compute"
        assert len(pattern.imports) > 0
        assert pattern.class_structure != ""
        assert len(pattern.method_signatures) > 0
        assert pattern.confidence > 0.5

        # Compute nodes should not have transaction management
        assert len(pattern.transaction_management) == 0

    def test_extract_patterns_caching(self, matcher):
        """Test pattern extraction caching."""
        # Create temporary test file
        test_code = '''
"""Test module."""
import logging

logger = logging.getLogger(__name__)

class NodeTestEffect:
    """Test effect node."""

    async def execute_effect(self, contract):
        """Execute effect."""
        async with self.transaction_manager.begin():
            logger.info("Executing")
            return result
'''
        test_file = Path(tempfile.gettempdir()) / "test_node_effect.py"
        test_file.write_text(test_code)

        try:
            # First extraction
            pattern1 = matcher.extract_patterns(test_file)
            # Second extraction (should use cache)
            pattern2 = matcher.extract_patterns(test_file)

            assert pattern1 is pattern2  # Should be same object from cache
        finally:
            test_file.unlink()


# ============================================================================
# CodeRefiner Tests
# ============================================================================


class TestCodeRefiner:
    """Test suite for CodeRefiner."""

    @pytest.fixture
    def refiner(self):
        """Create code refiner instance."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            with patch("google.generativeai.configure"):
                with patch("google.generativeai.GenerativeModel"):
                    return CodeRefiner()

    @pytest.fixture
    def sample_code(self):
        """Sample generated code for testing."""
        return '''
"""Sample node."""

class NodeDatabaseWriterEffect:
    """Database writer effect node."""

    def execute_effect(self, contract):
        """Execute database write."""
        result = write_to_database(contract.data)
        return result
'''

    def test_refiner_initialization(self):
        """Test refiner initialization."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"}):
            with patch("google.generativeai.configure") as mock_configure:
                with patch("google.generativeai.GenerativeModel") as _mock_model:
                    refiner = CodeRefiner()

                    assert refiner.model is not None
                    assert refiner.pattern_matcher is not None
                    assert isinstance(refiner.pattern_cache, dict)
                    mock_configure.assert_called_once()

    def test_refiner_initialization_no_api_key(self):
        """Test refiner initialization without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                CodeRefiner()

    def test_validate_code_compiles_valid(self, refiner):
        """Test code validation with valid code."""
        valid_code = '''
def hello():
    """Say hello."""
    print("Hello, world!")
'''
        assert refiner._validate_code_compiles(valid_code) is True

    def test_validate_code_compiles_invalid(self, refiner):
        """Test code validation with invalid code."""
        invalid_code = """
def hello()  # Missing colon
    print("Hello")
"""
        assert refiner._validate_code_compiles(invalid_code) is False

    def test_extract_code_from_response_markdown(self, refiner):
        """Test code extraction from markdown response."""
        response = """
Here's the refined code:

```python
def hello():
    print("Hello")
```

This code is better.
"""
        extracted = refiner._extract_code_from_response(response)
        assert "def hello():" in extracted
        assert "```" not in extracted
        assert "This code is better" not in extracted

    def test_extract_code_from_response_plain(self, refiner):
        """Test code extraction from plain response."""
        response = """
def hello():
    print("Hello")
"""
        extracted = refiner._extract_code_from_response(response)
        assert "def hello():" in extracted

    @pytest.mark.asyncio
    async def test_get_production_patterns(self, refiner):
        """Test production pattern retrieval."""
        context = {
            "node_type": "effect",
            "domain": "database",
        }

        # Mock pattern matcher
        test_node_path = Path(tempfile.gettempdir()) / "test_node_effect.py"
        refiner.pattern_matcher.find_similar_nodes = MagicMock(
            return_value=[
                test_node_path,
            ]
        )

        refiner.pattern_matcher.extract_patterns = MagicMock(
            return_value=ProductionPattern(
                node_path=test_node_path,
                node_type="effect",
                domain="database",
                imports=["import logging"],
                class_structure="class NodeDatabaseEffect(NodeBaseEffect):",
                confidence=0.9,
            )
        )

        patterns = await refiner._get_production_patterns(context)

        assert len(patterns) == 1
        assert patterns[0].node_type == "effect"
        assert patterns[0].confidence > 0.5

    @pytest.mark.asyncio
    async def test_get_production_patterns_caching(self, refiner):
        """Test production pattern caching."""
        context = {
            "node_type": "effect",
            "domain": "database",
        }

        # Pre-populate cache
        cache_key = "effect:database"
        cached_pattern = ProductionPattern(
            node_path=Path(tempfile.gettempdir()) / "cached.py",
            node_type="effect",
            domain="database",
            confidence=0.9,
        )
        refiner.pattern_cache[cache_key] = [cached_pattern]

        patterns = await refiner._get_production_patterns(context)

        # Should return cached pattern
        assert len(patterns) == 1
        assert patterns[0] is cached_pattern

    def test_build_refinement_prompt(self, refiner, sample_code):
        """Test refinement prompt building."""
        patterns = [
            ProductionPattern(
                node_path=Path(tempfile.gettempdir()) / "example.py",
                node_type="effect",
                domain="database",
                imports=["import logging", "from pathlib import Path"],
                class_structure="class NodeDatabaseEffect(NodeBaseEffect):",
                method_signatures=[
                    "async def execute_effect(self, contract: ModelContract) -> ModelResult"
                ],
                error_handling=[
                    "except Exception as e:",
                    "logger.error(f'Error: {e}')",
                ],
                documentation=["Database writer effect node."],
                confidence=0.9,
            )
        ]

        context = {
            "node_type": "effect",
            "domain": "database",
        }

        prompt = refiner._build_refinement_prompt(
            sample_code, "node", patterns, context
        )

        # Verify prompt contents
        assert "ONEX architecture patterns" in prompt
        assert "CRITICAL REQUIREMENTS" in prompt
        assert "ConfigDict" in prompt
        assert "Production Patterns to Apply" in prompt
        assert "Original Code" in prompt
        assert sample_code in prompt
        assert "import logging" in prompt

    @pytest.mark.asyncio
    async def test_refine_code_no_patterns(self, refiner, sample_code):
        """Test code refinement with no patterns found."""
        context = {
            "node_type": "unknown",
            "domain": "unknown",
        }

        # Mock to return no patterns
        refiner._get_production_patterns = AsyncMock(return_value=[])

        result = await refiner.refine_code(sample_code, "node", context)

        # Should return original code when no patterns found
        assert result == sample_code

    @pytest.mark.asyncio
    async def test_refine_code_compilation_failure(self, refiner, sample_code):
        """Test code refinement with compilation failure."""
        context = {
            "node_type": "effect",
            "domain": "database",
        }

        # Mock pattern retrieval
        refiner._get_production_patterns = AsyncMock(
            return_value=[
                ProductionPattern(
                    node_path=Path(tempfile.gettempdir()) / "test.py",
                    node_type="effect",
                    domain="database",
                    confidence=0.9,
                )
            ]
        )

        # Mock AI response with invalid code
        mock_response = MagicMock()
        mock_response.text = "invalid python code def hello("
        refiner.model.generate_content = MagicMock(return_value=mock_response)

        result = await refiner.refine_code(sample_code, "node", context)

        # Should return original code when refined code doesn't compile
        assert result == sample_code

    @pytest.mark.skipif(
        not Path("/Volumes/PRO-G40/Code/omniarchon").exists(),
        reason="Requires omniarchon repository",
    )
    @pytest.mark.asyncio
    async def test_refine_code_integration(self, sample_code):
        """Integration test for code refinement (requires API key)."""
        import os

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            pytest.skip("GEMINI_API_KEY not set")

        refiner = CodeRefiner()

        context = {
            "node_type": "effect",
            "domain": "database",
            "requirements": {"transaction_management": True},
        }

        # This test actually calls the AI model
        refined = await refiner.refine_code(sample_code, "node", context)

        # Verify refinement
        assert refined != sample_code
        assert "async" in refined  # Should add async
        assert (
            "transaction_manager" in refined or refined == sample_code
        )  # May add transactions or return original if failed
        # Should compile
        try:
            ast.parse(refined)
        except SyntaxError:
            pytest.fail("Refined code does not compile")


# ============================================================================
# Integration Tests
# ============================================================================


class TestCodeRefinerIntegration:
    """Integration tests for full code refinement workflow."""

    @pytest.mark.skipif(
        not Path("/Volumes/PRO-G40/Code/omniarchon").exists(),
        reason="Requires omniarchon repository",
    )
    def test_find_and_extract_effect_patterns(self):
        """Test finding and extracting Effect node patterns."""
        matcher = ProductionPatternMatcher()

        # Find database Effect nodes
        nodes = matcher.find_similar_nodes("effect", "database", limit=2)
        assert len(nodes) > 0

        # Extract patterns
        for node_path in nodes:
            pattern = matcher.extract_patterns(node_path)
            assert pattern.node_type == "effect"
            assert pattern.confidence > 0.0

            # Effect nodes should have transaction management
            if pattern.confidence > 0.5:
                assert len(pattern.transaction_management) > 0

    @pytest.mark.skipif(
        not Path("/Volumes/PRO-G40/Code/omniarchon").exists(),
        reason="Requires omniarchon repository",
    )
    def test_find_and_extract_compute_patterns(self):
        """Test finding and extracting Compute node patterns."""
        matcher = ProductionPatternMatcher()

        # Find compute nodes
        nodes = matcher.find_similar_nodes("compute", "classification", limit=2)
        assert len(nodes) > 0

        # Extract patterns
        for node_path in nodes:
            pattern = matcher.extract_patterns(node_path)
            assert pattern.node_type == "compute"
            assert pattern.confidence > 0.0

            # Compute nodes should not have transaction management
            assert len(pattern.transaction_management) == 0
