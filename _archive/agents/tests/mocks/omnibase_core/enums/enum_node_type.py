#!/usr/bin/env python3
"""
Mock omnibase_core.enums.enum_node_type module for testing Phase 5 components
"""

from enum import Enum


class EnumNodeType(str, Enum):
    """Mock node type enum for testing"""

    EFFECT = "EFFECT"
    COMPUTE = "COMPUTE"
    REDUCER = "REDUCER"
    ORCHESTRATOR = "ORCHESTRATOR"
