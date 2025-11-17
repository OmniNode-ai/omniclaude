"""
Pattern Quality Scorer - Evaluates and stores pattern quality metrics

Scoring Dimensions:
1. Code Completeness (0-1.0): Has meaningful code vs stubs
2. Documentation Quality (0-1.0): Docstrings, comments, type hints
3. ONEX Compliance (0-1.0): Follows ONEX architecture patterns
4. Metadata Richness (0-1.0): Use cases, examples, node types
5. Complexity Appropriateness (0-1.0): Complexity matches use case

Composite Score: Weighted average of dimensions
"""

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, List, Optional

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings
except ImportError:
    settings = None

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:
    psycopg2 = None


@dataclass
class PatternQualityScore:
    """Quality score for a code pattern across multiple dimensions."""

    pattern_id: str
    pattern_name: str
    composite_score: float  # 0.0-1.0
    completeness_score: float
    documentation_score: float
    onex_compliance_score: float
    metadata_richness_score: float
    complexity_score: float
    confidence: float  # from Archon Intelligence
    measurement_timestamp: datetime
    version: str = "1.0.0"


class PatternQualityScorer:
    """Evaluates pattern quality across multiple dimensions."""

    # Quality thresholds
    EXCELLENT_THRESHOLD = 0.9
    GOOD_THRESHOLD = 0.7
    FAIR_THRESHOLD = 0.5

    # Composite score weights
    WEIGHTS = {
        "completeness": 0.30,
        "documentation": 0.25,
        "onex_compliance": 0.20,
        "metadata_richness": 0.15,
        "complexity": 0.10,
    }

    def score_pattern(self, pattern: dict) -> PatternQualityScore:
        """
        Score a pattern across all quality dimensions.

        Args:
            pattern: Dictionary containing pattern data with fields:
                - pattern_id (str)
                - pattern_name (str)
                - code (str)
                - text (str)
                - metadata (Dict)
                - node_type (Optional[str])
                - use_cases (List)
                - examples (List)
                - confidence (float)

        Returns:
            PatternQualityScore object with dimension scores and composite
        """
        # Extract pattern fields
        pattern_id = pattern.get("pattern_id", "")
        pattern_name = pattern.get("pattern_name", "")
        code = pattern.get("code", "")
        text = pattern.get("text", "")
        metadata = pattern.get("metadata", {})
        node_type = pattern.get("node_type")
        use_cases = pattern.get("use_cases", [])
        examples = pattern.get("examples", [])
        confidence = pattern.get("confidence", 0.0)

        # Score all dimensions
        completeness_score = self._score_completeness(code, text)
        documentation_score = self._score_documentation(code, text)
        onex_compliance_score = self._score_onex_compliance(
            code, node_type, pattern_name
        )
        metadata_richness_score = self._score_metadata_richness(
            use_cases, examples, metadata
        )
        complexity_score = self._score_complexity(code, metadata.get("complexity"))

        # Calculate weighted composite score
        composite_score = (
            completeness_score * self.WEIGHTS["completeness"]
            + documentation_score * self.WEIGHTS["documentation"]
            + onex_compliance_score * self.WEIGHTS["onex_compliance"]
            + metadata_richness_score * self.WEIGHTS["metadata_richness"]
            + complexity_score * self.WEIGHTS["complexity"]
        )

        return PatternQualityScore(
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            composite_score=composite_score,
            completeness_score=completeness_score,
            documentation_score=documentation_score,
            onex_compliance_score=onex_compliance_score,
            metadata_richness_score=metadata_richness_score,
            complexity_score=complexity_score,
            confidence=confidence,
            measurement_timestamp=datetime.now(UTC),
        )

    def _score_completeness(self, code: str, text: str) -> float:
        """
        Score code completeness vs stub implementations.

        Penalties:
        - -0.2 per stub indicator (pass, TODO, NotImplemented, etc.)

        Bonuses:
        - +0.1 for having logic (if/for/while/async def/class)
        - +0.05 for imports
        - +min(0.15, line_count/100) for code length

        Args:
            code: Source code string
            text: Descriptive text

        Returns:
            Completeness score (0.0-1.0)
        """
        if not code:
            return 0.0

        base_score = 1.0

        # Detect stub indicators
        stub_indicators = [
            "pass",
            "TODO",
            "NotImplemented",
            "...",
            "raise NotImplementedError",
        ]
        for indicator in stub_indicators:
            if indicator in code:
                base_score -= 0.2

        # Bonus checks
        bonuses = 0.0

        # Has logic
        logic_patterns = ["if ", "for ", "while ", "async def ", "class "]
        if any(pattern in code for pattern in logic_patterns):
            bonuses += 0.1

        # Has imports
        if "import " in code:
            bonuses += 0.05

        # Line count bonus
        line_count = len(code.split("\n"))
        bonuses += min(0.15, line_count / 100)

        return min(1.0, max(0.0, base_score + bonuses))

    def _score_documentation(self, code: str, text: str) -> float:
        """
        Score documentation quality.

        Scoring:
        - +0.4 for docstrings (triple quotes)
        - +min(0.2, comment_lines/20) for inline comments
        - +0.2 for type hints
        - +0.2 for descriptive text (>100 chars)

        Args:
            code: Source code string
            text: Descriptive text

        Returns:
            Documentation score (0.0-1.0)
        """
        score = 0.0

        if not code and not text:
            return 0.0

        # Check for docstrings
        if '"""' in code or "'''" in code:
            score += 0.4

        # Count inline comments
        comment_lines = len([line for line in code.split("\n") if "#" in line])
        score += min(0.2, comment_lines / 20)

        # Check for type hints
        type_hint_pattern = r":\s*\w+|\s*->\s*\w+"
        if re.search(type_hint_pattern, code):
            score += 0.2

        # Check for descriptive text
        if len(text) > 100:
            score += 0.2

        return min(1.0, score)

    def _score_onex_compliance(
        self, code: str, node_type: str | None, pattern_name: str
    ) -> float:
        """
        Score ONEX architecture compliance.

        Scoring:
        - No node_type: 0.5 if pattern_name contains node type, else 0.3
        - Has node_type: base 0.7
        - +0.15 for proper naming (node_type in pattern_name)
        - +0.15 for ONEX method signatures

        Args:
            code: Source code string
            node_type: ONEX node type (effect/compute/reducer/orchestrator)
            pattern_name: Name of the pattern

        Returns:
            ONEX compliance score (0.0-1.0)
        """
        if not node_type:
            # Check if pattern_name suggests a node type
            onex_types = ["Effect", "Compute", "Reducer", "Orchestrator"]
            if any(otype in pattern_name for otype in onex_types):
                return 0.5
            return 0.3

        score = 0.7  # Base score for having node_type

        # Check proper naming
        if node_type.lower() in pattern_name.lower():
            score += 0.15

        # Check for ONEX method signatures
        method_signatures = {
            "effect": "async def execute_effect",
            "compute": "async def execute_compute",
            "reducer": "async def execute_reduction",
            "orchestrator": "async def execute_orchestration",
        }

        expected_signature = method_signatures.get(node_type.lower())
        if expected_signature and expected_signature in code:
            score += 0.15

        return min(1.0, score)

    def _score_metadata_richness(
        self, use_cases: list, examples: list, metadata: dict
    ) -> float:
        """
        Score metadata richness.

        Scoring:
        - +min(0.4, len(use_cases)/3 * 0.4) for use cases
        - +min(0.3, len(examples)/2 * 0.3) for examples
        - +0.3 for rich metadata (>3 fields)

        Args:
            use_cases: List of use case descriptions
            examples: List of example implementations
            metadata: Additional metadata dictionary

        Returns:
            Metadata richness score (0.0-1.0)
        """
        score = 0.0

        # Score use cases
        if use_cases:
            score += min(0.4, len(use_cases) / 3 * 0.4)

        # Score examples
        if examples:
            score += min(0.3, len(examples) / 2 * 0.3)

        # Score rich metadata
        if metadata and len(metadata) > 3:
            score += 0.3

        return min(1.0, score)

    def _score_complexity(self, code: str, declared_complexity: str | None) -> float:
        """
        Score complexity appropriateness.

        Determines actual complexity by counting cyclomatic indicators,
        then compares with declared complexity.

        Scoring:
        - 1.0 if declared matches actual
        - 0.6 if declared but mismatched
        - 0.4 if no declaration

        Args:
            code: Source code string
            declared_complexity: Declared complexity level (low/medium/high)

        Returns:
            Complexity score (0.0-1.0)
        """
        if not code:
            return 0.4

        # Count cyclomatic complexity indicators
        indicators = ["if ", "for ", "while ", "except "]
        indicator_count = sum(code.count(indicator) for indicator in indicators)

        # Determine actual complexity
        if indicator_count < 3:
            actual_complexity = "low"
        elif indicator_count < 8:
            actual_complexity = "medium"
        else:
            actual_complexity = "high"

        # Score based on declaration match
        if not declared_complexity:
            return 0.4

        if declared_complexity.lower() == actual_complexity:
            return 1.0

        return 0.6

    def _build_connection_string_from_env(self) -> str:
        """
        Build PostgreSQL connection string from environment variables.

        Uses production defaults that match Pydantic settings when available,
        or fallback to hardcoded defaults for backward compatibility.

        Returns:
            PostgreSQL connection string
        """
        # Prefer defaults from settings if available (type-safe)
        if settings:
            default_host = settings.postgres_host
            default_port = str(settings.postgres_port)
            default_database = settings.postgres_database
            default_user = settings.postgres_user
        else:
            # Fallback to hardcoded defaults for backward compatibility
            default_host = "192.168.86.200"
            default_port = "5436"
            default_database = "omninode_bridge"
            default_user = "postgres"

        host = os.getenv("POSTGRES_HOST", default_host)
        port = os.getenv("POSTGRES_PORT", default_port)
        database = os.getenv("POSTGRES_DATABASE", default_database)
        user = os.getenv("POSTGRES_USER", default_user)
        password = os.getenv("POSTGRES_PASSWORD", "")

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    def _store_quality_metrics_sync(
        self, score: PatternQualityScore, connection_string: str
    ) -> None:
        """
        Synchronous database operations for storing quality metrics.

        This method runs in a thread pool via asyncio.to_thread() to avoid
        blocking the event loop with synchronous psycopg2 operations.

        Args:
            score: PatternQualityScore object to store
            connection_string: PostgreSQL connection string

        Raises:
            ValueError: If pattern_id is not a valid UUID format
            Exception: Database connection or query errors
        """
        # Validate UUID format before database operation
        import uuid as uuid_module

        try:
            # Attempt to parse pattern_id as UUID to validate format
            uuid_module.UUID(score.pattern_id)
        except (ValueError, AttributeError, TypeError) as e:
            raise ValueError(
                f"Invalid UUID format for pattern_id: '{score.pattern_id}'. "
                f"Expected valid UUID string (e.g., '550e8400-e29b-41d4-a716-446655440000'). "
                f"Error: {e}"
            )

        conn = None
        try:
            conn = psycopg2.connect(connection_string)
            cursor = conn.cursor()

            # Prepare dimension scores as metadata JSON
            dimension_scores = {
                "completeness_score": score.completeness_score,
                "documentation_score": score.documentation_score,
                "onex_compliance_score": score.onex_compliance_score,
                "metadata_richness_score": score.metadata_richness_score,
                "complexity_score": score.complexity_score,
            }

            # Upsert query with ON CONFLICT on pattern_id
            # Uses UNIQUE constraint added in migration 014
            query = """
                INSERT INTO pattern_quality_metrics (
                    pattern_id,
                    quality_score,
                    confidence,
                    measurement_timestamp,
                    version,
                    metadata
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (pattern_id) DO UPDATE SET
                    quality_score = EXCLUDED.quality_score,
                    confidence = EXCLUDED.confidence,
                    measurement_timestamp = EXCLUDED.measurement_timestamp,
                    version = EXCLUDED.version,
                    metadata = EXCLUDED.metadata
            """

            # Pass pattern_id directly - psycopg2 handles string-to-UUID conversion
            cursor.execute(
                query,
                (
                    score.pattern_id,
                    score.composite_score,
                    score.confidence,
                    score.measurement_timestamp,
                    score.version,
                    Json(dimension_scores),
                ),
            )

            conn.commit()
            cursor.close()

        except psycopg2.errors.ForeignKeyViolation:
            # Defensive: FK constraint was removed in migration 013,
            # but keeping this handler for safety
            if conn:
                conn.rollback()
            return  # Skip if FK constraint is ever re-added
        except Exception as e:
            if conn:
                conn.rollback()
            raise Exception(f"Failed to store quality metrics: {e}")

        finally:
            if conn:
                conn.close()

    async def store_quality_metrics(
        self, score: PatternQualityScore, db_connection_string: str | None = None
    ) -> None:
        """
        Store quality metrics to pattern_quality_metrics table (async wrapper).

        Uses upsert (INSERT ... ON CONFLICT UPDATE) to handle duplicate pattern_ids.
        Requires UNIQUE constraint on pattern_id (added in migration 014).

        This method runs synchronous psycopg2 operations in a thread pool to avoid
        blocking the event loop. All callers can continue using await.

        Upsert Behavior:
        - If pattern_id doesn't exist: Creates new record
        - If pattern_id exists: Updates quality_score, confidence, timestamp, version, metadata

        Args:
            score: PatternQualityScore object to store
            db_connection_string: PostgreSQL connection string (defaults to env var)

        Raises:
            ImportError: If psycopg2 is not installed
            Exception: Database connection or query errors
        """
        if psycopg2 is None:
            raise ImportError("psycopg2 is required for database operations")

        # Get database connection string with production defaults
        if db_connection_string:
            connection_string = db_connection_string
        elif os.getenv("HOST_DATABASE_URL"):
            connection_string = os.getenv("HOST_DATABASE_URL")
        elif os.getenv("DATABASE_URL"):
            connection_string = os.getenv("DATABASE_URL")
        elif settings:
            # Use Pydantic settings to build production connection string
            try:
                connection_string = settings.get_postgres_dsn()
            except Exception:
                # Fall back to environment-based construction
                connection_string = self._build_connection_string_from_env()
        else:
            # Last resort: build from environment variables with production defaults
            connection_string = self._build_connection_string_from_env()

        # Run synchronous database operations in thread pool to avoid blocking event loop
        await asyncio.to_thread(
            self._store_quality_metrics_sync, score, connection_string
        )
