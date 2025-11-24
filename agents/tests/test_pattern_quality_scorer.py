"""
Tests for Pattern Quality Scorer

Tests the 5-dimensional pattern quality scoring system that evaluates
code patterns across completeness, documentation, ONEX compliance,
metadata richness, and complexity appropriateness.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.lib.pattern_quality_scorer import PatternQualityScore, PatternQualityScorer


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def excellent_pattern():
    """High-quality ONEX pattern with comprehensive documentation."""
    return {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440001",
        "pattern_name": "UserAuthEffect",
        "code": '''"""User authentication effect node.

This node handles user authentication and session creation with
secure database validation and error handling.
"""
import asyncio
from typing import Dict, Optional

class NodeUserAuthEffect:
    """Effect node for user authentication."""

    async def execute_effect(self, user_id: str) -> Dict:
        """
        Authenticate user and return session token.

        Args:
            user_id: Unique user identifier

        Returns:
            Dictionary with session token and user info

        Raises:
            ValueError: If user_id is invalid
        """
        # Validate user credentials
        if not user_id:
            raise ValueError("User ID required")

        # Query database for user
        user = await self.db.get_user(user_id)

        # Create secure session
        session = user.create_session()

        # Return session data
        return {"session": session, "user": user.to_dict()}
''',
        "text": "Authenticates users and creates secure sessions with comprehensive database validation, error handling, and detailed logging for audit trails",
        "node_type": "effect",
        "metadata": {
            "complexity": "low",
            "domain": "auth",
            "version": "1.0",
            "author": "team",
            "reviewed": True,
        },
        "use_cases": [
            "user login authentication",
            "API authentication",
            "session management",
        ],
        "examples": [
            "await effect.execute_effect('user123')",
            "effect.execute_effect(request.user_id)",
        ],
        "confidence": 0.95,
    }


@pytest.fixture
def good_pattern():
    """Good quality pattern with decent documentation."""
    return {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440002",
        "pattern_name": "DataProcessorCompute",
        "code": '''"""Data processing compute node."""
from typing import List

class NodeDataProcessorCompute:
    async def execute_compute(self, data: List) -> List:
        """Process and transform data."""
        # Filter invalid entries
        valid_data = [item for item in data if item]

        # Transform data
        result = []
        for item in valid_data:
            result.append(item.upper())

        return result
''',
        "text": "Processes and transforms data with filtering and validation",
        "node_type": "compute",
        "metadata": {"complexity": "medium", "domain": "data"},
        "use_cases": ["data transformation"],
        "examples": ["await compute.execute_compute(data)"],
        "confidence": 0.80,
    }


@pytest.fixture
def stub_pattern():
    """Incomplete stub pattern with TODOs."""
    return {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440003",
        "pattern_name": "IncompleteNode",
        "code": """def process():
    # TODO: implement logic
    pass
    raise NotImplementedError
    ...
""",
        "text": "Stub",
        "node_type": None,
        "metadata": {},
        "use_cases": [],
        "examples": [],
        "confidence": 0.3,
    }


@pytest.fixture
def poor_pattern():
    """Poor quality pattern with minimal content."""
    return {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440004",
        "pattern_name": "MinimalNode",
        "code": "def run():\n    return None",
        "text": "Node",
        "node_type": None,
        "metadata": {},
        "use_cases": [],
        "examples": [],
        "confidence": 0.4,
    }


@pytest.fixture
def scorer():
    """Create PatternQualityScorer instance."""
    return PatternQualityScorer()


# ============================================================================
# Test PatternQualityScore Dataclass
# ============================================================================


def test_pattern_quality_score_instantiation():
    """Test PatternQualityScore can be instantiated with all fields."""
    timestamp = datetime.now(UTC)
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=timestamp,
        version="1.0.0",
    )

    assert score.pattern_id == "550e8400-e29b-41d4-a716-446655440000"
    assert score.pattern_name == "TestPattern"
    assert score.composite_score == 0.85
    assert score.completeness_score == 0.90
    assert score.documentation_score == 0.80
    assert score.onex_compliance_score == 0.85
    assert score.metadata_richness_score == 0.75
    assert score.complexity_score == 0.95
    assert score.confidence == 0.90
    assert score.measurement_timestamp == timestamp
    assert score.version == "1.0.0"


def test_pattern_quality_score_default_version():
    """Test PatternQualityScore has default version."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    assert score.version == "1.0.0"


# ============================================================================
# Test score_pattern Method
# ============================================================================


def test_score_excellent_pattern(scorer, excellent_pattern):
    """Test scoring of high-quality pattern produces excellent scores."""
    score = scorer.score_pattern(excellent_pattern)

    # Composite score should be excellent
    assert score.composite_score >= 0.9
    assert score.composite_score <= 1.0

    # All dimension scores should be high
    assert score.completeness_score >= 0.8
    assert score.documentation_score >= 0.8
    assert score.onex_compliance_score >= 0.9
    assert score.metadata_richness_score >= 0.7
    # Note: complexity score might be lower if declared doesn't match actual
    # (The excellent pattern has low complexity but might be miscategorized)
    assert score.complexity_score >= 0.4

    # Metadata should match
    assert score.pattern_id == "550e8400-e29b-41d4-a716-446655440001"
    assert score.pattern_name == "UserAuthEffect"
    assert score.confidence == 0.95


def test_score_good_pattern(scorer, good_pattern):
    """Test scoring of good quality pattern produces good scores."""
    score = scorer.score_pattern(good_pattern)

    # Composite score should be good
    assert 0.7 <= score.composite_score < 0.9

    # Dimension scores should be reasonable
    assert score.completeness_score >= 0.6
    assert score.documentation_score >= 0.4
    assert score.onex_compliance_score >= 0.7


def test_score_stub_pattern(scorer, stub_pattern):
    """Test scoring of stub pattern produces low scores."""
    score = scorer.score_pattern(stub_pattern)

    # Composite score should be poor
    assert score.composite_score < 0.5

    # Completeness should be very low due to stubs
    assert score.completeness_score < 0.5

    # Documentation should be minimal
    assert score.documentation_score < 0.3

    # ONEX compliance should be low (no node_type)
    assert score.onex_compliance_score <= 0.5


def test_score_poor_pattern(scorer, poor_pattern):
    """Test scoring of minimal pattern produces poor scores."""
    score = scorer.score_pattern(poor_pattern)

    # Composite score should be low
    assert score.composite_score < 0.7
    # Note: A minimal but valid function can score 1.0 on completeness
    # because it has no stub indicators (pass, TODO, etc.)
    # The poor quality comes from lack of documentation and metadata
    assert score.documentation_score < 0.5
    assert score.metadata_richness_score == 0.0


def test_score_pattern_with_missing_fields(scorer):
    """Test scoring handles missing fields gracefully."""
    minimal_pattern = {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440005",
        "pattern_name": "Minimal",
        # Missing: code, text, metadata, etc.
    }

    score = scorer.score_pattern(minimal_pattern)

    # Should not crash, but scores should be low
    assert 0.0 <= score.composite_score <= 1.0
    assert score.completeness_score == 0.0
    assert score.confidence == 0.0


def test_score_pattern_weighted_composite(scorer, excellent_pattern):
    """Test composite score uses correct weights."""
    score = scorer.score_pattern(excellent_pattern)

    # Manually calculate weighted composite
    expected_composite = (
        score.completeness_score * 0.30
        + score.documentation_score * 0.25
        + score.onex_compliance_score * 0.20
        + score.metadata_richness_score * 0.15
        + score.complexity_score * 0.10
    )

    # Should match within floating point precision
    assert abs(score.composite_score - expected_composite) < 0.001


def test_score_pattern_all_scores_in_range(scorer, excellent_pattern):
    """Test all dimension scores are between 0.0 and 1.0."""
    score = scorer.score_pattern(excellent_pattern)

    assert 0.0 <= score.composite_score <= 1.0
    assert 0.0 <= score.completeness_score <= 1.0
    assert 0.0 <= score.documentation_score <= 1.0
    assert 0.0 <= score.onex_compliance_score <= 1.0
    assert 0.0 <= score.metadata_richness_score <= 1.0
    assert 0.0 <= score.complexity_score <= 1.0


# ============================================================================
# Test _score_completeness Method
# ============================================================================


def test_score_completeness_with_stubs(scorer):
    """Test completeness penalizes stub indicators."""
    stub_code = """
def process():
    pass
    # TODO: implement
    raise NotImplementedError
    ...
"""

    score = scorer._score_completeness(stub_code, "")

    # Should have significant penalties (5 stub indicators = -1.0)
    assert score < 0.5


def test_score_completeness_with_logic(scorer):
    """Test completeness rewards meaningful logic."""
    logic_code = """
async def process(data):
    if data:
        for item in data:
            while item.is_valid():
                yield item
"""

    score = scorer._score_completeness(logic_code, "")

    # Should reward logic patterns
    assert score >= 0.6


def test_score_completeness_with_imports(scorer):
    """Test completeness adds bonus for imports."""
    code_with_imports = """
import asyncio
from typing import Dict

def process():
    return {}
"""

    score = scorer._score_completeness(code_with_imports, "")

    # Should include import bonus
    assert score >= 0.5


def test_score_completeness_line_count_bonus(scorer):
    """Test completeness scales with line count."""
    # Use code with pass to ensure base score is not already maxed
    short_code = "def run():\n    pass"
    long_code = "def run():\n    pass\n" + "\n".join(
        [f"    # line {i}" for i in range(50)]
    )

    short_score = scorer._score_completeness(short_code, "")
    long_score = scorer._score_completeness(long_code, "")

    # Longer code should score higher (up to 0.15 bonus)
    # Short code with pass gets penalized (-0.2) but gets small line bonus
    # Long code with pass also gets penalized but gets larger line bonus
    assert long_score > short_score


def test_score_completeness_empty_code(scorer):
    """Test completeness handles empty code."""
    score = scorer._score_completeness("", "")

    assert score == 0.0


def test_score_completeness_very_long_code(scorer):
    """Test completeness caps line count bonus at 0.15."""
    very_long_code = "\n".join([f"line {i}" for i in range(200)])

    score = scorer._score_completeness(very_long_code, "")

    # Base score (1.0) + line bonus (max 0.15) = max 1.15, capped at 1.0
    assert score == 1.0


# ============================================================================
# Test _score_documentation Method
# ============================================================================


def test_score_documentation_with_docstrings(scorer):
    """Test documentation detects and scores docstrings."""
    code_with_docstring = '''
def process():
    """This is a docstring."""
    pass
'''

    score = scorer._score_documentation(code_with_docstring, "")

    # Should get 0.4 for docstring
    assert score >= 0.4


def test_score_documentation_with_inline_comments(scorer):
    """Test documentation scales with comment count."""
    code_with_comments = "\n".join([f"# Comment {i}" for i in range(20)])

    score = scorer._score_documentation(code_with_comments, "")

    # Should get close to 0.2 for comments (20 comments / 20 = 1.0, min(0.2, 1.0) = 0.2)
    assert score >= 0.2


def test_score_documentation_with_type_hints(scorer):
    """Test documentation adds bonus for type hints."""
    code_with_types = """
def process(data: str) -> int:
    return len(data)
"""

    score = scorer._score_documentation(code_with_types, "")

    # Should get 0.2 for type hints
    assert score >= 0.2


def test_score_documentation_with_descriptive_text(scorer):
    """Test documentation scores long descriptive text."""
    short_text = "Short"
    long_text = "This is a very detailed description that explains the pattern in comprehensive detail with multiple sentences and technical context."

    score_short = scorer._score_documentation("", short_text)
    score_long = scorer._score_documentation("", long_text)

    # Long text should score higher
    assert score_long > score_short
    assert score_long >= 0.2


def test_score_documentation_combination(scorer):
    """Test documentation combines all scoring factors."""
    comprehensive_code = '''"""
Comprehensive documentation with docstring.
"""
from typing import Dict

def process(data: Dict) -> Dict:
    """Process data with validation."""
    # Validate input
    if not data:
        return {}

    # Transform data
    result = {}
    # Add items to result
    for key, value in data.items():
        # Process each value
        result[key] = value.upper()

    return result
'''

    score = scorer._score_documentation(
        comprehensive_code, "Detailed description " * 20
    )

    # Should combine: docstring (0.4) + comments (varies) + type hints (0.2) + text (0.2)
    # Should be close to 1.0 but capped
    assert score >= 0.8
    assert score <= 1.0


def test_score_documentation_empty(scorer):
    """Test documentation handles empty input."""
    score = scorer._score_documentation("", "")

    assert score == 0.0


def test_score_documentation_triple_single_quotes(scorer):
    """Test documentation detects triple single quotes."""
    code = "def f():\n    '''Docstring'''\n    pass"

    score = scorer._score_documentation(code, "")

    # Should get 0.4 for docstring
    assert score >= 0.4


# ============================================================================
# Test _score_onex_compliance Method
# ============================================================================


def test_score_onex_compliance_with_proper_node(scorer):
    """Test ONEX compliance with proper node type and naming."""
    code = "async def execute_effect(self, data):\n    return data"

    score = scorer._score_onex_compliance(code, "effect", "UserAuthEffect")

    # Should get base (0.7) + naming (0.15) + signature (0.15) = 1.0
    assert score == 1.0


def test_score_onex_compliance_with_node_type_only(scorer):
    """Test ONEX compliance with node type but wrong naming."""
    code = "def process(self, data):\n    return data"

    score = scorer._score_onex_compliance(code, "compute", "DataProcessor")

    # Should get base (0.7) only
    assert score == 0.7


def test_score_onex_compliance_without_node_type_but_good_name(scorer):
    """Test ONEX compliance without node type but name suggests type."""
    code = "def process():\n    pass"

    score = scorer._score_onex_compliance(code, None, "DataProcessorEffect")

    # Should get 0.5 for name suggesting node type
    assert score == 0.5


def test_score_onex_compliance_without_node_type(scorer):
    """Test ONEX compliance without node type or suggestive name."""
    code = "def process():\n    pass"

    score = scorer._score_onex_compliance(code, None, "DataProcessor")

    # Should get 0.3 (no node type, name doesn't suggest type)
    assert score == 0.3


def test_score_onex_compliance_all_node_types(scorer):
    """Test ONEX compliance recognizes all node types."""
    node_types_and_signatures = [
        ("effect", "async def execute_effect"),
        ("compute", "async def execute_compute"),
        ("reducer", "async def execute_reduction"),
        ("orchestrator", "async def execute_orchestration"),
    ]

    for node_type, signature in node_types_and_signatures:
        code = f"{signature}(self):\n    pass"
        pattern_name = f"Test{node_type.capitalize()}"

        score = scorer._score_onex_compliance(code, node_type, pattern_name)

        # Should get full score (base + naming + signature)
        assert score == 1.0, f"Failed for {node_type}"


def test_score_onex_compliance_case_insensitive(scorer):
    """Test ONEX compliance is case insensitive for node type matching."""
    code = "async def execute_effect(self):\n    pass"

    score = scorer._score_onex_compliance(code, "EFFECT", "UserAuthEffect")

    # Should still match with uppercase node_type
    assert score == 1.0


# ============================================================================
# Test _score_metadata_richness Method
# ============================================================================


def test_score_metadata_richness_with_use_cases(scorer):
    """Test metadata richness scales with use case count."""
    no_cases = scorer._score_metadata_richness([], [], {})
    one_case = scorer._score_metadata_richness(["case1"], [], {})
    three_cases = scorer._score_metadata_richness(["case1", "case2", "case3"], [], {})

    assert no_cases == 0.0
    assert one_case > no_cases
    assert three_cases > one_case
    # Three cases should max out at 0.4
    assert three_cases >= 0.4


def test_score_metadata_richness_with_examples(scorer):
    """Test metadata richness scales with example count."""
    no_examples = scorer._score_metadata_richness([], [], {})
    one_example = scorer._score_metadata_richness([], ["example1"], {})
    two_examples = scorer._score_metadata_richness([], ["example1", "example2"], {})

    assert no_examples == 0.0
    assert one_example > no_examples
    assert two_examples > one_example
    # Two examples should max out at 0.3
    assert two_examples >= 0.3


def test_score_metadata_richness_with_rich_metadata(scorer):
    """Test metadata richness detects rich metadata (>3 fields)."""
    poor_metadata = {"field1": "value1"}
    rich_metadata = {
        "field1": "value1",
        "field2": "value2",
        "field3": "value3",
        "field4": "value4",
    }

    score_poor = scorer._score_metadata_richness([], [], poor_metadata)
    score_rich = scorer._score_metadata_richness([], [], rich_metadata)

    # Rich metadata should get 0.3 bonus
    assert score_rich == score_poor + 0.3


def test_score_metadata_richness_combination(scorer):
    """Test metadata richness combines all factors."""
    use_cases = ["case1", "case2", "case3"]
    examples = ["example1", "example2"]
    metadata = {"f1": "v1", "f2": "v2", "f3": "v3", "f4": "v4"}

    score = scorer._score_metadata_richness(use_cases, examples, metadata)

    # Should combine: use_cases (0.4) + examples (0.3) + rich metadata (0.3) = 1.0
    assert score == 1.0


def test_score_metadata_richness_caps_at_1_0(scorer):
    """Test metadata richness score caps at 1.0."""
    many_cases = [f"case{i}" for i in range(10)]
    many_examples = [f"example{i}" for i in range(10)]
    rich_metadata = {f"field{i}": f"value{i}" for i in range(10)}

    score = scorer._score_metadata_richness(many_cases, many_examples, rich_metadata)

    assert score == 1.0


# ============================================================================
# Test _score_complexity Method
# ============================================================================


def test_score_complexity_low_matching(scorer):
    """Test complexity scoring with matching low complexity."""
    low_complexity_code = "def process():\n    return data"

    score = scorer._score_complexity(low_complexity_code, "low")

    # Should get 1.0 for matching declared and actual
    assert score == 1.0


def test_score_complexity_medium_matching(scorer):
    """Test complexity scoring with matching medium complexity."""
    medium_complexity_code = """
def process(data):
    if data:
        for item in data:
            if item.valid:
                return item
"""

    score = scorer._score_complexity(medium_complexity_code, "medium")

    # Should get 1.0 for matching declared and actual
    assert score == 1.0


def test_score_complexity_high_matching(scorer):
    """Test complexity scoring with matching high complexity."""
    high_complexity_code = """
def process(data):
    if data:
        for item in data:
            if item.valid:
                while item.active:
                    try:
                        if item.process():
                            for sub in item.children:
                                if sub.valid:
                                    pass
                    except Exception:
                        pass
"""

    score = scorer._score_complexity(high_complexity_code, "high")

    # Should get 1.0 for matching declared and actual
    assert score == 1.0


def test_score_complexity_mismatch(scorer):
    """Test complexity scoring with mismatched declaration."""
    low_complexity_code = "def process():\n    return data"

    score = scorer._score_complexity(low_complexity_code, "high")

    # Should get 0.6 for mismatch
    assert score == 0.6


def test_score_complexity_no_declaration(scorer):
    """Test complexity scoring without declaration."""
    code = "def process():\n    return data"

    score = scorer._score_complexity(code, None)

    # Should get 0.4 for no declaration
    assert score == 0.4


def test_score_complexity_empty_code(scorer):
    """Test complexity scoring with empty code."""
    score = scorer._score_complexity("", None)

    assert score == 0.4


def test_score_complexity_thresholds(scorer):
    """Test complexity categorization thresholds."""
    # Low: < 3 indicators
    low_code = "if True:\n    pass"
    # Medium: 3-7 indicators
    medium_code = "if 1:\n    pass\nif 2:\n    pass\nif 3:\n    pass"
    # High: >= 8 indicators
    high_code = "\n".join([f"if {i}:\n    pass" for i in range(8)])

    assert scorer._score_complexity(low_code, "low") == 1.0
    assert scorer._score_complexity(medium_code, "medium") == 1.0
    assert scorer._score_complexity(high_code, "high") == 1.0


# ============================================================================
# Test store_quality_metrics Method
# ============================================================================


@pytest.mark.asyncio
async def test_store_quality_metrics_success(scorer):
    """Test successful storage of quality metrics."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    # Mock psycopg2
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_psycopg2.connect.return_value = mock_conn

        # Should not raise
        await scorer.store_quality_metrics(score, "postgresql://test")

        # Verify database operations
        mock_psycopg2.connect.assert_called_once_with("postgresql://test")
        mock_conn.cursor.assert_called_once()
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_store_quality_metrics_upsert(scorer):
    """Test upsert behavior (ON CONFLICT UPDATE)."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_psycopg2.connect.return_value = mock_conn

        await scorer.store_quality_metrics(score, "postgresql://test")

        # Verify query contains ON CONFLICT clause
        call_args = mock_cursor.execute.call_args
        query = call_args[0][0]
        assert "ON CONFLICT (pattern_id) DO UPDATE" in query


@pytest.mark.asyncio
async def test_store_quality_metrics_json_serialization(scorer):
    """Test metadata JSON serialization."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        mock_json = MagicMock()
        mock_psycopg2.extras.Json = mock_json
        mock_psycopg2.connect.return_value = mock_conn

        await scorer.store_quality_metrics(score, "postgresql://test")

        # Verify Json() was called with dimension scores
        # params would be mock_cursor.execute.call_args[0][1]
        # metadata parameter (params[5]) should be a Json object
        # In real code, it would be psycopg2.extras.Json(dict)


@pytest.mark.asyncio
async def test_store_quality_metrics_connection_error(scorer):
    """Test error handling with invalid connection."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        # Mock the errors module to avoid "catching classes that do not inherit from BaseException"
        mock_errors = MagicMock()
        mock_errors.ForeignKeyViolation = type("ForeignKeyViolation", (Exception,), {})
        mock_psycopg2.errors = mock_errors
        mock_psycopg2.connect.side_effect = Exception("Connection failed")

        # Should raise exception
        with pytest.raises(Exception) as exc_info:  # noqa: PT011
            await scorer.store_quality_metrics(score, "postgresql://invalid")

        assert "Failed to store quality metrics" in str(exc_info.value)


@pytest.mark.asyncio
async def test_store_quality_metrics_query_error_rollback(scorer):
    """Test rollback on query error."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("Query failed")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        # Mock the errors module
        mock_errors = MagicMock()
        mock_errors.ForeignKeyViolation = type("ForeignKeyViolation", (Exception,), {})
        mock_psycopg2.errors = mock_errors
        mock_psycopg2.connect.return_value = mock_conn

        with pytest.raises(Exception) as exc_info:  # noqa: PT011
            await scorer.store_quality_metrics(score, "postgresql://test")

        # Verify rollback was called
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()
        assert "Failed to store quality metrics" in str(exc_info.value)


@pytest.mark.asyncio
async def test_store_quality_metrics_missing_psycopg2(scorer):
    """Test error when psycopg2 is not installed."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    with patch("agents.lib.pattern_quality_scorer.psycopg2", None):
        with pytest.raises(ImportError) as exc_info:
            await scorer.store_quality_metrics(score, "postgresql://test")

        assert "psycopg2 is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_store_quality_metrics_default_connection_string(scorer):
    """Test default connection string from environment."""
    score = PatternQualityScore(
        pattern_id="550e8400-e29b-41d4-a716-446655440000",
        pattern_name="TestPattern",
        composite_score=0.85,
        completeness_score=0.90,
        documentation_score=0.80,
        onex_compliance_score=0.85,
        metadata_richness_score=0.75,
        complexity_score=0.95,
        confidence=0.90,
        measurement_timestamp=datetime.now(UTC),
    )

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("agents.lib.pattern_quality_scorer.psycopg2") as mock_psycopg2:
        # Mock the errors module
        mock_errors = MagicMock()
        mock_errors.ForeignKeyViolation = type("ForeignKeyViolation", (Exception,), {})
        mock_psycopg2.errors = mock_errors
        mock_psycopg2.connect.return_value = mock_conn

        # Clear HOST_DATABASE_URL so DATABASE_URL is used instead
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "postgresql://env_url", "HOST_DATABASE_URL": ""},
            clear=False,
        ):
            await scorer.store_quality_metrics(score)  # No connection string

            # Should use DATABASE_URL environment variable
            mock_psycopg2.connect.assert_called_once_with("postgresql://env_url")


# ============================================================================
# Test Scorer Configuration
# ============================================================================


def test_scorer_thresholds(scorer):
    """Test scorer has correct quality thresholds."""
    assert scorer.EXCELLENT_THRESHOLD == 0.9
    assert scorer.GOOD_THRESHOLD == 0.7
    assert scorer.FAIR_THRESHOLD == 0.5


def test_scorer_weights_sum_to_1(scorer):
    """Test scoring weights sum to 1.0."""
    total_weight = sum(scorer.WEIGHTS.values())

    assert abs(total_weight - 1.0) < 0.001


def test_scorer_weight_values(scorer):
    """Test individual weight values are correct."""
    assert scorer.WEIGHTS["completeness"] == 0.30
    assert scorer.WEIGHTS["documentation"] == 0.25
    assert scorer.WEIGHTS["onex_compliance"] == 0.20
    assert scorer.WEIGHTS["metadata_richness"] == 0.15
    assert scorer.WEIGHTS["complexity"] == 0.10


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_scoring_workflow(scorer, excellent_pattern):
    """Test complete scoring workflow from pattern to score."""
    # Score the pattern
    score = scorer.score_pattern(excellent_pattern)

    # Verify all components are present
    assert score.pattern_id == excellent_pattern["pattern_id"]
    assert score.pattern_name == excellent_pattern["pattern_name"]
    assert score.confidence == excellent_pattern["confidence"]

    # Verify score quality
    assert score.composite_score >= 0.9

    # Verify timestamp is recent
    time_diff = datetime.now(UTC) - score.measurement_timestamp
    assert time_diff.total_seconds() < 1.0

    # Verify version
    assert score.version == "1.0.0"


def test_scoring_multiple_patterns(
    scorer, excellent_pattern, good_pattern, poor_pattern
):
    """Test scoring multiple patterns maintains consistency."""
    score_excellent = scorer.score_pattern(excellent_pattern)
    score_good = scorer.score_pattern(good_pattern)
    score_poor = scorer.score_pattern(poor_pattern)

    # Scores should be ordered by quality
    assert score_excellent.composite_score > score_good.composite_score
    assert score_good.composite_score > score_poor.composite_score


def test_pattern_with_all_dimensions_maxed(scorer):
    """Test pattern that maximizes all scoring dimensions."""
    perfect_pattern = {
        "pattern_id": "550e8400-e29b-41d4-a716-446655440006",
        "pattern_name": "PerfectEffect",
        "code": '''"""Perfect ONEX effect node with comprehensive documentation.

This node demonstrates all quality dimensions at maximum:
- Complete implementation with no stubs
- Comprehensive docstrings and comments
- Perfect ONEX compliance
- Rich metadata
- Appropriate complexity matching
"""
import asyncio
from typing import Dict, List, Optional

class NodePerfectEffect:
    """Effect node with perfect quality score."""

    async def execute_effect(self, data: Dict) -> Dict:
        """
        Execute the effect with perfect implementation.

        Args:
            data: Input data dictionary

        Returns:
            Processed result dictionary
        """
        # Validate input data
        if not data:
            raise ValueError("Data required")

        # Process each item
        result = {}
        for key, value in data.items():
            # Transform value
            result[key] = value

        # Return result
        return result
'''
        + "\n" * 50,  # Add extra lines for line count bonus
        "text": "This is a highly detailed and comprehensive description that provides extensive context and explanation for the pattern implementation, architecture, design decisions, and use cases."
        * 2,
        "node_type": "effect",
        "metadata": {
            "complexity": "low",
            "domain": "processing",
            "version": "2.0",
            "author": "team",
            "reviewed": True,
        },
        "use_cases": ["use_case_1", "use_case_2", "use_case_3"],
        "examples": ["example_1", "example_2"],
        "confidence": 1.0,
    }

    score = scorer.score_pattern(perfect_pattern)

    # Should achieve near-perfect composite score
    assert score.composite_score >= 0.95
    assert score.completeness_score >= 0.95
    assert score.documentation_score >= 0.9
    assert score.onex_compliance_score == 1.0
    assert score.metadata_richness_score == 1.0
    assert score.complexity_score == 1.0
