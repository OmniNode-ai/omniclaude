"""
Pydantic models for Intelligent Context Proxy.

Includes:
- Event envelope models (Kafka event structure)
- FSM state models (workflow state tracking)
- ONEX contracts (node input/output contracts)
- Request/response payloads (domain models)
"""

from .event_envelope import (
    BaseEventEnvelope,
    ContextRequestReceivedEvent,
    ContextQueryRequestedEvent,
    ContextQueryCompletedEvent,
    ContextRewriteRequestedEvent,
    ContextRewriteCompletedEvent,
    ContextForwardRequestedEvent,
    ContextForwardCompletedEvent,
    ContextResponseCompletedEvent,
    ContextFailedEvent,
    PersistStateIntent,
)
from .fsm_state import FSMState, FSMTransition, FSMStateManager
from .contracts import (
    ProxyReducerInput,
    ProxyReducerOutput,
    ProxyOrchestratorInput,
    ProxyOrchestratorOutput,
)

__all__ = [
    # Event envelopes
    "BaseEventEnvelope",
    "ContextRequestReceivedEvent",
    "ContextQueryRequestedEvent",
    "ContextQueryCompletedEvent",
    "ContextRewriteRequestedEvent",
    "ContextRewriteCompletedEvent",
    "ContextForwardRequestedEvent",
    "ContextForwardCompletedEvent",
    "ContextResponseCompletedEvent",
    "ContextFailedEvent",
    "PersistStateIntent",
    # FSM state
    "FSMState",
    "FSMTransition",
    "FSMStateManager",
    # Contracts
    "ProxyReducerInput",
    "ProxyReducerOutput",
    "ProxyOrchestratorInput",
    "ProxyOrchestratorOutput",
]
