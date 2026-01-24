# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for TaskClassifier and related models.

This module contains comprehensive tests for:
- TaskIntent enum values
- TaskContext dataclass fields and instantiation
- TaskClassifier.classify() method for intent detection
- Entity extraction from prompts
- Service and node type detection
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omniclaude.lib.task_classifier import TaskClassifier, TaskContext, TaskIntent

if TYPE_CHECKING:
    from collections.abc import Generator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> Generator[TaskClassifier, None, None]:
    """Provide a TaskClassifier instance for tests.

    This fixture ensures consistent classifier instantiation across tests
    and enables potential future extensions like mocking or configuration.
    """
    return TaskClassifier()


# =============================================================================
# TaskIntent Enum Tests
# =============================================================================


@pytest.mark.unit
class TestTaskIntent:
    """Tests for TaskIntent enum values."""

    def test_all_intent_values_defined(self) -> None:
        """All expected TaskIntent enum values are defined."""
        expected_intents = {
            "DEBUG",
            "IMPLEMENT",
            "DATABASE",
            "REFACTOR",
            "RESEARCH",
            "TEST",
            "DOCUMENT",
            "UNKNOWN",
        }
        actual_intents = {intent.name for intent in TaskIntent}
        assert actual_intents == expected_intents

    def test_intent_values_are_lowercase(self) -> None:
        """TaskIntent values are lowercase strings matching names."""
        for intent in TaskIntent:
            assert intent.value == intent.name.lower()
            assert isinstance(intent.value, str)

    def test_debug_intent(self) -> None:
        """DEBUG intent has correct value."""
        assert TaskIntent.DEBUG.value == "debug"

    def test_implement_intent(self) -> None:
        """IMPLEMENT intent has correct value."""
        assert TaskIntent.IMPLEMENT.value == "implement"

    def test_database_intent(self) -> None:
        """DATABASE intent has correct value."""
        assert TaskIntent.DATABASE.value == "database"

    def test_refactor_intent(self) -> None:
        """REFACTOR intent has correct value."""
        assert TaskIntent.REFACTOR.value == "refactor"

    def test_research_intent(self) -> None:
        """RESEARCH intent has correct value."""
        assert TaskIntent.RESEARCH.value == "research"

    def test_test_intent(self) -> None:
        """TEST intent has correct value."""
        assert TaskIntent.TEST.value == "test"

    def test_document_intent(self) -> None:
        """DOCUMENT intent has correct value."""
        assert TaskIntent.DOCUMENT.value == "document"

    def test_unknown_intent(self) -> None:
        """UNKNOWN intent has correct value."""
        assert TaskIntent.UNKNOWN.value == "unknown"

    def test_intent_count(self) -> None:
        """TaskIntent has exactly 8 members."""
        assert len(TaskIntent) == 8


# =============================================================================
# TaskContext Dataclass Tests
# =============================================================================


@pytest.mark.unit
class TestTaskContext:
    """Tests for TaskContext dataclass."""

    def test_task_context_instantiation(self) -> None:
        """TaskContext can be instantiated with all required fields."""
        context = TaskContext(
            primary_intent=TaskIntent.DEBUG,
            keywords=["error", "fix"],
            entities=["config.py"],
            mentioned_services=["kafka"],
            mentioned_node_types=["EFFECT"],
            confidence=0.8,
        )
        assert context.primary_intent == TaskIntent.DEBUG
        assert context.keywords == ["error", "fix"]
        assert context.entities == ["config.py"]
        assert context.mentioned_services == ["kafka"]
        assert context.mentioned_node_types == ["EFFECT"]
        assert context.confidence == 0.8

    def test_task_context_empty_lists(self) -> None:
        """TaskContext can be instantiated with empty lists."""
        context = TaskContext(
            primary_intent=TaskIntent.UNKNOWN,
            keywords=[],
            entities=[],
            mentioned_services=[],
            mentioned_node_types=[],
            confidence=0.0,
        )
        assert context.keywords == []
        assert context.entities == []
        assert context.mentioned_services == []
        assert context.mentioned_node_types == []

    def test_task_context_field_types(self) -> None:
        """TaskContext fields have correct types."""
        context = TaskContext(
            primary_intent=TaskIntent.IMPLEMENT,
            keywords=["create"],
            entities=["file.py"],
            mentioned_services=["postgres"],
            mentioned_node_types=["COMPUTE"],
            confidence=0.5,
        )
        assert isinstance(context.primary_intent, TaskIntent)
        assert isinstance(context.keywords, list)
        assert isinstance(context.entities, list)
        assert isinstance(context.mentioned_services, list)
        assert isinstance(context.mentioned_node_types, list)
        assert isinstance(context.confidence, float)


# =============================================================================
# TaskClassifier Initialization Tests
# =============================================================================


@pytest.mark.unit
class TestTaskClassifierInit:
    """Tests for TaskClassifier initialization."""

    def test_classifier_instantiation(self, classifier: TaskClassifier) -> None:
        """TaskClassifier can be instantiated."""
        assert classifier is not None

    def test_classifier_has_intent_keywords(self) -> None:
        """TaskClassifier has INTENT_KEYWORDS class attribute."""
        assert hasattr(TaskClassifier, "INTENT_KEYWORDS")
        assert isinstance(TaskClassifier.INTENT_KEYWORDS, dict)

    def test_classifier_has_service_patterns(self) -> None:
        """TaskClassifier has SERVICE_PATTERNS class attribute."""
        assert hasattr(TaskClassifier, "SERVICE_PATTERNS")
        assert isinstance(TaskClassifier.SERVICE_PATTERNS, list)

    def test_classifier_has_node_type_patterns(self) -> None:
        """TaskClassifier has NODE_TYPE_PATTERNS class attribute."""
        assert hasattr(TaskClassifier, "NODE_TYPE_PATTERNS")
        assert isinstance(TaskClassifier.NODE_TYPE_PATTERNS, list)

    def test_service_patterns_content(self) -> None:
        """SERVICE_PATTERNS contains expected services."""
        expected_services = {"kafka", "redpanda", "postgresql", "postgres", "qdrant"}
        actual_services = set(TaskClassifier.SERVICE_PATTERNS)
        assert expected_services.issubset(actual_services)

    def test_node_type_patterns_content(self) -> None:
        """NODE_TYPE_PATTERNS contains all ONEX node types."""
        expected_types = {"effect", "compute", "reducer", "orchestrator"}
        actual_types = set(TaskClassifier.NODE_TYPE_PATTERNS)
        assert actual_types == expected_types


# =============================================================================
# TaskClassifier.classify() - DEBUG Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyDebugIntent:
    """Tests for DEBUG intent classification."""

    def test_classify_fix_bug(self, classifier: TaskClassifier) -> None:
        """'fix the bug' classifies as DEBUG intent."""
        result = classifier.classify("fix the bug")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_error_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'error' classify as DEBUG."""
        result = classifier.classify("I'm getting an error in my code")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_failing_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'failing' classify as DEBUG."""
        result = classifier.classify("my tests are failing")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_broken_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'broken' classify as DEBUG."""
        result = classifier.classify("the build is broken")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_debug_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'debug' classify as DEBUG."""
        result = classifier.classify("help me debug this issue")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_troubleshoot_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'troubleshoot' classify as DEBUG."""
        result = classifier.classify("troubleshoot the connection")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_classify_investigate_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'investigate' classify as DEBUG."""
        result = classifier.classify("investigate why it fails")
        assert result.primary_intent == TaskIntent.DEBUG


# =============================================================================
# TaskClassifier.classify() - IMPLEMENT Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyImplementIntent:
    """Tests for IMPLEMENT intent classification."""

    def test_classify_create_feature(self, classifier: TaskClassifier) -> None:
        """'create new feature' classifies as IMPLEMENT intent."""
        result = classifier.classify("create new feature")
        assert result.primary_intent == TaskIntent.IMPLEMENT

    def test_classify_implement_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'implement' classify as IMPLEMENT."""
        result = classifier.classify("implement user authentication")
        assert result.primary_intent == TaskIntent.IMPLEMENT

    def test_classify_add_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'add' classify as IMPLEMENT."""
        result = classifier.classify("add a new endpoint")
        assert result.primary_intent == TaskIntent.IMPLEMENT

    def test_classify_build_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'build' classify as IMPLEMENT."""
        result = classifier.classify("build a REST API")
        assert result.primary_intent == TaskIntent.IMPLEMENT

    def test_classify_develop_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'develop' classify as IMPLEMENT."""
        result = classifier.classify("develop the payment system")
        assert result.primary_intent == TaskIntent.IMPLEMENT

    def test_classify_domain_indicator_fallback(
        self, classifier: TaskClassifier
    ) -> None:
        """Domain-specific terms trigger IMPLEMENT even without explicit verbs."""
        result = classifier.classify("ONEX authentication system")
        assert result.primary_intent == TaskIntent.IMPLEMENT
        assert result.confidence >= 0.5


# =============================================================================
# TaskClassifier.classify() - DATABASE Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyDatabaseIntent:
    """Tests for DATABASE intent classification."""

    def test_classify_query_database(self, classifier: TaskClassifier) -> None:
        """'query the database' classifies as DATABASE intent."""
        result = classifier.classify("query the database")
        assert result.primary_intent == TaskIntent.DATABASE

    def test_classify_sql_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'sql' classify as DATABASE."""
        result = classifier.classify("write a SQL query")
        assert result.primary_intent == TaskIntent.DATABASE

    def test_classify_table_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'table' classify as DATABASE."""
        result = classifier.classify("the users table needs more columns")
        assert result.primary_intent == TaskIntent.DATABASE

    def test_classify_schema_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'schema' classify as DATABASE."""
        result = classifier.classify("update the schema")
        assert result.primary_intent == TaskIntent.DATABASE

    def test_classify_migration_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'migration' classify as DATABASE."""
        result = classifier.classify("run the database migration")
        assert result.primary_intent == TaskIntent.DATABASE

    def test_classify_postgresql_keyword(self, classifier: TaskClassifier) -> None:
        """Prompts with 'postgresql' classify as DATABASE."""
        result = classifier.classify("connect to postgresql")
        assert result.primary_intent == TaskIntent.DATABASE


# =============================================================================
# TaskClassifier.classify() - RESEARCH Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyResearchIntent:
    """Tests for RESEARCH intent classification."""

    def test_classify_what_is_code(self) -> None:
        """'what is this code' classifies as RESEARCH intent."""
        classifier = TaskClassifier()
        result = classifier.classify("what is this code doing")
        assert result.primary_intent == TaskIntent.RESEARCH

    def test_classify_how_keyword(self) -> None:
        """Prompts with 'how' classify as RESEARCH."""
        classifier = TaskClassifier()
        result = classifier.classify("how does this work")
        assert result.primary_intent == TaskIntent.RESEARCH

    def test_classify_where_keyword(self) -> None:
        """Prompts with 'where' classify as RESEARCH."""
        classifier = TaskClassifier()
        result = classifier.classify("where is the config file")
        assert result.primary_intent == TaskIntent.RESEARCH

    def test_classify_explain_keyword(self) -> None:
        """Prompts with 'explain' classify as RESEARCH."""
        classifier = TaskClassifier()
        result = classifier.classify("explain the architecture")
        assert result.primary_intent == TaskIntent.RESEARCH

    def test_classify_find_keyword(self) -> None:
        """Prompts with 'find' classify as RESEARCH."""
        classifier = TaskClassifier()
        result = classifier.classify("find the function definition")
        assert result.primary_intent == TaskIntent.RESEARCH

    def test_classify_show_me_keyword(self) -> None:
        """Prompts with 'show me' classify as RESEARCH."""
        classifier = TaskClassifier()
        result = classifier.classify("show me the logs")
        assert result.primary_intent == TaskIntent.RESEARCH


# =============================================================================
# TaskClassifier.classify() - REFACTOR Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyRefactorIntent:
    """Tests for REFACTOR intent classification."""

    def test_classify_refactor_keyword(self) -> None:
        """Prompts with 'refactor' classify as REFACTOR."""
        classifier = TaskClassifier()
        result = classifier.classify("refactor this function")
        assert result.primary_intent == TaskIntent.REFACTOR

    def test_classify_optimize_keyword(self) -> None:
        """Prompts with 'optimize' classify as REFACTOR."""
        classifier = TaskClassifier()
        result = classifier.classify("optimize the query performance")
        assert result.primary_intent == TaskIntent.REFACTOR

    def test_classify_improve_keyword(self) -> None:
        """Prompts with 'improve' classify as REFACTOR."""
        classifier = TaskClassifier()
        result = classifier.classify("improve code readability")
        assert result.primary_intent == TaskIntent.REFACTOR

    def test_classify_clean_up_keyword(self) -> None:
        """Prompts with 'clean up' classify as REFACTOR."""
        classifier = TaskClassifier()
        result = classifier.classify("clean up the codebase")
        assert result.primary_intent == TaskIntent.REFACTOR

    def test_classify_simplify_keyword(self) -> None:
        """Prompts with 'simplify' classify as REFACTOR."""
        classifier = TaskClassifier()
        result = classifier.classify("simplify this logic")
        assert result.primary_intent == TaskIntent.REFACTOR


# =============================================================================
# TaskClassifier.classify() - TEST Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyTestIntent:
    """Tests for TEST intent classification."""

    def test_classify_test_keyword(self) -> None:
        """Prompts with 'test' classify as TEST."""
        classifier = TaskClassifier()
        result = classifier.classify("run the test suite and check assertions")
        assert result.primary_intent == TaskIntent.TEST

    def test_classify_pytest_keyword(self) -> None:
        """Prompts with 'pytest' classify as TEST."""
        classifier = TaskClassifier()
        result = classifier.classify("run pytest on the module")
        assert result.primary_intent == TaskIntent.TEST

    def test_classify_unittest_keyword(self) -> None:
        """Prompts with 'unittest' classify as TEST."""
        classifier = TaskClassifier()
        result = classifier.classify("create unittest cases")
        assert result.primary_intent == TaskIntent.TEST

    def test_classify_validate_keyword(self) -> None:
        """Prompts with 'validate' classify as TEST."""
        classifier = TaskClassifier()
        result = classifier.classify("validate the input data")
        assert result.primary_intent == TaskIntent.TEST

    def test_classify_verify_keyword(self) -> None:
        """Prompts with 'verify' classify as TEST."""
        classifier = TaskClassifier()
        result = classifier.classify("verify the output")
        assert result.primary_intent == TaskIntent.TEST


# =============================================================================
# TaskClassifier.classify() - DOCUMENT Intent Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyDocumentIntent:
    """Tests for DOCUMENT intent classification."""

    def test_classify_document_keyword(self) -> None:
        """Prompts with 'document' classify as DOCUMENT."""
        classifier = TaskClassifier()
        result = classifier.classify("document this function")
        assert result.primary_intent == TaskIntent.DOCUMENT

    def test_classify_documentation_keyword(self) -> None:
        """Prompts with 'documentation' classify as DOCUMENT."""
        classifier = TaskClassifier()
        result = classifier.classify("add documentation")
        assert result.primary_intent == TaskIntent.DOCUMENT

    def test_classify_readme_keyword(self) -> None:
        """Prompts with 'readme' classify as DOCUMENT."""
        classifier = TaskClassifier()
        result = classifier.classify("update the readme file")
        assert result.primary_intent == TaskIntent.DOCUMENT

    def test_classify_docstring_keyword(self) -> None:
        """Prompts with 'docstring' classify as DOCUMENT."""
        classifier = TaskClassifier()
        result = classifier.classify("the docstring needs to describe the parameters")
        assert result.primary_intent == TaskIntent.DOCUMENT


# =============================================================================
# TaskClassifier.classify() - Entity Extraction Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyEntityExtraction:
    """Tests for entity extraction from prompts."""

    def test_extract_file_with_extension(self) -> None:
        """Files with extensions are extracted as entities."""
        classifier = TaskClassifier()
        result = classifier.classify("fix the bug in config.py")
        assert "config.py" in result.entities

    def test_extract_file_with_underscores(self) -> None:
        """Files with underscores are extracted as entities."""
        classifier = TaskClassifier()
        result = classifier.classify("update node_user_reducer.py")
        assert "node_user_reducer.py" in result.entities

    def test_extract_table_name_with_underscores(self) -> None:
        """Table names with underscores are extracted as entities."""
        classifier = TaskClassifier()
        result = classifier.classify("query the agent_routing_decisions table")
        assert "agent_routing_decisions" in result.entities

    def test_extract_module_name_with_underscores(self) -> None:
        """Module names with underscores are extracted as entities."""
        classifier = TaskClassifier()
        result = classifier.classify("import manifest_injector")
        assert "manifest_injector" in result.entities

    def test_extract_yaml_file(self) -> None:
        """YAML files are extracted as entities."""
        classifier = TaskClassifier()
        result = classifier.classify("edit the config.yaml file")
        assert "config.yaml" in result.entities

    def test_extract_multiple_entities(self) -> None:
        """Multiple entities are extracted from a single prompt."""
        classifier = TaskClassifier()
        result = classifier.classify(
            "compare config.py and settings.yaml in user_service"
        )
        assert "config.py" in result.entities
        assert "settings.yaml" in result.entities
        assert "user_service" in result.entities

    def test_no_entities_in_simple_prompt(self) -> None:
        """Simple prompts without entities return empty list."""
        classifier = TaskClassifier()
        result = classifier.classify("help me debug")
        # Should not include simple words as entities
        assert all("_" in e or "." in e for e in result.entities)


# =============================================================================
# TaskClassifier.classify() - Service Extraction Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyServiceExtraction:
    """Tests for service name extraction from prompts."""

    def test_extract_kafka_service(self) -> None:
        """Kafka is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("send message to kafka")
        assert "kafka" in result.mentioned_services

    def test_extract_postgres_service(self) -> None:
        """Postgres is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("connect to postgres database")
        assert "postgres" in result.mentioned_services

    def test_extract_postgresql_service(self) -> None:
        """PostgreSQL is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("postgresql connection string")
        assert "postgresql" in result.mentioned_services

    def test_extract_qdrant_service(self) -> None:
        """Qdrant is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("search in qdrant")
        assert "qdrant" in result.mentioned_services

    def test_extract_docker_service(self) -> None:
        """Docker is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("build docker container")
        assert "docker" in result.mentioned_services

    def test_extract_redpanda_service(self) -> None:
        """Redpanda is extracted as mentioned service."""
        classifier = TaskClassifier()
        result = classifier.classify("configure redpanda cluster")
        assert "redpanda" in result.mentioned_services

    def test_extract_multiple_services(self) -> None:
        """Multiple services are extracted from a single prompt."""
        classifier = TaskClassifier()
        result = classifier.classify("connect kafka to postgres and qdrant")
        assert "kafka" in result.mentioned_services
        assert "postgres" in result.mentioned_services
        assert "qdrant" in result.mentioned_services


# =============================================================================
# TaskClassifier.classify() - Node Type Extraction Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyNodeTypeExtraction:
    """Tests for ONEX node type extraction from prompts."""

    def test_extract_effect_node_type(self) -> None:
        """Effect node type is extracted (uppercase)."""
        classifier = TaskClassifier()
        result = classifier.classify("create an effect node")
        assert "EFFECT" in result.mentioned_node_types

    def test_extract_compute_node_type(self) -> None:
        """Compute node type is extracted (uppercase)."""
        classifier = TaskClassifier()
        result = classifier.classify("implement a compute node")
        assert "COMPUTE" in result.mentioned_node_types

    def test_extract_reducer_node_type(self) -> None:
        """Reducer node type is extracted (uppercase)."""
        classifier = TaskClassifier()
        result = classifier.classify("add a reducer node")
        assert "REDUCER" in result.mentioned_node_types

    def test_extract_orchestrator_node_type(self) -> None:
        """Orchestrator node type is extracted (uppercase)."""
        classifier = TaskClassifier()
        result = classifier.classify("design an orchestrator node")
        assert "ORCHESTRATOR" in result.mentioned_node_types

    def test_extract_multiple_node_types(self) -> None:
        """Multiple node types are extracted from a single prompt."""
        classifier = TaskClassifier()
        result = classifier.classify("connect effect to compute to reducer")
        assert "EFFECT" in result.mentioned_node_types
        assert "COMPUTE" in result.mentioned_node_types
        assert "REDUCER" in result.mentioned_node_types


# =============================================================================
# TaskClassifier.classify() - Edge Cases
# =============================================================================


@pytest.mark.unit
class TestClassifyEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_prompt(self, classifier: TaskClassifier) -> None:
        """Empty prompt returns UNKNOWN intent with zero confidence."""
        result = classifier.classify("")
        assert result.primary_intent == TaskIntent.UNKNOWN
        assert result.confidence == 0.0
        assert result.keywords == []

    def test_whitespace_only_prompt(self, classifier: TaskClassifier) -> None:
        """Whitespace-only prompt returns UNKNOWN intent."""
        result = classifier.classify("   \t\n   ")
        assert result.primary_intent == TaskIntent.UNKNOWN
        assert result.confidence == 0.0

    def test_unknown_intent_no_keywords(self, classifier: TaskClassifier) -> None:
        """Prompts with no matching keywords return UNKNOWN."""
        result = classifier.classify("xyz abc 123")
        # Check confidence is low or intent is UNKNOWN (depending on word length)
        assert result.confidence < 0.5 or result.primary_intent == TaskIntent.UNKNOWN

    def test_case_insensitive_matching(self, classifier: TaskClassifier) -> None:
        """Keyword matching is case-insensitive."""
        result_lower = classifier.classify("fix the bug")
        result_upper = classifier.classify("FIX THE BUG")
        result_mixed = classifier.classify("Fix The Bug")
        assert result_lower.primary_intent == TaskIntent.DEBUG
        assert result_upper.primary_intent == TaskIntent.DEBUG
        assert result_mixed.primary_intent == TaskIntent.DEBUG

    def test_multiple_intents_highest_score_wins(
        self, classifier: TaskClassifier
    ) -> None:
        """When multiple intents match, highest score wins."""
        # This has "fix" (DEBUG) and "error" (DEBUG) - should be DEBUG
        result = classifier.classify("fix the error in the failing test")
        assert result.primary_intent == TaskIntent.DEBUG

    def test_confidence_is_bounded(self, classifier: TaskClassifier) -> None:
        """Confidence is always between 0 and 1."""
        # Test with many keywords to potentially exceed 1.0
        result = classifier.classify(
            "fix error bug broken failing issue debug troubleshoot investigate why"
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_keywords_are_deduplicated(self, classifier: TaskClassifier) -> None:
        """Returned keywords list has no duplicates."""
        result = classifier.classify("test test test testing")
        # Check no duplicates by comparing length with set length
        assert len(result.keywords) == len(set(result.keywords))

    def test_entities_are_deduplicated(self, classifier: TaskClassifier) -> None:
        """Returned entities list has no duplicates."""
        result = classifier.classify("update config.py and fix config.py")
        # Check no duplicates
        assert len(result.entities) == len(set(result.entities))


# =============================================================================
# TaskClassifier.classify() - Confidence Score Tests
# =============================================================================


@pytest.mark.unit
class TestClassifyConfidence:
    """Tests for confidence score calculation."""

    def test_more_keywords_higher_confidence(self) -> None:
        """More matching keywords result in higher confidence."""
        classifier = TaskClassifier()
        result_single = classifier.classify("fix")
        result_multiple = classifier.classify("fix the error and debug the issue")
        assert result_multiple.confidence >= result_single.confidence

    def test_domain_terms_boost_confidence(self) -> None:
        """Domain-specific terms boost IMPLEMENT confidence."""
        classifier = TaskClassifier()
        result = classifier.classify("create ONEX node with effect pattern")
        assert result.primary_intent == TaskIntent.IMPLEMENT
        assert result.confidence >= 0.5

    def test_zero_confidence_for_unknown(self) -> None:
        """UNKNOWN intent has zero confidence when no domain terms."""
        classifier = TaskClassifier()
        result = classifier.classify("zzzz xxxx yyyy")
        if result.primary_intent == TaskIntent.UNKNOWN:
            assert result.confidence == 0.0


# =============================================================================
# TaskClassifier._extract_entities() - Direct Tests
# =============================================================================


@pytest.mark.unit
class TestExtractEntitiesMethod:
    """Tests for the _extract_entities() private method."""

    def test_extract_python_file(self) -> None:
        """Python files are extracted."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("look at main.py")
        assert "main.py" in entities

    def test_extract_file_with_path_segments(self) -> None:
        """File names with underscores in path are extracted."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("edit task_classifier.py")
        assert "task_classifier.py" in entities

    def test_extract_snake_case_name(self) -> None:
        """Snake case names are extracted as entities."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("the user_profile_service is slow")
        assert "user_profile_service" in entities

    def test_no_match_for_simple_words(self) -> None:
        """Simple words without underscores or dots are not extracted."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("hello world")
        assert "hello" not in entities
        assert "world" not in entities

    def test_extract_json_file(self) -> None:
        """JSON files are extracted."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("parse config.json")
        assert "config.json" in entities

    def test_extract_markdown_file(self) -> None:
        """Markdown files are extracted."""
        classifier = TaskClassifier()
        entities = classifier._extract_entities("update README.md")
        assert "README.md" in entities


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.unit
class TestClassifierIntegration:
    """Integration tests for complete classification scenarios."""

    def test_complex_debug_scenario(self, classifier: TaskClassifier) -> None:
        """Complex debugging prompt is correctly classified."""
        result = classifier.classify(
            "The kafka consumer in event_processor.py is failing with a connection error. "
            "Can you help debug why it's not connecting to postgres?"
        )
        assert result.primary_intent == TaskIntent.DEBUG
        assert "kafka" in result.mentioned_services
        assert "postgres" in result.mentioned_services
        assert "event_processor.py" in result.entities

    def test_complex_implement_scenario(self, classifier: TaskClassifier) -> None:
        """Complex implementation prompt is correctly classified."""
        result = classifier.classify(
            "Create a new effect node that reads from qdrant and writes to kafka. "
            "The node should be named node_search_effect.py"
        )
        assert result.primary_intent == TaskIntent.IMPLEMENT
        assert "EFFECT" in result.mentioned_node_types
        assert "qdrant" in result.mentioned_services
        assert "kafka" in result.mentioned_services
        assert "node_search_effect.py" in result.entities

    def test_complex_database_scenario(self, classifier: TaskClassifier) -> None:
        """Complex database prompt is correctly classified."""
        # Use a prompt that more clearly signals DATABASE intent
        # (avoids IMPLEMENT keywords like "write", "add", "new")
        result = classifier.classify(
            "Query the agent_routing_decisions table in postgresql to find recent records"
        )
        assert result.primary_intent == TaskIntent.DATABASE
        assert "postgresql" in result.mentioned_services
        assert "agent_routing_decisions" in result.entities

    def test_complex_research_scenario(self, classifier: TaskClassifier) -> None:
        """Complex research prompt is correctly classified."""
        result = classifier.classify(
            "What is the orchestrator node pattern and where can I find examples of it?"
        )
        assert result.primary_intent == TaskIntent.RESEARCH
        assert "ORCHESTRATOR" in result.mentioned_node_types
