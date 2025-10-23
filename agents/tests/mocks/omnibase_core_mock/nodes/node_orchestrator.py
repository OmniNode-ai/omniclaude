#!/usr/bin/env python3
"""
Mock NodeOrchestrator base class for testing
"""


class NodeOrchestrator:
    """Mock ORCHESTRATOR node base class"""

    def __init__(self, container=None):
        self.container = container
