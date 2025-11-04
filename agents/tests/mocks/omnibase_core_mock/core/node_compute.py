#!/usr/bin/env python3
"""
Mock omnibase_core.core.node_compute module for testing Phase 5 components
"""

from typing import Any


class NodeCompute:
    """Mock base Compute node class"""

    async def execute_compute(self, contract: Any) -> Any:
        """Execute compute operation"""
        pass
