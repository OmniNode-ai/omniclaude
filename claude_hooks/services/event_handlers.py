#!/usr/bin/env python3
"""
Event Handlers for Hook Event Processor

Registry and handlers for different event types (PreToolUse, PostToolUse, UserPromptSubmit, etc.)
Each handler processes events based on source/action and returns a HandlerResult.

Handler Signature:
    def handler(event: Dict[str, Any]) -> HandlerResult

Event Structure:
    {
        "id": UUID,
        "source": str (e.g., "PreToolUse", "PostToolUse", "UserPromptSubmit"),
        "action": str (e.g., "tool_invocation", "tool_completion", "prompt_submitted"),
        "resource": str,
        "resource_id": str,
        "payload": dict (JSONB),
        "metadata": dict (JSONB),
        "processed": bool,
        "processing_errors": list[str],
        "retry_count": int,
        "created_at": datetime,
        "processed_at": datetime | None
    }
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    """Result of event handler execution."""

    success: bool
    message: str
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Ensure metadata is a dict."""
        if self.metadata is None:
            self.metadata = {}


# Type alias for event handlers
EventHandler = Callable[[Dict[str, Any]], HandlerResult]


class EventHandlerRegistry:
    """
    Registry for event handlers.

    Maps (source, action) tuples to handler functions.
    Supports wildcard matching for flexible routing.
    """

    def __init__(self):
        """Initialize the handler registry."""
        self._handlers: Dict[tuple[str, str], EventHandler] = {}
        self._wildcard_handlers: Dict[str, EventHandler] = {}

        # Register default handlers
        self._register_default_handlers()

    def _register_default_handlers(self):
        """Register default handlers for common event types."""
        # PreToolUse handlers
        self.register("PreToolUse", "tool_invocation", handle_pretooluse_invocation)

        # PostToolUse handlers
        self.register("PostToolUse", "tool_completion", handle_posttooluse_completion)

        # UserPromptSubmit handlers
        self.register(
            "UserPromptSubmit", "prompt_submitted", handle_userprompt_submitted
        )

        # Stop/SessionEnd handlers (future expansion)
        self.register("Stop", "session_stopped", handle_session_stopped)
        self.register("SessionEnd", "session_ended", handle_session_ended)

        # Wildcard handler for unknown events
        self.register_wildcard("*", handle_unknown_event)

        logger.info(f"Registered {len(self._handlers)} default event handlers")

    def register(self, source: str, action: str, handler: EventHandler):
        """
        Register an event handler for a specific source/action combination.

        Args:
            source: Event source (e.g., "PreToolUse")
            action: Event action (e.g., "tool_invocation")
            handler: Handler function
        """
        key = (source, action)
        self._handlers[key] = handler
        logger.debug(f"Registered handler for {source}/{action}: {handler.__name__}")

    def register_wildcard(self, source: str, handler: EventHandler):
        """
        Register a wildcard handler for all actions from a source.

        Args:
            source: Event source or "*" for all sources
            handler: Handler function
        """
        self._wildcard_handlers[source] = handler
        logger.debug(f"Registered wildcard handler for {source}: {handler.__name__}")

    def get_handler(self, source: str, action: str) -> Optional[EventHandler]:
        """
        Get handler for a specific source/action combination.

        Lookup order:
        1. Exact match (source, action)
        2. Wildcard for source (*any action)
        3. Global wildcard (*)

        Args:
            source: Event source
            action: Event action

        Returns:
            Handler function or None if no handler found
        """
        # Try exact match
        key = (source, action)
        if key in self._handlers:
            return self._handlers[key]

        # Try wildcard for source
        if source in self._wildcard_handlers:
            return self._wildcard_handlers[source]

        # Try global wildcard
        if "*" in self._wildcard_handlers:
            return self._wildcard_handlers["*"]

        return None


# ============================================================================
# Event Handlers
# ============================================================================


def handle_pretooluse_invocation(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle PreToolUse / tool_invocation events.

    These events are logged when a tool is about to be invoked,
    including quality checks and RAG queries.

    Processing:
    - Extract tool name and input from payload
    - Log tool usage metrics
    - Track quality check results if present
    """
    try:
        payload = event.get("payload", {})
        tool_name = payload.get("tool_name", "unknown")
        quality_check = payload.get("quality_check")

        logger.info(
            f"PreToolUse event: tool={tool_name}, "
            f"quality_check={'yes' if quality_check else 'no'}"
        )

        # Future: Send metrics to monitoring system
        # Future: Trigger alerts for quality check failures

        return HandlerResult(
            success=True,
            message=f"Processed PreToolUse for {tool_name}",
            metadata={
                "tool_name": tool_name,
                "quality_check_performed": quality_check is not None,
            },
        )

    except Exception as e:
        logger.error(f"Error handling PreToolUse event: {e}", exc_info=True)
        return HandlerResult(
            success=False, message="Failed to process PreToolUse event", error=str(e)
        )


def handle_posttooluse_completion(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle PostToolUse / tool_completion events.

    These events are logged after tool execution completes,
    including auto-fix information.

    Processing:
    - Extract tool name and output
    - Track auto-fix applications
    - Monitor file modifications
    """
    try:
        payload = event.get("payload", {})
        tool_name = payload.get("tool_name", "unknown")
        file_path = payload.get("file_path")
        auto_fix_applied = payload.get("auto_fix_details") is not None

        logger.info(
            f"PostToolUse event: tool={tool_name}, "
            f"file={file_path}, auto_fix={auto_fix_applied}"
        )

        # Future: Track auto-fix success rates
        # Future: Update file modification history

        return HandlerResult(
            success=True,
            message=f"Processed PostToolUse for {tool_name}",
            metadata={
                "tool_name": tool_name,
                "file_path": file_path,
                "auto_fix_applied": auto_fix_applied,
            },
        )

    except Exception as e:
        logger.error(f"Error handling PostToolUse event: {e}", exc_info=True)
        return HandlerResult(
            success=False, message="Failed to process PostToolUse event", error=str(e)
        )


def handle_userprompt_submitted(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle UserPromptSubmit / prompt_submitted events.

    These events are logged when a user submits a prompt,
    including agent detection information.

    Processing:
    - Extract prompt and agent detection info
    - Track agent usage patterns
    - Monitor detection confidence and methods
    """
    try:
        payload = event.get("payload", {})
        prompt_preview = payload.get("prompt_preview", "")
        agent_detected = payload.get("agent_detected")
        detection_method = payload.get("detection_method")
        confidence = payload.get("confidence")

        logger.info(
            f"UserPromptSubmit event: agent={agent_detected}, "
            f"method={detection_method}, confidence={confidence}"
        )

        # Future: Update agent usage statistics
        # Future: Improve agent detection based on patterns

        return HandlerResult(
            success=True,
            message="Processed UserPromptSubmit event",
            metadata={
                "agent_detected": agent_detected,
                "detection_method": detection_method,
                "confidence": confidence,
                "prompt_length": len(prompt_preview),
            },
        )

    except Exception as e:
        logger.error(f"Error handling UserPromptSubmit event: {e}", exc_info=True)
        return HandlerResult(
            success=False,
            message="Failed to process UserPromptSubmit event",
            error=str(e),
        )


def handle_session_stopped(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle Stop / session_stopped events.

    These events are logged when a Claude Code session is stopped.

    Processing:
    - Log session end
    - Clean up session-specific resources
    """
    try:
        logger.info("Stop event: session stopped")

        # Future: Clean up session resources
        # Future: Generate session summary

        return HandlerResult(
            success=True, message="Processed Stop event", metadata={"event": "stop"}
        )

    except Exception as e:
        logger.error(f"Error handling Stop event: {e}", exc_info=True)
        return HandlerResult(
            success=False, message="Failed to process Stop event", error=str(e)
        )


def handle_session_ended(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle SessionEnd / session_ended events.

    These events are logged when a Claude Code session ends normally.

    Processing:
    - Log session completion
    - Archive session data
    """
    try:
        logger.info("SessionEnd event: session ended")

        # Future: Archive session data
        # Future: Generate session report

        return HandlerResult(
            success=True,
            message="Processed SessionEnd event",
            metadata={"event": "session_end"},
        )

    except Exception as e:
        logger.error(f"Error handling SessionEnd event: {e}", exc_info=True)
        return HandlerResult(
            success=False, message="Failed to process SessionEnd event", error=str(e)
        )


def handle_unknown_event(event: Dict[str, Any]) -> HandlerResult:
    """
    Handle unknown events (wildcard handler).

    Logs the event for future analysis but marks as successfully processed
    to avoid infinite retries.

    Args:
        event: Event dictionary

    Returns:
        HandlerResult with success=True (to avoid retries)
    """
    source = event.get("source", "unknown")
    action = event.get("action", "unknown")

    logger.warning(
        f"Unknown event type: {source}/{action} (event_id={event.get('id')})"
    )

    # Log payload for analysis
    logger.debug(f"Unknown event payload: {event.get('payload', {})}")

    return HandlerResult(
        success=True,  # Don't retry unknown events
        message=f"Unknown event type: {source}/{action}",
        metadata={"source": source, "action": action, "unknown": True},
    )


# ============================================================================
# Custom Handler Registration (for extensions)
# ============================================================================


def register_custom_handler(
    registry: EventHandlerRegistry,
    source: str,
    action: str,
    handler: EventHandler,
):
    """
    Register a custom event handler.

    Example:
        def my_custom_handler(event: Dict[str, Any]) -> HandlerResult:
            # Process event
            return HandlerResult(success=True, message="Custom processing")

        register_custom_handler(registry, "MySource", "my_action", my_custom_handler)

    Args:
        registry: EventHandlerRegistry instance
        source: Event source
        action: Event action
        handler: Handler function
    """
    registry.register(source, action, handler)
    logger.info(f"Registered custom handler for {source}/{action}")
