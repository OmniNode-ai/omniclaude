#!/usr/bin/env python3
"""
Mock omnibase_core.core.node_effect module for testing Phase 5 components
"""

from typing import Any, Dict


class NodeEffect:
    """Mock base Effect node class"""

    async def execute_effect(self, contract: Any) -> Any:
        """Execute effect operation"""
        pass


class ModelEffectInput:
    """Mock Effect input model"""

    def __init__(self, data: Dict[str, Any] = None):
        self.data = data or {}


class ModelEffectOutput:
    """Mock Effect output model"""

    def __init__(self, result: Any = None, success: bool = True):
        self.result = result
        self.success = success
