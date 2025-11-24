"""Intent Dispatcher Module - Phase 1 Reflex Arc Architecture."""

from .intent_classifier import IntentClassifier, IntentContext


# IntentDispatcher will be added in Phase 1.3
# from .intent_dispatcher import IntentDispatcher, DispatchResult

__all__ = [
    "IntentClassifier",
    "IntentContext",
    # "IntentDispatcher",  # Phase 1.3
    # "DispatchResult",    # Phase 1.3
]
