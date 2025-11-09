"""
ONEX nodes for Intelligent Context Proxy.

Includes:
- NodeContextRequestReducer: FSM state tracker (consumes events, updates state, emits persistence intents)
- NodeContextProxyOrchestrator: Workflow coordinator (reads FSM state, publishes domain events)
- NodeIntelligenceQueryEffect: Intelligence queries via Kafka (reuses ManifestInjector)
- NodeContextRewriterCompute: Pure context rewriting logic
- NodeAnthropicForwarderEffect: HTTP forwarding to Anthropic API
"""

from .node_reducer import NodeContextRequestReducer
from .node_orchestrator import NodeContextProxyOrchestrator

__all__ = [
    "NodeContextRequestReducer",
    "NodeContextProxyOrchestrator",
]
