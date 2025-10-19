"""
Structured JSON Logger with Correlation ID Support

High-performance structured logging framework for agent workflow coordination.
Provides JSON-formatted logs with correlation IDs, component tagging, and metadata
support while maintaining <1ms overhead per log entry.

Features:
- Structured JSON output format
- Correlation ID threading
- Component tagging (agent_name, stream, phase)
- Log levels with filtering
- Performance optimized (<1ms overhead)
- Integration with monitoring systems

Usage:
    logger = StructuredLogger("my_component", component="agent-workflow-coordinator")
    logger.set_correlation_id(correlation_id)
    logger.info("Task started", metadata={"task_id": "123", "phase": "research"})
    logger.error("Task failed", metadata={"error": str(e)})
"""

import json
import logging
import sys
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

# Context variables for thread-safe correlation tracking
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
_session_id: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_component: ContextVar[Optional[str]] = ContextVar("component", default=None)


class LogLevel(str, Enum):
    """Standard logging levels"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogRecord:
    """Structured log record for JSON serialization"""

    timestamp: str
    level: str
    logger_name: str
    message: str
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None
    component: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values for compact JSON"""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


class JSONFormatter(logging.Formatter):
    """Custom formatter for JSON log output"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        # Extract custom fields from record
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger_name": record.name,
            "message": record.getMessage(),
        }

        # Add correlation IDs if available
        if hasattr(record, "correlation_id") and record.correlation_id:
            log_data["correlation_id"] = record.correlation_id
        if hasattr(record, "session_id") and record.session_id:
            log_data["session_id"] = record.session_id
        if hasattr(record, "component") and record.component:
            log_data["component"] = record.component
        if hasattr(record, "metadata") and record.metadata:
            log_data["metadata"] = record.metadata

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class StructuredLogger:
    """
    Structured JSON logger with correlation ID support.

    Provides high-performance structured logging with correlation IDs,
    component tagging, and metadata support. Optimized for <1ms overhead
    per log entry.

    Args:
        name: Logger name (typically module name)
        component: Component identifier (e.g., agent name, service name)
        level: Minimum log level to emit (default: INFO)

    Example:
        logger = StructuredLogger(__name__, component="agent-researcher")
        logger.set_correlation_id(correlation_id)
        logger.info("Research started", metadata={"query": query})
    """

    def __init__(
        self,
        name: str,
        component: Optional[str] = None,
        level: LogLevel = LogLevel.INFO,
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.value))

        # Set up JSON formatter if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(JSONFormatter())
            self.logger.addHandler(handler)

        self.component = component
        self.correlation_id: Optional[str] = None
        self.session_id: Optional[str] = None

    def set_correlation_id(self, correlation_id: UUID | str):
        """Set correlation ID for request tracing"""
        self.correlation_id = str(correlation_id)
        _correlation_id.set(self.correlation_id)

    def set_session_id(self, session_id: UUID | str):
        """Set session ID for session tracking"""
        self.session_id = str(session_id)
        _session_id.set(self.session_id)

    def set_component(self, component: str):
        """Set component identifier"""
        self.component = component
        _component.set(component)

    def _log(
        self,
        level: LogLevel,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        exc_info: Optional[Exception] = None,
    ):
        """
        Internal logging method with performance optimization.

        Args:
            level: Log level
            message: Log message
            metadata: Additional structured metadata
            exc_info: Exception information for error logs
        """
        # Get context values (fallback to instance values)
        correlation_id = _correlation_id.get() or self.correlation_id
        session_id = _session_id.get() or self.session_id
        component = _component.get() or self.component

        # Create log record with extra fields
        extra = {
            "correlation_id": correlation_id,
            "session_id": session_id,
            "component": component,
            "metadata": metadata,
        }

        # Map log level to logger method
        log_method = getattr(self.logger, level.value.lower())
        log_method(message, extra=extra, exc_info=exc_info)

    def debug(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log debug message"""
        self._log(LogLevel.DEBUG, message, metadata)

    def info(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log info message"""
        self._log(LogLevel.INFO, message, metadata)

    def warning(self, message: str, metadata: Optional[Dict[str, Any]] = None):
        """Log warning message"""
        self._log(LogLevel.WARNING, message, metadata)

    def error(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        exc_info: Optional[Exception] = None,
    ):
        """Log error message with optional exception info"""
        self._log(LogLevel.ERROR, message, metadata, exc_info)

    def critical(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        exc_info: Optional[Exception] = None,
    ):
        """Log critical message with optional exception info"""
        self._log(LogLevel.CRITICAL, message, metadata, exc_info)


def get_logger(name: str, component: Optional[str] = None) -> StructuredLogger:
    """
    Factory function to create structured logger.

    Args:
        name: Logger name (typically __name__)
        component: Component identifier

    Returns:
        StructuredLogger instance

    Example:
        logger = get_logger(__name__, component="agent-researcher")
    """
    return StructuredLogger(name, component=component)


def set_global_correlation_id(correlation_id: UUID | str):
    """Set correlation ID in global context"""
    _correlation_id.set(str(correlation_id))


def set_global_session_id(session_id: UUID | str):
    """Set session ID in global context"""
    _session_id.set(str(session_id))


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID from context"""
    return _correlation_id.get()


def get_session_id() -> Optional[str]:
    """Get current session ID from context"""
    return _session_id.get()
