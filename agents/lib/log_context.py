"""
Logging Context Propagation

Provides context managers and decorators for automatic correlation ID and
session ID propagation across async workflows. Ensures all logs within a
context are tagged with the same correlation IDs for complete traceability.

Features:
- Automatic correlation ID propagation
- Session ID tracking
- Component tagging
- Async context manager support
- Decorator support for functions
- Thread-safe context isolation

Usage:
    # Context manager
    async with log_context(correlation_id=uuid4(), component="agent-researcher"):
        logger.info("Inside context")  # Automatically tagged

    # Decorator
    @with_log_context(component="agent-researcher")
    async def research_task(correlation_id: UUID):
        logger.info("Task started")  # Automatically tagged
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Callable, Optional
from uuid import UUID

from .structured_logger import _component, _correlation_id, _session_id


@contextmanager
def log_context(
    correlation_id: Optional[UUID | str] = None,
    session_id: Optional[UUID | str] = None,
    component: Optional[str] = None,
):
    """
    Context manager for log context propagation (synchronous).

    Sets correlation ID, session ID, and component in the context for
    the duration of the with block. All logs emitted within the context
    will automatically include these fields.

    Args:
        correlation_id: Correlation ID for request tracing
        session_id: Session ID for session tracking
        component: Component identifier (e.g., agent name)

    Example:
        with log_context(correlation_id=uuid4(), component="agent-researcher"):
            logger.info("Research started")  # Automatically tagged
    """
    # Store previous values
    prev_correlation_id = _correlation_id.get()
    prev_session_id = _session_id.get()
    prev_component = _component.get()

    # Set new values
    if correlation_id:
        _correlation_id.set(str(correlation_id))
    if session_id:
        _session_id.set(str(session_id))
    if component:
        _component.set(component)

    try:
        yield
    finally:
        # Restore previous values
        _correlation_id.set(prev_correlation_id)
        _session_id.set(prev_session_id)
        _component.set(prev_component)


@asynccontextmanager
async def async_log_context(
    correlation_id: Optional[UUID | str] = None,
    session_id: Optional[UUID | str] = None,
    component: Optional[str] = None,
):
    """
    Async context manager for log context propagation.

    Sets correlation ID, session ID, and component in the context for
    the duration of the async with block. All logs emitted within the
    context will automatically include these fields.

    Args:
        correlation_id: Correlation ID for request tracing
        session_id: Session ID for session tracking
        component: Component identifier (e.g., agent name)

    Example:
        async with async_log_context(correlation_id=uuid4(), component="agent-researcher"):
            await research_task()  # All logs automatically tagged
    """
    # Store previous values
    prev_correlation_id = _correlation_id.get()
    prev_session_id = _session_id.get()
    prev_component = _component.get()

    # Set new values
    if correlation_id:
        _correlation_id.set(str(correlation_id))
    if session_id:
        _session_id.set(str(session_id))
    if component:
        _component.set(component)

    try:
        yield
    finally:
        # Restore previous values
        _correlation_id.set(prev_correlation_id)
        _session_id.set(prev_session_id)
        _component.set(prev_component)


def with_log_context(
    component: Optional[str] = None,
    correlation_id_param: str = "correlation_id",
    session_id_param: str = "session_id",
):
    """
    Decorator for automatic log context propagation.

    Automatically sets up log context from function parameters. Looks for
    parameters named by correlation_id_param and session_id_param.

    Args:
        component: Fixed component name for all calls
        correlation_id_param: Name of correlation_id parameter (default: "correlation_id")
        session_id_param: Name of session_id parameter (default: "session_id")

    Example:
        @with_log_context(component="agent-researcher")
        async def research_task(correlation_id: UUID, query: str):
            logger.info("Research started", metadata={"query": query})
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Extract correlation_id and session_id from kwargs
            correlation_id = kwargs.get(correlation_id_param)
            session_id = kwargs.get(session_id_param)

            # Set up context
            async with async_log_context(
                correlation_id=correlation_id,
                session_id=session_id,
                component=component,
            ):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Extract correlation_id and session_id from kwargs
            correlation_id = kwargs.get(correlation_id_param)
            session_id = kwargs.get(session_id_param)

            # Set up context
            with log_context(
                correlation_id=correlation_id,
                session_id=session_id,
                component=component,
            ):
                return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class LogContext:
    """
    Log context manager for manual context setup.

    Provides a simple interface for setting up log context without
    using context managers or decorators.

    Example:
        context = LogContext(correlation_id=uuid4(), component="agent-researcher")
        context.enter()
        try:
            logger.info("Task started")
        finally:
            context.exit()
    """

    def __init__(
        self,
        correlation_id: Optional[UUID | str] = None,
        session_id: Optional[UUID | str] = None,
        component: Optional[str] = None,
    ):
        self.correlation_id = str(correlation_id) if correlation_id else None
        self.session_id = str(session_id) if session_id else None
        self.component = component

        self.prev_correlation_id: Optional[str] = None
        self.prev_session_id: Optional[str] = None
        self.prev_component: Optional[str] = None

    def enter(self):
        """Enter the log context"""
        # Store previous values
        self.prev_correlation_id = _correlation_id.get()
        self.prev_session_id = _session_id.get()
        self.prev_component = _component.get()

        # Set new values
        if self.correlation_id:
            _correlation_id.set(self.correlation_id)
        if self.session_id:
            _session_id.set(self.session_id)
        if self.component:
            _component.set(self.component)

    def exit(self):
        """Exit the log context and restore previous values"""
        _correlation_id.set(self.prev_correlation_id)
        _session_id.set(self.prev_session_id)
        _component.set(self.prev_component)

    def __enter__(self):
        """Context manager entry"""
        self.enter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.exit()
        return False
