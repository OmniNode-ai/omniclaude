"""
Tracing infrastructure for hook execution tracking.

This module provides PostgreSQL-based tracing for hook executions,
enabling pattern learning and execution analytics.
"""

from .models import (
    ExecutionTrace,
    HookExecution,
    HookExecutionSummary,
    HookMetadata,
    TraceContext as ModelTraceContext,  # Core models; Helper models; Utility functions
    create_new_hook_execution,
    create_new_trace,
    create_trace_context,
    generate_correlation_id,
    generate_session_id,
    parse_hook_from_row,
    parse_trace_from_row,
)
from .postgres_client import PostgresTracingClient
from .tracer import ExecutionTracer, TraceContext as TracerContext


# Re-export TracerContext as the primary TraceContext
# (for use with ExecutionTracer context managers)
TraceContext = TracerContext

__all__ = [
    # Infrastructure
    "PostgresTracingClient",
    "ExecutionTracer",
    # Core models
    "ExecutionTrace",
    "HookExecution",
    # Context managers
    "TraceContext",  # Primary context from tracer.py
    "TracerContext",  # Explicit name for tracer context
    "ModelTraceContext",  # Pydantic model from models.py
    # Helper models
    "HookMetadata",
    "HookExecutionSummary",
    # Utility functions
    "generate_correlation_id",
    "generate_session_id",
    "parse_trace_from_row",
    "parse_hook_from_row",
    "create_trace_context",
    "create_new_trace",
    "create_new_hook_execution",
]
