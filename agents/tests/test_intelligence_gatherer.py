#!/usr/bin/env python3
"""
Tests for IntelligenceGatherer - RAG Integration for Node Generation
"""

from unittest.mock import AsyncMock

import pytest

from agents.lib.config.intelligence_config import IntelligenceConfig
from agents.lib.intelligence_event_client import IntelligenceEventClient
from agents.lib.intelligence_gatherer import IntelligenceGatherer
from agents.lib.models.intelligence_context import IntelligenceContext


class TestIntelligenceGatherer:
    """Test suite for IntelligenceGatherer"""

    @pytest.fixture
    def gatherer(self):
        """Create intelligence gatherer instance"""
        return IntelligenceGatherer()

    @pytest.mark.asyncio
    async def test_gather_intelligence_effect_database(self, gatherer):
        """Test gathering intelligence for EFFECT/database node"""
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="PostgresCRUD",
            operations=["create", "read", "update", "delete"],
            prompt="Create PostgreSQL CRUD node",
        )

        # Verify intelligence was gathered
        assert isinstance(intelligence, IntelligenceContext)
        assert len(intelligence.node_type_patterns) > 0
        assert len(intelligence.domain_best_practices) > 0
        assert len(intelligence.common_operations) > 0
        assert len(intelligence.required_mixins) > 0
        assert len(intelligence.rag_sources) > 0

        # Verify specific patterns for database EFFECT nodes
        patterns_str = str(intelligence.node_type_patterns).lower()
        assert "connection pooling" in patterns_str
        assert "prepared statements" in patterns_str or "sql injection" in patterns_str

        # Verify common operations
        assert "create" in intelligence.common_operations
        assert "read" in intelligence.common_operations
        assert "update" in intelligence.common_operations
        assert "delete" in intelligence.common_operations

        # Verify performance targets
        assert "max_response_time_ms" in intelligence.performance_targets
        assert intelligence.performance_targets["max_response_time_ms"] > 0

        # Verify error scenarios
        assert len(intelligence.error_scenarios) > 0

        # Verify confidence score
        assert 0.0 <= intelligence.confidence_score <= 1.0
        assert intelligence.confidence_score > 0.0  # Should have some confidence

    @pytest.mark.asyncio
    async def test_gather_intelligence_compute_general(self, gatherer):
        """Test gathering intelligence for COMPUTE node"""
        intelligence = await gatherer.gather_intelligence(
            node_type="COMPUTE",
            domain="general",
            service_name="Calculator",
            operations=["calculate", "validate"],
            prompt="Create calculation node",
        )

        # Verify COMPUTE-specific patterns
        patterns_str = str(intelligence.node_type_patterns).lower()
        assert "pure function" in patterns_str or "no side effect" in patterns_str
        assert "immutable" in patterns_str

        # Verify COMPUTE operations
        assert "calculate" in intelligence.common_operations
        assert "transform" in intelligence.common_operations

        # Verify performance targets specific to COMPUTE
        assert (
            "single_operation_max_ms" in intelligence.performance_targets
            or "max_computation_time_ms" in intelligence.performance_targets
        )

    @pytest.mark.asyncio
    async def test_gather_intelligence_reducer(self, gatherer):
        """Test gathering intelligence for REDUCER node"""
        intelligence = await gatherer.gather_intelligence(
            node_type="REDUCER",
            domain="analytics",
            service_name="DataAggregator",
            operations=["aggregate", "reduce"],
            prompt="Create data aggregation node",
        )

        # Verify REDUCER-specific patterns
        patterns_str = str(intelligence.node_type_patterns).lower()
        assert (
            "aggregat" in patterns_str or "state" in patterns_str
        )  # Pattern includes aggregation or state management

        # Verify REDUCER operations
        assert "aggregate" in intelligence.common_operations
        assert "reduce" in intelligence.common_operations

        # Verify REDUCER performance targets
        assert (
            "aggregation_window_ms" in intelligence.performance_targets
            or "max_aggregation_delay_ms" in intelligence.performance_targets
        )

    @pytest.mark.asyncio
    async def test_gather_intelligence_orchestrator(self, gatherer):
        """Test gathering intelligence for ORCHESTRATOR node"""
        intelligence = await gatherer.gather_intelligence(
            node_type="ORCHESTRATOR",
            domain="workflow",
            service_name="TaskOrchestrator",
            operations=["coordinate", "orchestrate"],
            prompt="Create workflow orchestration node",
        )

        # Verify ORCHESTRATOR-specific patterns (should have orchestration-related patterns)
        patterns_str = str(intelligence.node_type_patterns).lower()
        # ORCHESTRATOR patterns should include workflow orchestration concepts
        assert (
            "workflow" in patterns_str
            or "coordinat" in patterns_str
            or "orchestrat" in patterns_str
            or "dag" in patterns_str  # DAG-based execution is orchestration
            or "dependency" in patterns_str  # Dependency management is orchestration
        )

        # Verify ORCHESTRATOR operations
        assert (
            "coordinate" in intelligence.common_operations
            or "orchestrate" in intelligence.common_operations
        )

        # Verify ORCHESTRATOR performance targets
        assert (
            "workflow_timeout_ms" in intelligence.performance_targets
            or "coordination_overhead_ms" in intelligence.performance_targets
        )

    @pytest.mark.asyncio
    async def test_domain_normalization(self, gatherer):
        """Test domain normalization for pattern matching"""
        # Test PostgreSQL domain normalization
        intelligence_postgres = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="postgresql",
            service_name="PostgresClient",
            operations=["query"],
            prompt="PostgreSQL client",
        )

        intelligence_db = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Both should have similar database patterns
        assert len(intelligence_postgres.node_type_patterns) > 0
        assert len(intelligence_db.node_type_patterns) > 0

        # Verify they both have database-related patterns
        postgres_patterns = str(intelligence_postgres.node_type_patterns).lower()
        db_patterns = str(intelligence_db.node_type_patterns).lower()

        assert "connection" in postgres_patterns or "database" in postgres_patterns
        assert "connection" in db_patterns or "database" in db_patterns

    @pytest.mark.asyncio
    async def test_mixin_recommendations(self, gatherer):
        """Test mixin recommendations based on node type and domain"""
        # Test database EFFECT node - should recommend transaction mixin
        intelligence_db = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseWriter",
            operations=["write"],
            prompt="Database writer",
        )

        # Verify retry and circuit breaker mixins for EFFECT
        mixins = intelligence_db.required_mixins
        assert any("Retry" in m for m in mixins) or any(
            "CircuitBreaker" in m for m in mixins
        )

        # Test API EFFECT node - should recommend rate limiting
        intelligence_api = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="api",
            service_name="ApiClient",
            operations=["request"],
            prompt="API client",
        )

        mixins_api = intelligence_api.required_mixins
        # Should have API-specific or EFFECT-specific mixins
        assert len(mixins_api) > 0

    @pytest.mark.asyncio
    async def test_error_scenarios(self, gatherer):
        """Test error scenario extraction"""
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database query client",
        )

        # Verify database-specific error scenarios
        errors = intelligence.error_scenarios
        assert len(errors) > 0

        errors_str = str(errors).lower()
        # Should have at least one database-related error
        assert (
            "timeout" in errors_str
            or "connection" in errors_str
            or "deadlock" in errors_str
            or "constraint" in errors_str
        )

    @pytest.mark.asyncio
    async def test_performance_targets(self, gatherer):
        """Test performance target extraction"""
        # Test EFFECT node performance targets
        intelligence_effect = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="api",
            service_name="ApiClient",
            operations=["request"],
            prompt="API client",
        )

        perf_effect = intelligence_effect.performance_targets
        assert len(perf_effect) > 0
        assert "max_response_time_ms" in perf_effect or "timeout_ms" in perf_effect

        # Test COMPUTE node performance targets
        intelligence_compute = await gatherer.gather_intelligence(
            node_type="COMPUTE",
            domain="calculation",
            service_name="Calculator",
            operations=["calculate"],
            prompt="Calculator",
        )

        perf_compute = intelligence_compute.performance_targets
        assert len(perf_compute) > 0
        # Should have computation-specific metrics
        assert any(
            "computation" in k.lower() or "operation" in k.lower()
            for k in perf_compute.keys()
        )

    @pytest.mark.asyncio
    async def test_intelligence_sources(self, gatherer):
        """Test that intelligence sources are tracked"""
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Should have at least the built-in pattern library as a source
        assert len(intelligence.rag_sources) > 0
        assert "builtin_pattern_library" in intelligence.rag_sources

    @pytest.mark.asyncio
    async def test_confidence_score(self, gatherer):
        """Test confidence score is set"""
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Should have a reasonable confidence score
        assert 0.0 <= intelligence.confidence_score <= 1.0
        # Built-in patterns should have at least moderate confidence
        assert intelligence.confidence_score >= 0.5

    @pytest.mark.asyncio
    async def test_empty_operations_handling(self, gatherer):
        """Test handling of empty operations list"""
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=[],  # Empty operations
            prompt="Database client",
        )

        # Should still gather intelligence even without explicit operations
        assert len(intelligence.node_type_patterns) > 0
        assert len(intelligence.common_operations) > 0  # Should have default operations

    @pytest.mark.asyncio
    async def test_event_based_discovery_success(self):
        """Test successful event-based pattern discovery"""
        # Mock configuration with event discovery enabled
        config = IntelligenceConfig(
            kafka_enable_intelligence=True,
            enable_event_based_discovery=True,
            enable_filesystem_fallback=True,
            prefer_event_patterns=True,
        )

        # Mock event client with successful response
        mock_event_client = AsyncMock(spec=IntelligenceEventClient)
        mock_event_client.request_pattern_discovery = AsyncMock(
            return_value=[
                {
                    "file_path": "node_database_writer_effect.py",
                    "confidence": 0.95,
                    "pattern_type": "database_effect",
                    "description": "Production database writer with connection pooling",
                    "code_snippet": "async def write_data(self, data): ...",
                    "best_practices": [
                        "Use connection pooling",
                        "Implement transaction support",
                    ],
                },
                {
                    "file_path": "node_api_client_effect.py",
                    "confidence": 0.88,
                    "pattern_type": "api_effect",
                    "description": "API client with retry logic",
                    "best_practices": ["Implement exponential backoff"],
                },
            ]
        )

        # Create gatherer with mocked event client
        gatherer = IntelligenceGatherer(
            config=config,
            event_client=mock_event_client,
        )

        # Gather intelligence
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseWriter",
            operations=["write"],
            prompt="Database writer",
        )

        # Verify event client was called
        mock_event_client.request_pattern_discovery.assert_called_once()

        # Verify patterns were extracted
        assert len(intelligence.node_type_patterns) > 0
        assert any(
            "connection pooling" in p.lower() for p in intelligence.node_type_patterns
        )

        # Verify code examples were added
        assert len(intelligence.code_examples) > 0

        # Verify event source was tracked
        assert "event_based_discovery" in intelligence.rag_sources

        # Verify high confidence score (prefer_event_patterns=True)
        assert intelligence.confidence_score >= 0.9

    @pytest.mark.asyncio
    async def test_event_based_discovery_timeout(self):
        """Test event-based discovery with timeout fallback"""
        # Mock configuration
        config = IntelligenceConfig(
            kafka_enable_intelligence=True,
            enable_event_based_discovery=True,
            enable_filesystem_fallback=True,
        )

        # Mock event client that times out
        mock_event_client = AsyncMock(spec=IntelligenceEventClient)
        mock_event_client.request_pattern_discovery = AsyncMock(
            side_effect=TimeoutError("Request timeout after 5000ms")
        )

        # Create gatherer with mocked event client
        gatherer = IntelligenceGatherer(
            config=config,
            event_client=mock_event_client,
        )

        # Gather intelligence - should fallback to built-in patterns
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Verify event client was called
        mock_event_client.request_pattern_discovery.assert_called_once()

        # Should still have patterns from built-in library
        assert len(intelligence.node_type_patterns) > 0

        # Should have built-in source
        assert "builtin_pattern_library" in intelligence.rag_sources

        # Should NOT have event-based source
        assert "event_based_discovery" not in intelligence.rag_sources

        # Should have reasonable confidence from built-in patterns
        assert intelligence.confidence_score >= 0.7

    @pytest.mark.asyncio
    async def test_event_based_discovery_disabled(self):
        """Test that event discovery is skipped when disabled"""
        # Mock configuration with event discovery disabled
        config = IntelligenceConfig(
            kafka_enable_intelligence=False,
            enable_event_based_discovery=False,
        )

        # Mock event client (should not be called)
        mock_event_client = AsyncMock(spec=IntelligenceEventClient)
        mock_event_client.request_pattern_discovery = AsyncMock()

        # Create gatherer
        gatherer = IntelligenceGatherer(
            config=config,
            event_client=mock_event_client,
        )

        # Gather intelligence
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Verify event client was NOT called
        mock_event_client.request_pattern_discovery.assert_not_called()

        # Should still have patterns from built-in library
        assert len(intelligence.node_type_patterns) > 0
        assert "builtin_pattern_library" in intelligence.rag_sources

    @pytest.mark.asyncio
    async def test_event_based_discovery_no_event_client(self):
        """Test graceful handling when event client is not provided"""
        # Create gatherer without event client
        gatherer = IntelligenceGatherer(event_client=None)

        # Gather intelligence
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Should still work with built-in patterns
        assert len(intelligence.node_type_patterns) > 0
        assert "builtin_pattern_library" in intelligence.rag_sources

    @pytest.mark.asyncio
    async def test_event_based_discovery_empty_response(self):
        """Test handling of empty response from event discovery"""
        # Mock configuration
        config = IntelligenceConfig(
            kafka_enable_intelligence=True,
            enable_event_based_discovery=True,
            enable_filesystem_fallback=True,
        )

        # Mock event client with empty response
        mock_event_client = AsyncMock(spec=IntelligenceEventClient)
        mock_event_client.request_pattern_discovery = AsyncMock(return_value=[])

        # Create gatherer
        gatherer = IntelligenceGatherer(
            config=config,
            event_client=mock_event_client,
        )

        # Gather intelligence
        intelligence = await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="DatabaseClient",
            operations=["query"],
            prompt="Database client",
        )

        # Verify event client was called
        mock_event_client.request_pattern_discovery.assert_called_once()

        # Should fallback to built-in patterns
        assert len(intelligence.node_type_patterns) > 0
        assert "builtin_pattern_library" in intelligence.rag_sources

        # Should NOT have event-based source (empty response)
        assert "event_based_discovery" not in intelligence.rag_sources


class TestIntelligenceContext:
    """Test IntelligenceContext model"""

    def test_intelligence_context_creation(self):
        """Test creating an IntelligenceContext instance"""
        context = IntelligenceContext(
            node_type_patterns=["Pattern 1", "Pattern 2"],
            common_operations=["create", "read"],
            required_mixins=["MixinRetry"],
            performance_targets={"timeout_ms": 5000},
            error_scenarios=["Connection timeout"],
            domain_best_practices=["Use connection pooling"],
            rag_sources=["builtin_pattern_library"],
            confidence_score=0.8,
        )

        assert len(context.node_type_patterns) == 2
        assert len(context.common_operations) == 2
        assert len(context.required_mixins) == 1
        assert context.confidence_score == 0.8
        assert "timeout_ms" in context.performance_targets

    def test_intelligence_context_defaults(self):
        """Test IntelligenceContext with default values"""
        context = IntelligenceContext()

        # All lists should be empty by default
        assert len(context.node_type_patterns) == 0
        assert len(context.common_operations) == 0
        assert len(context.required_mixins) == 0
        assert len(context.error_scenarios) == 0
        assert len(context.domain_best_practices) == 0
        assert len(context.rag_sources) == 0
        assert context.confidence_score == 0.0

    def test_intelligence_context_validation(self):
        """Test Pydantic validation in IntelligenceContext"""
        # Valid confidence score
        context = IntelligenceContext(confidence_score=0.5)
        assert context.confidence_score == 0.5

        # Invalid confidence score should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            IntelligenceContext(confidence_score=1.5)

        with pytest.raises(Exception):  # Pydantic ValidationError
            IntelligenceContext(confidence_score=-0.1)
