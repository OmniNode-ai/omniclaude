#!/usr/bin/env python3
"""
Mock omnibase_core.nodes module for testing
"""

from .node_compute import NodeCompute
from .node_effect import NodeEffect
from .node_orchestrator import NodeOrchestrator
from .node_reducer import NodeReducer

__all__ = ["NodeEffect", "NodeCompute", "NodeReducer", "NodeOrchestrator"]
