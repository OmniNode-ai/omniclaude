#!/usr/bin/env python3
"""
Comprehensive Unit Tests for Relevance Scoring Functionality

Tests RelevanceScorer's ability to:
- Score patterns based on keyword matching and heuristics
- Score database schemas based on table name matching
- Apply task-specific heuristics (DEBUG, IMPLEMENT, DATABASE)
- Filter and sort by relevance scores
"""

import pytest

from agents.lib.relevance_scorer import RelevanceScorer
from agents.lib.task_classifier import TaskContext, TaskIntent


class TestPatternRelevanceScoring:
    """Test suite for pattern relevance scoring."""

    def test_score_pattern_high_relevance(self):
        """Test pattern with keywords matching task context scores high."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "ONEX Effect Node Pattern",
            "description": "External API interaction with async error handling",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api", "async"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Create an Effect node for API calls",
        )

        # Should score high due to keyword matches + node type match
        assert score > 0.6, f"Expected high relevance (>0.6), got {score}"
        assert score <= 1.0

    def test_score_pattern_low_relevance(self):
        """Test pattern with no keyword matches scores low."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Database Migration Pattern",
            "description": "SQL schema evolution and data migration strategies",
            "node_types": ["REDUCER"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api", "async"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Create an Effect node for API calls",
        )

        # Should score low due to no keyword/node type matches
        assert score < 0.3, f"Expected low relevance (<0.3), got {score}"

    def test_score_pattern_node_type_matching(self):
        """Test pattern with matching node type gets heuristic boost."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "ONEX Effect Node Pattern",
            "description": "External API interaction",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=[],  # No keyword matches
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],  # Node type match
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Implement EFFECT node",
        )

        # Should have non-zero score due to node type heuristic (30% of 1.0 = 0.3) + entity matching
        assert score >= 0.3, f"Expected heuristic boost (>=0.3), got {score}"

    def test_score_pattern_partial_keyword_match(self):
        """Test pattern with partial keyword matches."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Error Handling Pattern",
            "description": "Async error handling and retry logic",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["error", "handling", "database"],  # 2 of 3 match
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.7,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Implement error handling",
        )

        # Should have medium score due to partial matches
        assert 0.3 <= score <= 0.7, f"Expected medium relevance (0.3-0.7), got {score}"


class TestSchemaRelevanceScoring:
    """Test suite for database schema relevance scoring."""

    def test_score_schema_direct_table_match(self):
        """Test schema with table name in prompt scores very high."""
        scorer = RelevanceScorer()

        schema = {
            "table_name": "agent_routing_decisions",
            "columns": ["id", "agent_name", "confidence"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["query", "table"],
            entities=["agent_routing_decisions"],
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.9,
        )

        score = scorer.score_schema_relevance(
            schema=schema,
            task_context=task_context,
            user_prompt="Query the agent_routing_decisions table",
        )

        # Should score at or near maximum due to direct table name match
        assert score >= 1.0, f"Expected maximum relevance (1.0), got {score}"

    def test_score_schema_keyword_match(self):
        """Test schema with keywords in table name scores medium."""
        scorer = RelevanceScorer()

        schema = {
            "table_name": "workflow_events",
            "columns": ["id", "workflow_id", "event_type"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["workflow", "event"],
            entities=[],
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.8,
        )

        score = scorer.score_schema_relevance(
            schema=schema,
            task_context=task_context,
            user_prompt="Find workflow event data",
        )

        # Should have medium score due to keyword matches (0.3 per keyword)
        assert 0.3 <= score <= 1.0, f"Expected medium relevance (0.3-1.0), got {score}"

    def test_score_schema_no_match(self):
        """Test schema with no relation to task scores low."""
        scorer = RelevanceScorer()

        schema = {
            "table_name": "user_preferences",
            "columns": ["id", "user_id", "theme"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["agent", "routing", "decision"],
            entities=["agent_routing_decisions"],
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.8,
        )

        score = scorer.score_schema_relevance(
            schema=schema,
            task_context=task_context,
            user_prompt="Query agent routing decisions",
        )

        # Should score very low or zero
        assert score <= 0.2, f"Expected low relevance (<=0.2), got {score}"

    def test_score_schema_entity_match(self):
        """Test schema with table name in entities list scores high."""
        scorer = RelevanceScorer()

        schema = {
            "table_name": "manifest_injections",
            "columns": ["id", "correlation_id", "query_time_ms"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["query"],
            entities=["manifest_injections"],  # Table name as entity
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.8,
        )

        score = scorer.score_schema_relevance(
            schema=schema,
            task_context=task_context,
            user_prompt="Check manifest_injections table",
        )

        # Should have high score due to entity match (0.5) + direct match (1.0)
        assert score >= 0.5, f"Expected high relevance (>=0.5), got {score}"


class TestFilteringAndSorting:
    """Test suite for filtering and sorting patterns by relevance."""

    def test_filtering_threshold(self):
        """Test filtering patterns by relevance threshold."""
        scorer = RelevanceScorer()

        patterns = [
            {
                "name": "High Relevance Pattern",
                "description": "Effect node API async error handling",
                "node_types": ["EFFECT"],
            },
            {
                "name": "Medium Relevance Pattern",
                "description": "Effect node implementation",
                "node_types": ["EFFECT"],
            },
            {
                "name": "Low Relevance Pattern",
                "description": "Database migration strategies",
                "node_types": ["REDUCER"],
            },
        ]

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api", "async", "error"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )

        # Score all patterns
        scored_patterns = []
        for pattern in patterns:
            score = scorer.score_pattern_relevance(
                pattern=pattern,
                task_context=task_context,
                user_prompt="Create Effect node for API with error handling",
            )
            scored_patterns.append((pattern, score))

        # Filter by threshold > 0.3
        threshold = 0.3
        filtered = [p for p, s in scored_patterns if s > threshold]

        # Should filter out low relevance pattern
        assert len(filtered) < len(patterns), "Expected some patterns to be filtered"
        assert len(filtered) >= 1, "Expected at least one pattern to pass threshold"

        # Verify low relevance pattern was filtered
        low_relevance_names = [p["name"] for p in filtered]
        assert "Low Relevance Pattern" not in low_relevance_names

    def test_top_n_sorting(self):
        """Test sorting patterns by score and taking top N."""
        scorer = RelevanceScorer()

        patterns = [
            {
                "name": "Pattern A",
                "description": "Effect node API",
                "node_types": ["EFFECT"],
            },
            {
                "name": "Pattern B",
                "description": "Effect node API async error",
                "node_types": ["EFFECT"],
            },
            {
                "name": "Pattern C",
                "description": "Compute node data",
                "node_types": ["COMPUTE"],
            },
            {
                "name": "Pattern D",
                "description": "Effect node implementation",
                "node_types": ["EFFECT"],
            },
        ]

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api", "async", "error"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )

        # Score all patterns
        scored_patterns = []
        for pattern in patterns:
            score = scorer.score_pattern_relevance(
                pattern=pattern,
                task_context=task_context,
                user_prompt="Create Effect node for async API with error handling",
            )
            scored_patterns.append((pattern, score))

        # Sort by score descending
        sorted_patterns = sorted(scored_patterns, key=lambda x: x[1], reverse=True)

        # Take top 2
        top_2 = sorted_patterns[:2]

        assert len(top_2) == 2
        # Scores should be in descending order
        assert top_2[0][1] >= top_2[1][1]

        # Pattern B should be highest (most keyword matches)
        assert top_2[0][0]["name"] == "Pattern B"


class TestTaskSpecificHeuristics:
    """Test suite for task-specific heuristic scoring."""

    def test_debug_task_heuristics(self):
        """Test DEBUG task boosts error-related patterns."""
        scorer = RelevanceScorer()

        error_pattern = {
            "name": "Error Handling and Debugging Pattern",
            "description": "Exception handling and debug logging",
            "node_types": ["EFFECT"],
        }

        normal_pattern = {
            "name": "Standard Effect Pattern",
            "description": "Basic external API interaction",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DEBUG,
            keywords=["fix", "error"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.7,
        )

        error_score = scorer.score_pattern_relevance(
            pattern=error_pattern,
            task_context=task_context,
            user_prompt="Fix error in Effect node",
        )

        normal_score = scorer.score_pattern_relevance(
            pattern=normal_pattern,
            task_context=task_context,
            user_prompt="Fix error in Effect node",
        )

        # Error pattern should score higher due to heuristic boost
        assert (
            error_score > normal_score
        ), f"Error pattern ({error_score}) should score higher than normal pattern ({normal_score})"

    def test_debug_task_exception_heuristic(self):
        """Test DEBUG task boosts exception-related patterns."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Exception Handling Pattern",
            "description": "Comprehensive exception management",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DEBUG,
            keywords=["troubleshoot"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.7,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Troubleshoot the system",
        )

        # Should get heuristic boost for "exception" keyword (30% of 0.5 = 0.15)
        assert score >= 0.15, f"Expected heuristic boost (>=0.15), got {score}"

    def test_implement_task_heuristics(self):
        """Test IMPLEMENT task boosts patterns with matching node types."""
        scorer = RelevanceScorer()

        effect_pattern = {
            "name": "Effect Node Pattern",
            "description": "External API interaction",
            "node_types": ["EFFECT"],
        }

        compute_pattern = {
            "name": "Compute Node Pattern",
            "description": "Data transformation logic",
            "node_types": ["COMPUTE"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["node"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],  # User wants EFFECT node
            confidence=0.8,
        )

        effect_score = scorer.score_pattern_relevance(
            pattern=effect_pattern,
            task_context=task_context,
            user_prompt="Implement an EFFECT node",
        )

        compute_score = scorer.score_pattern_relevance(
            pattern=compute_pattern,
            task_context=task_context,
            user_prompt="Implement an EFFECT node",
        )

        # Effect pattern should score higher due to node type match
        assert (
            effect_score > compute_score
        ), f"Effect pattern ({effect_score}) should score higher than Compute pattern ({compute_score})"

    def test_database_task_heuristics(self):
        """Test DATABASE task boosts database-related patterns."""
        scorer = RelevanceScorer()

        db_pattern = {
            "name": "Database Query Pattern",
            "description": "SQL query optimization and schema design",
            "node_types": ["REDUCER"],
        }

        api_pattern = {
            "name": "API Integration Pattern",
            "description": "REST API client implementation",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["query", "table"],
            entities=[],
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.8,
        )

        db_score = scorer.score_pattern_relevance(
            pattern=db_pattern,
            task_context=task_context,
            user_prompt="Optimize database query",
        )

        api_score = scorer.score_pattern_relevance(
            pattern=api_pattern,
            task_context=task_context,
            user_prompt="Optimize database query",
        )

        # Database pattern should score higher due to heuristic boost
        assert (
            db_score > api_score
        ), f"DB pattern ({db_score}) should score higher than API pattern ({api_score})"


class TestKeywordMatching:
    """Test suite for keyword matching logic."""

    def test_keyword_match_calculation(self):
        """Test keyword match score calculation."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Effect Node Pattern",
            "description": "API async error handling",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["api", "async", "error"],  # All 3 match
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Create API with async error handling",
        )

        # With 3/3 keywords matching, keyword score = 1.0
        # Total = 1.0 * 0.5 (keyword weight) + entity matching
        assert score >= 0.5, f"Expected high keyword match score, got {score}"

    def test_no_keywords_low_score(self):
        """Test pattern with no keywords scores low without heuristics."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Pattern Name",
            "description": "Pattern description",
            "node_types": [],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=[],  # No keywords to match
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.5,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Do something",
        )

        # Should score 0.0 (no keywords, no heuristics)
        assert score == 0.0, f"Expected zero score, got {score}"


class TestEdgeCases:
    """Test suite for edge cases and boundary conditions."""

    def test_empty_pattern_fields(self):
        """Test pattern with empty/missing fields."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "",
            "description": "",
            "node_types": [],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["test"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.5,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Test prompt",
        )

        # Should handle gracefully and return low score
        assert 0.0 <= score <= 1.0
        assert score < 0.1

    def test_score_capped_at_one(self):
        """Test that scores are capped at 1.0."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Effect node API async error handling debug logging exception",
            "description": "Effect node API async error handling debug logging exception",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DEBUG,
            keywords=["effect", "node", "api", "async", "error", "debug", "exception"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=1.0,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Debug effect node with API async error handling",
        )

        # Score should be capped at 1.0
        assert score <= 1.0, f"Score should be capped at 1.0, got {score}"

    def test_case_insensitive_matching(self):
        """Test that keyword matching is case-insensitive."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "EFFECT NODE PATTERN",
            "description": "API INTEGRATION",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api"],  # Lowercase keywords
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Implement effect node for API",
        )

        # Should match despite case differences
        assert score > 0.6, f"Expected case-insensitive match, got {score}"

    def test_multiple_node_types_match(self):
        """Test pattern with multiple node types matches any mentioned type."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Multi-Node Pattern",
            "description": "Combines Effect and Compute nodes",
            "node_types": ["EFFECT", "COMPUTE", "REDUCER"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=[],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["COMPUTE"],  # Match one of multiple
            confidence=0.8,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Implement Compute node",
        )

        # Should get heuristic boost for matching one node type (30% of 1.0 = 0.3) + entity matching
        assert score >= 0.3, f"Expected node type match boost, got {score}"


class TestRealWorldScenarios:
    """Test suite with realistic scoring scenarios."""

    def test_realistic_high_relevance_scenario(self):
        """Test realistic scenario with high relevance."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Async Effect Node with Error Handling",
            "description": "External API calls with async/await, retry logic, and comprehensive error handling",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["effect", "api", "async", "error", "retry"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["EFFECT"],
            confidence=0.9,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="I need to implement an Effect node that makes async API calls with retry logic and error handling",
        )

        # Should score very high (keyword match + node type match)
        assert score >= 0.8, f"Expected very high relevance (>=0.8), got {score}"

    def test_realistic_medium_relevance_scenario(self):
        """Test realistic scenario with medium relevance."""
        scorer = RelevanceScorer()

        pattern = {
            "name": "Basic Effect Node Pattern",
            "description": "Simple external API interaction",
            "node_types": ["EFFECT"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["compute", "transformation", "data"],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=["COMPUTE"],
            confidence=0.7,
        )

        score = scorer.score_pattern_relevance(
            pattern=pattern,
            task_context=task_context,
            user_prompt="Implement data transformation logic",
        )

        # Should have medium/low score (no keyword or node type match)
        assert score < 0.5, f"Expected medium/low relevance (<0.5), got {score}"

    def test_realistic_schema_scenario(self):
        """Test realistic database schema scoring scenario."""
        scorer = RelevanceScorer()

        schema = {
            "table_name": "agent_routing_decisions",
            "columns": ["id", "agent_name", "confidence", "correlation_id"],
        }

        task_context = TaskContext(
            primary_intent=TaskIntent.DATABASE,
            keywords=["agent", "routing", "decisions"],
            entities=["agent_routing_decisions"],
            mentioned_services=["postgresql"],
            mentioned_node_types=[],
            confidence=0.9,
        )

        score = scorer.score_schema_relevance(
            schema=schema,
            task_context=task_context,
            user_prompt="Show me data from the agent_routing_decisions table",
        )

        # Should score maximum (direct table match + keywords + entity)
        assert score >= 1.0, f"Expected maximum relevance (1.0), got {score}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
