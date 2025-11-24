"""
Claude Hooks Services Package

Background services for processing hook events and managing hook lifecycle.

Modules:
- hook_event_processor: Main event processor service
- event_handlers: Event handler registry and implementations
"""

from .event_handlers import (
    EventHandler,
    EventHandlerRegistry,
    HandlerResult,
    register_custom_handler,
)
from .hook_event_processor import HookEventProcessor


__all__ = [
    "HookEventProcessor",
    "EventHandlerRegistry",
    "HandlerResult",
    "EventHandler",
    "register_custom_handler",
]
