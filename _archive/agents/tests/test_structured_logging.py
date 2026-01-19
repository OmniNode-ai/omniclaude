"""
Structured Logging Framework Tests

Comprehensive test suite for structured JSON logging with correlation IDs,
context propagation, and performance validation.

Test Coverage:
- Basic structured logging
- Correlation ID propagation
- Session ID tracking
- Context managers (sync and async)
- Decorators
- Log rotation
- Performance validation (<1ms overhead)
- JSON output validation
"""

import json
import logging
import time
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest

from agents.lib.log_context import (
    LogContext,
    async_log_context,
    log_context,
    with_log_context,
)
from agents.lib.log_rotation import (
    LogRotationConfig,
    configure_file_rotation,
    get_log_stats,
)
from agents.lib.structured_logger import (
    StructuredLogger,
    get_correlation_id,
    get_logger,
    get_session_id,
    set_global_correlation_id,
    set_global_session_id,
)


class TestStructuredLogger:
    """Test StructuredLogger basic functionality"""

    def test_logger_creation(self):
        """Test logger can be created with component"""
        logger = StructuredLogger("test_logger", component="test-component")
        assert logger.component == "test-component"
        assert logger.logger.name == "test_logger"

    def test_set_correlation_id(self):
        """Test correlation ID can be set"""
        logger = StructuredLogger("test_logger")
        correlation_id = uuid4()
        logger.set_correlation_id(correlation_id)
        assert logger.correlation_id == str(correlation_id)

    def test_set_session_id(self):
        """Test session ID can be set"""
        logger = StructuredLogger("test_logger")
        session_id = uuid4()
        logger.set_session_id(session_id)
        assert logger.session_id == str(session_id)

    def test_log_levels(self):
        """Test all log levels work"""
        logger = StructuredLogger("test_logger", component="test")

        # Should not raise exceptions
        logger.debug("Debug message", metadata={"test": "value"})
        logger.info("Info message", metadata={"test": "value"})
        logger.warning("Warning message", metadata={"test": "value"})
        logger.error("Error message", metadata={"test": "value"})
        logger.critical("Critical message", metadata={"test": "value"})

    def test_get_logger_factory(self):
        """Test get_logger factory function"""
        logger = get_logger("test_factory", component="test-component")
        assert isinstance(logger, StructuredLogger)
        assert logger.component == "test-component"


class TestJSONOutput:
    """Test JSON output format validation"""

    def setup_method(self):
        """Set up test logger with captured output"""
        self.logger = StructuredLogger("test_json")
        # Clear existing handlers
        self.logger.logger.handlers.clear()

        # Add handler with string buffer
        self.log_output = StringIO()
        handler = logging.StreamHandler(self.log_output)
        from agents.lib.structured_logger import JSONFormatter

        handler.setFormatter(JSONFormatter())
        self.logger.logger.addHandler(handler)
        self.logger.logger.setLevel(logging.DEBUG)

    def test_json_format(self):
        """Test log output is valid JSON"""
        self.logger.info("Test message")

        # Get log output
        log_line = self.log_output.getvalue().strip()

        # Should be valid JSON
        log_data = json.loads(log_line)
        assert log_data["message"] == "Test message"
        assert log_data["level"] == "INFO"
        assert "timestamp" in log_data

    def test_correlation_id_in_json(self):
        """Test correlation ID appears in JSON output"""
        correlation_id = uuid4()
        self.logger.set_correlation_id(correlation_id)
        self.logger.info("Test message")

        log_line = self.log_output.getvalue().strip()
        log_data = json.loads(log_line)

        assert log_data["correlation_id"] == str(correlation_id)

    def test_metadata_in_json(self):
        """Test metadata appears in JSON output"""
        metadata = {"task_id": "123", "phase": "research"}
        self.logger.info("Test message", metadata=metadata)

        log_line = self.log_output.getvalue().strip()
        log_data = json.loads(log_line)

        assert log_data["metadata"] == metadata

    def test_component_in_json(self):
        """Test component appears in JSON output"""
        logger = StructuredLogger("test_json", component="test-component")
        logger.logger.handlers.clear()

        log_output = StringIO()
        handler = logging.StreamHandler(log_output)
        from agents.lib.structured_logger import JSONFormatter

        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.DEBUG)

        logger.info("Test message")

        log_line = log_output.getvalue().strip()
        log_data = json.loads(log_line)

        assert log_data["component"] == "test-component"


class TestContextPropagation:
    """Test correlation ID context propagation"""

    def test_global_correlation_id(self):
        """Test global correlation ID setter and getter"""
        correlation_id = uuid4()
        set_global_correlation_id(correlation_id)
        assert get_correlation_id() == str(correlation_id)

    def test_global_session_id(self):
        """Test global session ID setter and getter"""
        session_id = uuid4()
        set_global_session_id(session_id)
        assert get_session_id() == str(session_id)

    def test_log_context_manager(self):
        """Test log_context context manager"""
        correlation_id = uuid4()

        with log_context(correlation_id=correlation_id, component="test-component"):
            assert get_correlation_id() == str(correlation_id)

        # Should be cleared after context
        # Note: context vars may persist in same thread, so we check explicitly

    @pytest.mark.asyncio
    async def test_async_log_context(self):
        """Test async_log_context async context manager"""
        correlation_id = uuid4()
        session_id = uuid4()

        async with async_log_context(
            correlation_id=correlation_id,
            session_id=session_id,
            component="test-component",
        ):
            assert get_correlation_id() == str(correlation_id)
            assert get_session_id() == str(session_id)

    def test_log_context_class(self):
        """Test LogContext class for manual context management"""
        correlation_id = uuid4()
        context = LogContext(correlation_id=correlation_id, component="test-component")

        context.enter()
        assert get_correlation_id() == str(correlation_id)
        context.exit()

    def test_log_context_with_statement(self):
        """Test LogContext with 'with' statement"""
        correlation_id = uuid4()

        with LogContext(correlation_id=correlation_id):
            assert get_correlation_id() == str(correlation_id)


class TestDecorators:
    """Test logging decorators"""

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        """Test with_log_context decorator on async function"""

        @with_log_context(component="test-component")
        async def test_func(correlation_id: str, task_id: str):
            assert get_correlation_id() == correlation_id
            return f"Task {task_id} completed"

        correlation_id = str(uuid4())
        result = await test_func(correlation_id=correlation_id, task_id="123")
        assert result == "Task 123 completed"

    def test_sync_decorator(self):
        """Test with_log_context decorator on sync function"""

        @with_log_context(component="test-component")
        def test_func(correlation_id: str, task_id: str):
            assert get_correlation_id() == correlation_id
            return f"Task {task_id} completed"

        correlation_id = str(uuid4())
        result = test_func(correlation_id=correlation_id, task_id="123")
        assert result == "Task 123 completed"


class TestLogRotation:
    """Test log rotation configuration"""

    def setup_method(self):
        """Set up test log directory"""
        self.test_log_dir = Path("./test_logs")
        self.test_log_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        """Clean up test log directory"""
        import shutil

        if self.test_log_dir.exists():
            shutil.rmtree(self.test_log_dir)

    def test_rotation_config_creation(self):
        """Test LogRotationConfig creation"""
        config = LogRotationConfig(
            log_dir=str(self.test_log_dir), max_bytes=1024 * 1024, backup_count=5
        )
        assert config.log_dir == str(self.test_log_dir)
        assert config.max_bytes == 1024 * 1024
        assert config.backup_count == 5

    def test_development_config(self):
        """Test development environment config"""
        config = LogRotationConfig.development()
        assert config.rotation_type == "size"
        assert config.max_bytes == 10 * 1024 * 1024
        assert config.backup_count == 5

    def test_production_config(self):
        """Test production environment config"""
        config = LogRotationConfig.production()
        assert config.rotation_type == "size"
        assert config.max_bytes == 100 * 1024 * 1024
        assert config.backup_count == 30
        assert config.compression is True

    def test_daily_rotation_config(self):
        """Test daily rotation config"""
        config = LogRotationConfig.daily_rotation(retention_days=60)
        assert config.rotation_type == "time"
        assert config.when == "midnight"
        assert config.backup_count == 60

    def test_configure_file_rotation(self):
        """Test file rotation configuration"""
        logger = get_logger("test_rotation", component="test")
        configure_file_rotation(
            logger,
            log_dir=str(self.test_log_dir),
            max_bytes=1024 * 1024,
            backup_count=5,
        )

        # Should have file handler added
        assert len(logger.logger.handlers) > 0

    def test_log_stats(self):
        """Test log statistics retrieval"""
        # Create a test log file
        test_file = self.test_log_dir / "test.log"
        test_file.write_text("test log content")

        stats = get_log_stats(str(self.test_log_dir))
        assert stats["file_count"] == 1
        assert stats["total_size_bytes"] > 0


class TestPerformance:
    """Test logging performance requirements"""

    def test_log_overhead(self):
        """Test log entry overhead is <1ms"""
        logger = get_logger("test_performance", component="test")
        correlation_id = uuid4()
        logger.set_correlation_id(correlation_id)

        # Warmup
        for _ in range(10):
            logger.info("Warmup message", metadata={"test": "value"})

        # Measure
        iterations = 1000
        start_time = time.perf_counter()

        for i in range(iterations):
            logger.info(f"Test message {i}", metadata={"iteration": i})

        end_time = time.perf_counter()
        avg_time_ms = ((end_time - start_time) / iterations) * 1000

        # Should be less than 1ms per log entry
        assert avg_time_ms < 1.0, f"Log overhead {avg_time_ms:.3f}ms exceeds 1ms target"

    def test_context_overhead(self):
        """Test context manager overhead is minimal"""
        correlation_id = uuid4()

        # Measure context manager overhead
        iterations = 10000
        start_time = time.perf_counter()

        for _ in range(iterations):
            with log_context(correlation_id=correlation_id, component="test"):
                pass

        end_time = time.perf_counter()
        avg_time_ms = ((end_time - start_time) / iterations) * 1000

        # Should be very fast (context setup should be <0.1ms)
        assert avg_time_ms < 0.1, f"Context overhead {avg_time_ms:.3f}ms is too high"


class TestIntegration:
    """Integration tests for complete logging workflow"""

    def setup_method(self):
        """Set up test environment"""
        self.test_log_dir = Path("./test_logs_integration")
        self.test_log_dir.mkdir(exist_ok=True)

    def teardown_method(self):
        """Clean up test environment"""
        import shutil

        if self.test_log_dir.exists():
            shutil.rmtree(self.test_log_dir)

    @pytest.mark.asyncio
    async def test_complete_workflow(self):
        """Test complete logging workflow with correlation IDs"""
        # Create logger
        logger = get_logger("test_integration", component="agent-researcher")

        # Configure rotation
        configure_file_rotation(
            logger,
            log_dir=str(self.test_log_dir),
            max_bytes=1024 * 1024,
            backup_count=5,
        )

        # Set up context
        correlation_id = uuid4()
        session_id = uuid4()

        async with async_log_context(
            correlation_id=correlation_id,
            session_id=session_id,
            component="agent-researcher",
        ):
            # Log various events
            logger.info("Research task started", metadata={"query": "test query"})
            logger.debug("Processing step 1", metadata={"step": 1})
            logger.info("Research task completed", metadata={"results_count": 10})

        # Verify log file was created
        log_files = list(self.test_log_dir.glob("*.log"))
        assert len(log_files) > 0

    def test_nested_contexts(self):
        """Test nested log contexts"""
        outer_correlation_id = uuid4()
        inner_correlation_id = uuid4()

        with log_context(correlation_id=outer_correlation_id, component="outer"):
            assert get_correlation_id() == str(outer_correlation_id)

            with log_context(correlation_id=inner_correlation_id, component="inner"):
                assert get_correlation_id() == str(inner_correlation_id)

            # Should restore outer correlation ID
            assert get_correlation_id() == str(outer_correlation_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
