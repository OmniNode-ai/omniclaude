#!/usr/bin/env python3
"""
Tests for PromptParser component.

Tests cover:
- Simple prompts
- Detailed prompts
- Minimal prompts
- Invalid prompts (error cases)
- Edge cases
- Each extraction strategy
"""

from uuid import UUID

import pytest
from omnibase_core.errors import EnumCoreErrorCode, OnexError

from agents.lib.models.prompt_parse_result import PromptParseResult
from agents.lib.prompt_parser import PromptParser


@pytest.fixture
def parser():
    """Create a PromptParser instance."""
    return PromptParser()


class TestSimplePrompts:
    """Test parsing of simple, well-formed prompts."""

    def test_simple_effect_node(self, parser):
        """Test parsing simple EFFECT node prompt."""
        prompt = "Create an EFFECT node called DatabaseWriter in the data_services domain that writes records to PostgreSQL"

        result = parser.parse(prompt)

        assert isinstance(result, PromptParseResult)
        assert result.node_name == "DatabaseWriter"
        assert result.node_type == "EFFECT"
        assert result.domain == "data_services"
        assert "PostgreSQL" in result.external_systems
        assert result.confidence >= 0.8
        assert isinstance(result.correlation_id, UUID)
        assert isinstance(result.session_id, UUID)

    def test_simple_compute_node(self, parser):
        """Test parsing simple COMPUTE node prompt."""
        prompt = "COMPUTE node: PriceCalculator (domain: pricing_engine) - calculates prices with tax and discounts"

        result = parser.parse(prompt)

        assert result.node_name == "PriceCalculator"
        assert result.node_type == "COMPUTE"
        assert result.domain == "pricing_engine"
        assert result.confidence >= 0.7

    def test_simple_reducer_node(self, parser):
        """Test parsing simple REDUCER node prompt."""
        prompt = "REDUCER node for aggregating user analytics, called AnalyticsAggregator, domain: analytics_services"

        result = parser.parse(prompt)

        assert result.node_name == "AnalyticsAggregator"
        assert result.node_type == "REDUCER"
        assert result.domain == "analytics_services"
        assert result.confidence >= 0.7

    def test_simple_orchestrator_node(self, parser):
        """Test parsing simple ORCHESTRATOR node prompt."""
        prompt = "Create ORCHESTRATOR node WorkflowCoordinator in workflow_services domain that coordinates multi-step processes"

        result = parser.parse(prompt)

        assert result.node_name == "WorkflowCoordinator"
        assert result.node_type == "ORCHESTRATOR"
        assert result.domain == "workflow_services"
        assert result.confidence >= 0.8


class TestDetailedPrompts:
    """Test parsing of detailed prompts with requirements."""

    def test_detailed_with_requirements(self, parser):
        """Test prompt with functional requirements."""
        prompt = """
        Create EFFECT node EmailSender in notification domain.

        Requirements:
        - Send emails via SMTP
        - Support HTML and plain text
        - Handle attachments
        - Retry on failure
        - Log all email operations
        """

        result = parser.parse(prompt)

        assert result.node_name == "EmailSender"
        assert result.node_type == "EFFECT"
        assert result.domain == "notification"
        assert len(result.functional_requirements) >= 3
        assert "SMTP" in result.external_systems
        assert result.confidence >= 0.7

    def test_detailed_with_should_statements(self, parser):
        """Test prompt with 'should' statements."""
        prompt = "COMPUTE node DataTransformer should process CSV files, should validate data integrity, and should output JSON format"

        result = parser.parse(prompt)

        assert result.node_type == "COMPUTE"
        assert "DataTransformer" in result.node_name
        assert len(result.functional_requirements) >= 1

    def test_detailed_with_external_systems(self, parser):
        """Test prompt mentioning multiple external systems."""
        prompt = "EFFECT node CacheWriter writes to Redis cache and PostgreSQL database for persistence"

        result = parser.parse(prompt)

        assert result.node_type == "EFFECT"
        assert "Redis" in result.external_systems
        assert "PostgreSQL" in result.external_systems


class TestMinimalPrompts:
    """Test parsing of minimal prompts."""

    def test_minimal_with_defaults(self, parser):
        """Test minimal prompt relies on defaults."""
        prompt = "Create node for sending notifications"

        result = parser.parse(prompt)

        assert result.node_type in ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
        assert result.node_name  # Some name extracted
        assert result.domain  # Some domain extracted
        assert len(result.description) >= 10

    def test_minimal_without_explicit_type(self, parser):
        """Test prompt without explicit node type."""
        prompt = "DatabaseWriter node writes records to PostgreSQL"

        result = parser.parse(prompt)

        # Should infer EFFECT from "write" action verb
        assert result.node_type == "EFFECT"
        assert result.node_name == "DatabaseWriter"
        assert "PostgreSQL" in result.external_systems

    def test_minimal_without_domain(self, parser):
        """Test prompt without explicit domain."""
        prompt = "EFFECT node called ApiClient that calls external REST APIs"

        result = parser.parse(prompt)

        assert result.node_type == "EFFECT"
        assert result.node_name == "ApiClient"
        # Should get default or inferred domain
        assert result.domain


class TestInvalidPrompts:
    """Test error handling for invalid prompts."""

    def test_empty_prompt(self, parser):
        """Test empty prompt raises error."""
        with pytest.raises(OnexError) as exc_info:
            parser.parse("")

        assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR
        assert "empty" in str(exc_info.value).lower()

    def test_none_prompt(self, parser):
        """Test None prompt raises error."""
        with pytest.raises(OnexError) as exc_info:
            parser.parse(None)

        assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR

    def test_too_short_prompt(self, parser):
        """Test very short prompt raises error."""
        with pytest.raises(OnexError) as exc_info:
            parser.parse("node")

        assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR
        assert "too short" in str(exc_info.value).lower()

    def test_whitespace_only_prompt(self, parser):
        """Test whitespace-only prompt raises error."""
        with pytest.raises(OnexError) as exc_info:
            parser.parse("   \n\t   ")

        assert exc_info.value.error_code == EnumCoreErrorCode.VALIDATION_ERROR


class TestNodeTypeExtraction:
    """Test node type extraction strategies."""

    def test_explicit_effect_keyword(self, parser):
        """Test explicit EFFECT keyword."""
        prompt = "EFFECT node for database operations"
        result = parser.parse(prompt)
        assert result.node_type == "EFFECT"
        assert result.confidence >= 0.7

    def test_explicit_compute_keyword(self, parser):
        """Test explicit COMPUTE keyword."""
        prompt = "COMPUTE node processes data transformations"
        result = parser.parse(prompt)
        assert result.node_type == "COMPUTE"

    def test_infer_from_write_verb(self, parser):
        """Test inferring EFFECT from write action."""
        prompt = "Node that writes data to storage"
        result = parser.parse(prompt)
        assert result.node_type == "EFFECT"

    def test_infer_from_calculate_verb(self, parser):
        """Test inferring COMPUTE from calculate action."""
        prompt = "Node that calculates pricing totals"
        result = parser.parse(prompt)
        assert result.node_type == "COMPUTE"

    def test_infer_from_aggregate_verb(self, parser):
        """Test inferring REDUCER from aggregate action."""
        prompt = "Node that aggregates user statistics"
        result = parser.parse(prompt)
        assert result.node_type == "REDUCER"

    def test_infer_from_coordinate_verb(self, parser):
        """Test inferring ORCHESTRATOR from coordinate action."""
        prompt = "Node that coordinates workflow steps"
        result = parser.parse(prompt)
        assert result.node_type == "ORCHESTRATOR"


class TestNodeNameExtraction:
    """Test node name extraction strategies."""

    def test_explicit_called_pattern(self, parser):
        """Test 'called NodeName' pattern."""
        prompt = "EFFECT node called DatabaseWriter"
        result = parser.parse(prompt)
        assert result.node_name == "DatabaseWriter"

    def test_explicit_name_colon_pattern(self, parser):
        """Test 'Name: NodeName' pattern."""
        prompt = "COMPUTE node Name: PriceCalculator for pricing"
        result = parser.parse(prompt)
        assert result.node_name == "PriceCalculator"

    def test_nodename_node_pattern(self, parser):
        """Test 'NodeName node' pattern."""
        prompt = "EmailSender node sends notifications"
        result = parser.parse(prompt)
        assert result.node_name == "EmailSender"

    def test_generated_from_context(self, parser):
        """Test name generation from context."""
        prompt = "EFFECT node writes to PostgreSQL database"
        result = parser.parse(prompt)
        # Should generate something like PostgreSQLWriter
        assert "PostgreSQL" in result.node_name or "Writer" in result.node_name


class TestDomainExtraction:
    """Test domain extraction strategies."""

    def test_explicit_in_the_domain(self, parser):
        """Test 'in the X domain' pattern."""
        prompt = "EFFECT node in the data_services domain"
        result = parser.parse(prompt)
        assert result.domain == "data_services"

    def test_explicit_domain_colon(self, parser):
        """Test 'domain: X' pattern."""
        prompt = "COMPUTE node domain: analytics_engine processes data"
        result = parser.parse(prompt)
        assert result.domain == "analytics_engine"

    def test_infer_from_database_keyword(self, parser):
        """Test inferring domain from database keyword."""
        prompt = "EFFECT node for database operations"
        result = parser.parse(prompt)
        assert "data" in result.domain or "database" in result.domain

    def test_infer_from_api_keyword(self, parser):
        """Test inferring domain from API keyword."""
        prompt = "EFFECT node calls REST API endpoints"
        result = parser.parse(prompt)
        assert "api" in result.domain


class TestRequirementsExtraction:
    """Test functional requirements extraction."""

    def test_bullet_points(self, parser):
        """Test extracting bullet point requirements."""
        prompt = """
        EFFECT node for email:
        - Send HTML emails
        - Support attachments
        - Retry on failure
        """
        result = parser.parse(prompt)
        assert len(result.functional_requirements) >= 2

    def test_should_statements(self, parser):
        """Test extracting 'should' statements."""
        prompt = "COMPUTE node should validate inputs and should transform data formats"
        result = parser.parse(prompt)
        assert len(result.functional_requirements) >= 1

    def test_action_verbs(self, parser):
        """Test extracting action verb phrases."""
        prompt = "EFFECT node creates records, updates existing data, and deletes obsolete entries"
        result = parser.parse(prompt)
        assert len(result.functional_requirements) >= 1


class TestExternalSystemDetection:
    """Test external system detection."""

    def test_detect_postgresql(self, parser):
        """Test detecting PostgreSQL."""
        prompt = "EFFECT node writes to PostgreSQL database"
        result = parser.parse(prompt)
        assert "PostgreSQL" in result.external_systems

    def test_detect_redis(self, parser):
        """Test detecting Redis."""
        prompt = "EFFECT node stores cache in Redis"
        result = parser.parse(prompt)
        assert "Redis" in result.external_systems

    def test_detect_kafka(self, parser):
        """Test detecting Kafka."""
        prompt = "EFFECT node publishes events to Kafka"
        result = parser.parse(prompt)
        assert "Kafka" in result.external_systems

    def test_detect_smtp(self, parser):
        """Test detecting SMTP."""
        prompt = "EFFECT node sends email via SMTP"
        result = parser.parse(prompt)
        assert "SMTP" in result.external_systems

    def test_detect_multiple_systems(self, parser):
        """Test detecting multiple systems."""
        prompt = (
            "EFFECT node reads from PostgreSQL, caches in Redis, and publishes to Kafka"
        )
        result = parser.parse(prompt)
        assert "PostgreSQL" in result.external_systems
        assert "Redis" in result.external_systems
        assert "Kafka" in result.external_systems


class TestConfidenceScoring:
    """Test confidence score calculation."""

    def test_high_confidence_complete_prompt(self, parser):
        """Test high confidence for complete prompt."""
        prompt = "EFFECT node called DatabaseWriter in data_services domain writes to PostgreSQL with retry logic"
        result = parser.parse(prompt)
        assert result.confidence >= 0.8

    def test_medium_confidence_inferred_fields(self, parser):
        """Test medium confidence for inferred fields."""
        prompt = "Node that writes database records"
        result = parser.parse(prompt)
        assert 0.4 <= result.confidence <= 0.8

    def test_confidence_increases_with_requirements(self, parser):
        """Test confidence increases with more requirements."""
        prompt1 = "EFFECT node DatabaseWriter"
        prompt2 = "EFFECT node DatabaseWriter should create records, update data, and handle errors"

        result1 = parser.parse(prompt1)
        result2 = parser.parse(prompt2)

        assert result2.confidence > result1.confidence


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_prompt_with_special_characters(self, parser):
        """Test prompt with special characters."""
        prompt = "EFFECT node: EmailSender (notification domain) - sends emails!"
        result = parser.parse(prompt)
        assert result.node_name == "EmailSender"
        assert result.node_type == "EFFECT"

    def test_prompt_with_newlines(self, parser):
        """Test prompt with multiple newlines."""
        prompt = """
        EFFECT node

        Name: DataWriter
        Domain: data_services

        Writes to PostgreSQL
        """
        result = parser.parse(prompt)
        assert result.node_name == "DataWriter"
        assert result.domain == "data_services"

    def test_custom_correlation_id(self, parser):
        """Test using custom correlation ID."""
        from uuid import uuid4

        custom_id = uuid4()
        prompt = "EFFECT node for database writes"
        result = parser.parse(prompt, correlation_id=custom_id)

        assert result.correlation_id == custom_id

    def test_custom_session_id(self, parser):
        """Test using custom session ID."""
        from uuid import uuid4

        custom_id = uuid4()
        prompt = "EFFECT node for database writes"
        result = parser.parse(prompt, session_id=custom_id)

        assert result.session_id == custom_id


class TestResultValidation:
    """Test PromptParseResult validation."""

    def test_valid_result_creation(self):
        """Test creating valid PromptParseResult."""
        from uuid import uuid4

        result = PromptParseResult(
            node_name="DatabaseWriter",
            node_type="EFFECT",
            domain="data_services",
            description="Writes records to database",
            functional_requirements=["Create records", "Update records"],
            external_systems=["PostgreSQL"],
            confidence=0.9,
            correlation_id=uuid4(),
            session_id=uuid4(),
        )

        assert result.node_name == "DatabaseWriter"
        assert result.node_type == "EFFECT"
        assert result.confidence == 0.9

    def test_invalid_node_type(self):
        """Test invalid node type raises error."""
        from uuid import uuid4

        with pytest.raises(Exception):  # Pydantic ValidationError
            PromptParseResult(
                node_name="Test",
                node_type="INVALID",  # Not a valid node type
                domain="test",
                description="Test description",
                confidence=0.5,
                correlation_id=uuid4(),
                session_id=uuid4(),
            )

    def test_invalid_confidence_range(self):
        """Test confidence out of range raises error."""
        from uuid import uuid4

        with pytest.raises(Exception):  # Pydantic ValidationError
            PromptParseResult(
                node_name="Test",
                node_type="EFFECT",
                domain="test",
                description="Test description",
                confidence=1.5,  # Out of range
                correlation_id=uuid4(),
                session_id=uuid4(),
            )

    def test_description_too_short(self):
        """Test description too short raises error."""
        from uuid import uuid4

        with pytest.raises(Exception):  # Pydantic ValidationError
            PromptParseResult(
                node_name="Test",
                node_type="EFFECT",
                domain="test",
                description="Short",  # Too short
                confidence=0.5,
                correlation_id=uuid4(),
                session_id=uuid4(),
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
