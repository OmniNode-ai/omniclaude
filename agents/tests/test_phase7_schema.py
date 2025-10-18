#!/usr/bin/env python3
"""
Phase 7 Schema Tests

Comprehensive tests for Phase 7 database schema enhancements:
- Migration (up and down)
- Python model validation
- CRUD operations
- Performance validation (<50ms writes)

ONEX Compliance: Quality gate validation for database operations
"""

import os
import time
from decimal import Decimal
from uuid import uuid4

import pytest

# Import after ensuring database setup
try:
    from agents.lib.persistence import CodegenPersistence
    from agents.lib.schema_phase7 import (
        EventProcessingCreate,
        EventProcessingMetrics,
        FeedbackType,
        GenerationPerformanceCreate,
        GenerationPerformanceMetrics,
        GenerationPhase,
        MixinCompatibilityCreate,
        MixinCompatibilityMatrix,
        NodeType,
        PatternFeedbackCreate,
        PatternFeedbackLog,
        TemplateCacheCreate,
        TemplateCacheMetadata,
        TemplateCacheUpdate,
        TemplateType,
    )
except ImportError:
    pytest.skip("Database dependencies not available", allow_module_level=True)


# Test configuration
# Note: Set TEST_PG_DSN environment variable with database password
TEST_DSN = os.getenv(
    "TEST_PG_DSN", "postgresql://postgres:YOUR_PASSWORD@localhost:5436/omninode_bridge"  # Replace YOUR_PASSWORD
)

# Performance target (ms)
# Base target represents production-grade performance expectations
PERFORMANCE_TARGET_MS = 50

# Environment-based performance multiplier
# Development/CI environments typically have higher latency due to:
# - Shared resources, slower I/O, network overhead, container virtualization
# Production target: 1.0x (50ms), Development target: 3.0x (150ms), CI target: 4.0x (200ms)
# Override with TEST_PERFORMANCE_MULTIPLIER environment variable
PERFORMANCE_MULTIPLIER = float(os.getenv("TEST_PERFORMANCE_MULTIPLIER", "3.0"))
ADJUSTED_PERFORMANCE_TARGET_MS = PERFORMANCE_TARGET_MS * PERFORMANCE_MULTIPLIER


@pytest.fixture
async def persistence():
    """Create persistence instance for testing"""
    p = CodegenPersistence(dsn=TEST_DSN)
    yield p
    await p.close()


@pytest.fixture
def sample_session_id():
    """Generate sample session ID"""
    return uuid4()


# =============================================================================
# Migration Tests
# =============================================================================


class TestMigration:
    """Test migration up and rollback"""

    @pytest.mark.asyncio
    async def test_migration_tables_exist(self, persistence):
        """Verify all Phase 7 tables exist after migration"""
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'mixin_compatibility_matrix',
                    'pattern_feedback_log',
                    'generation_performance_metrics',
                    'template_cache_metadata',
                    'event_processing_metrics'
                  )
                ORDER BY table_name
            """
            )

            table_names = [row["table_name"] for row in tables]
            assert len(table_names) == 5, f"Expected 5 tables, found {len(table_names)}"
            assert "mixin_compatibility_matrix" in table_names
            assert "pattern_feedback_log" in table_names
            assert "generation_performance_metrics" in table_names
            assert "template_cache_metadata" in table_names
            assert "event_processing_metrics" in table_names

    @pytest.mark.asyncio
    async def test_migration_views_exist(self, persistence):
        """Verify all Phase 7 views exist after migration"""
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            views = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'mixin_compatibility_summary',
                    'pattern_feedback_analysis',
                    'performance_metrics_summary',
                    'template_cache_efficiency',
                    'event_processing_health'
                  )
                ORDER BY table_name
            """
            )

            view_names = [row["table_name"] for row in views]
            assert len(view_names) == 5, f"Expected 5 views, found {len(view_names)}"

    @pytest.mark.asyncio
    async def test_migration_functions_exist(self, persistence):
        """Verify all Phase 7 functions exist after migration"""
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            functions = await conn.fetch(
                """
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema = 'public'
                  AND routine_name IN (
                    'update_mixin_compatibility',
                    'record_pattern_feedback'
                  )
                ORDER BY routine_name
            """
            )

            function_names = [row["routine_name"] for row in functions]
            assert len(function_names) == 2, f"Expected 2 functions, found {len(function_names)}"


# =============================================================================
# Mixin Compatibility Matrix Tests
# =============================================================================


class TestMixinCompatibility:
    """Test mixin compatibility matrix operations"""

    @pytest.mark.asyncio
    async def test_update_mixin_compatibility_success(self, persistence):
        """Test updating mixin compatibility with success"""
        start_time = time.time()

        result_id = await persistence.update_mixin_compatibility(
            mixin_a="TransactionMixin",
            mixin_b="ValidationMixin",
            node_type="EFFECT",
            success=True,
            resolution_pattern="Apply transaction wrapper before validation",
        )

        duration_ms = (time.time() - start_time) * 1000

        assert result_id is not None
        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_update_mixin_compatibility_failure(self, persistence):
        """Test updating mixin compatibility with failure"""
        result_id = await persistence.update_mixin_compatibility(
            mixin_a="AsyncMixin",
            mixin_b="SyncMixin",
            node_type="COMPUTE",
            success=False,
            conflict_reason="Async/sync mismatch in execution context",
        )

        assert result_id is not None

    @pytest.mark.asyncio
    async def test_get_mixin_compatibility(self, persistence):
        """Test retrieving mixin compatibility record"""
        # First create a record
        await persistence.update_mixin_compatibility(
            mixin_a="CacheMixin", mixin_b="LoggingMixin", node_type="REDUCER", success=True
        )

        # Retrieve it
        record = await persistence.get_mixin_compatibility(
            mixin_a="CacheMixin", mixin_b="LoggingMixin", node_type="REDUCER"
        )

        assert record is not None
        assert record["mixin_a"] == "CacheMixin"
        assert record["mixin_b"] == "LoggingMixin"
        assert record["node_type"] == "REDUCER"
        assert record["success_count"] >= 1

    @pytest.mark.asyncio
    async def test_get_mixin_compatibility_summary(self, persistence):
        """Test aggregated compatibility summary"""
        summary = await persistence.get_mixin_compatibility_summary()

        assert isinstance(summary, list)
        # Summary may be empty if no data, but should return list
        for record in summary:
            assert "node_type" in record
            assert "total_combinations" in record


# =============================================================================
# Pattern Feedback Log Tests
# =============================================================================


class TestPatternFeedback:
    """Test pattern feedback logging operations"""

    @pytest.mark.asyncio
    async def test_record_pattern_feedback_correct(self, persistence, sample_session_id):
        """Test recording correct pattern feedback"""
        start_time = time.time()

        result_id = await persistence.record_pattern_feedback(
            session_id=sample_session_id,
            pattern_name="StateManagementPattern",
            detected_confidence=0.95,
            actual_pattern="StateManagementPattern",
            feedback_type="correct",
            user_provided=False,
        )

        duration_ms = (time.time() - start_time) * 1000

        assert result_id is not None
        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_record_pattern_feedback_incorrect(self, persistence, sample_session_id):
        """Test recording incorrect pattern feedback"""
        result_id = await persistence.record_pattern_feedback(
            session_id=sample_session_id,
            pattern_name="EventSourcingPattern",
            detected_confidence=0.65,
            actual_pattern="CQRSPattern",
            feedback_type="incorrect",
            user_provided=True,
            contract_json={"expected": "CQRS", "detected": "EventSourcing"},
        )

        assert result_id is not None

    @pytest.mark.asyncio
    async def test_get_pattern_feedback_analysis(self, persistence):
        """Test pattern feedback analysis view"""
        analysis = await persistence.get_pattern_feedback_analysis()

        assert isinstance(analysis, list)
        for record in analysis:
            assert "pattern_name" in record
            assert "feedback_type" in record


# =============================================================================
# Generation Performance Metrics Tests
# =============================================================================


class TestPerformanceMetrics:
    """Test generation performance metrics operations"""

    @pytest.mark.asyncio
    async def test_insert_performance_metric(self, persistence, sample_session_id):
        """Test inserting performance metric"""
        start_time = time.time()

        await persistence.insert_performance_metric(
            session_id=sample_session_id,
            node_type="EFFECT",
            phase="code_gen",
            duration_ms=1234,
            memory_usage_mb=45,
            cpu_percent=23.5,
            cache_hit=False,
            parallel_execution=True,
            worker_count=4,
            metadata={"complexity": "medium"},
        )

        duration_ms = (time.time() - start_time) * 1000

        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_insert_performance_metric_minimal(self, persistence, sample_session_id):
        """Test inserting minimal performance metric"""
        await persistence.insert_performance_metric(
            session_id=sample_session_id, node_type="COMPUTE", phase="template_load", duration_ms=50
        )

        # Should succeed with minimal required fields

    @pytest.mark.asyncio
    async def test_get_performance_metrics_summary(self, persistence):
        """Test performance metrics summary view"""
        summary = await persistence.get_performance_metrics_summary()

        assert isinstance(summary, list)
        for record in summary:
            assert "phase" in record
            assert "execution_count" in record


# =============================================================================
# Template Cache Metadata Tests
# =============================================================================


class TestTemplateCacheMetadata:
    """Test template cache metadata operations"""

    @pytest.mark.asyncio
    async def test_upsert_template_cache_metadata(self, persistence):
        """Test upserting template cache metadata"""
        start_time = time.time()

        await persistence.upsert_template_cache_metadata(
            template_name="effect_node_template",
            template_type="node",
            cache_key="node:effect:v1.0",
            file_path="/templates/effect_node_template.py",
            file_hash="abc123def456",
            size_bytes=2048,
            load_time_ms=45,
        )

        duration_ms = (time.time() - start_time) * 1000

        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_update_cache_metrics_hit(self, persistence):
        """Test updating cache hit metrics"""
        # First create metadata
        await persistence.upsert_template_cache_metadata(
            template_name="compute_node_template",
            template_type="node",
            cache_key="node:compute:v1.0",
            file_path="/templates/compute_node_template.py",
            file_hash="xyz789",
        )

        start_time = time.time()

        # Record cache hit
        await persistence.update_cache_metrics(template_name="compute_node_template", cache_hit=True)

        duration_ms = (time.time() - start_time) * 1000

        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_update_cache_metrics_miss(self, persistence):
        """Test updating cache miss metrics"""
        # First create metadata
        await persistence.upsert_template_cache_metadata(
            template_name="reducer_node_template",
            template_type="node",
            cache_key="node:reducer:v1.0",
            file_path="/templates/reducer_node_template.py",
            file_hash="lmn456",
        )

        # Record cache miss
        await persistence.update_cache_metrics(template_name="reducer_node_template", cache_hit=False, load_time_ms=120)

        # Should succeed

    @pytest.mark.asyncio
    async def test_get_template_cache_efficiency(self, persistence):
        """Test template cache efficiency view"""
        efficiency = await persistence.get_template_cache_efficiency()

        assert isinstance(efficiency, list)
        for record in efficiency:
            assert "template_type" in record
            assert "template_count" in record


# =============================================================================
# Event Processing Metrics Tests
# =============================================================================


class TestEventProcessingMetrics:
    """Test event processing metrics operations"""

    @pytest.mark.asyncio
    async def test_insert_event_processing_metric_success(self, persistence):
        """Test inserting successful event processing metric"""
        start_time = time.time()

        await persistence.insert_event_processing_metric(
            event_type="code_generation_complete",
            event_source="CodegenWorkflow",
            processing_duration_ms=250,
            success=True,
            queue_wait_time_ms=10,
            batch_size=1,
        )

        duration_ms = (time.time() - start_time) * 1000

        assert (
            duration_ms < ADJUSTED_PERFORMANCE_TARGET_MS
        ), f"Performance target exceeded: {duration_ms:.2f}ms > {ADJUSTED_PERFORMANCE_TARGET_MS:.0f}ms (base: {PERFORMANCE_TARGET_MS}ms, multiplier: {PERFORMANCE_MULTIPLIER}x)"

    @pytest.mark.asyncio
    async def test_insert_event_processing_metric_failure(self, persistence):
        """Test inserting failed event processing metric"""
        await persistence.insert_event_processing_metric(
            event_type="validation_failed",
            event_source="QualityValidator",
            processing_duration_ms=150,
            success=False,
            error_type="ValidationError",
            error_message="Type mismatch in contract",
            retry_count=2,
        )

        # Should succeed

    @pytest.mark.asyncio
    async def test_get_event_processing_health(self, persistence):
        """Test event processing health view"""
        health = await persistence.get_event_processing_health()

        assert isinstance(health, list)
        for record in health:
            assert "event_type" in record
            assert "total_events" in record


# =============================================================================
# Python Model Validation Tests
# =============================================================================


class TestPythonModels:
    """Test Pydantic model validation"""

    def test_mixin_compatibility_model_valid(self):
        """Test valid mixin compatibility model"""
        model = MixinCompatibilityMatrix(
            id=uuid4(),
            mixin_a="TestMixinA",
            mixin_b="TestMixinB",
            node_type=NodeType.EFFECT,
            compatibility_score=Decimal("0.8500"),
            success_count=10,
            failure_count=2,
            created_at="2025-10-15T10:00:00Z",
            updated_at="2025-10-15T10:00:00Z",
        )

        assert model.total_tests == 12
        assert abs(model.success_rate - 83.33) < 0.1

    def test_pattern_feedback_model_valid(self):
        """Test valid pattern feedback model"""
        model = PatternFeedbackLog(
            id=uuid4(),
            session_id=uuid4(),
            pattern_name="TestPattern",
            detected_confidence=Decimal("0.9000"),
            actual_pattern="TestPattern",
            feedback_type=FeedbackType.CORRECT,
            user_provided=True,
            learning_weight=Decimal("1.0"),
            created_at="2025-10-15T10:00:00Z",
        )

        assert model.feedback_type == FeedbackType.CORRECT

    def test_performance_metric_model_valid(self):
        """Test valid performance metric model"""
        model = GenerationPerformanceMetrics(
            id=uuid4(),
            session_id=uuid4(),
            node_type="EFFECT",
            phase=GenerationPhase.CODE_GEN,
            duration_ms=1500,
            memory_usage_mb=50,
            cpu_percent=Decimal("25.5"),
            cache_hit=True,
            parallel_execution=True,
            worker_count=4,
            created_at="2025-10-15T10:00:00Z",
        )

        assert model.phase == GenerationPhase.CODE_GEN

    def test_template_cache_model_valid(self):
        """Test valid template cache model"""
        model = TemplateCacheMetadata(
            id=uuid4(),
            template_name="test_template",
            template_type=TemplateType.NODE,
            cache_key="node:test:v1",
            file_path="/templates/test.py",
            file_hash="abc123",
            size_bytes=2048,
            load_time_ms=50,
            access_count=100,
            cache_hits=80,
            cache_misses=20,
            created_at="2025-10-15T10:00:00Z",
            updated_at="2025-10-15T10:00:00Z",
        )

        assert model.total_accesses == 100
        assert model.hit_rate == 80.0

    def test_event_processing_model_valid(self):
        """Test valid event processing model"""
        model = EventProcessingMetrics(
            id=uuid4(),
            event_type="test_event",
            event_source="TestSource",
            processing_duration_ms=100,
            success=True,
            batch_size=5,
            created_at="2025-10-15T10:00:00Z",
        )

        assert model.success is True


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Test integrated workflows"""

    @pytest.mark.asyncio
    async def test_full_codegen_workflow(self, persistence, sample_session_id):
        """Test complete code generation workflow with all Phase 7 metrics"""

        # 1. Record performance metrics for each phase
        phases = ["prd_analysis", "template_load", "code_gen", "validation", "persistence"]
        for phase in phases:
            await persistence.insert_performance_metric(
                session_id=sample_session_id,
                node_type="EFFECT",
                phase=phase,
                duration_ms=100 + (phases.index(phase) * 50),
                cache_hit=(phase == "template_load"),
            )

        # 2. Update mixin compatibility
        await persistence.update_mixin_compatibility(
            mixin_a="TransactionMixin", mixin_b="ErrorHandlingMixin", node_type="EFFECT", success=True
        )

        # 3. Record pattern feedback
        await persistence.record_pattern_feedback(
            session_id=sample_session_id,
            pattern_name="TransactionPattern",
            detected_confidence=0.92,
            actual_pattern="TransactionPattern",
            feedback_type="correct",
        )

        # 4. Update template cache
        await persistence.upsert_template_cache_metadata(
            template_name="effect_template",
            template_type="node",
            cache_key="node:effect:v1",
            file_path="/templates/effect.py",
            file_hash="hash123",
        )
        await persistence.update_cache_metrics(template_name="effect_template", cache_hit=True)

        # 5. Record event processing
        await persistence.insert_event_processing_metric(
            event_type="generation_complete", event_source="CodegenWorkflow", processing_duration_ms=500, success=True
        )

        # Verify all data persisted
        metrics = await persistence.get_performance_metrics_summary(sample_session_id)
        assert len(metrics) > 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
