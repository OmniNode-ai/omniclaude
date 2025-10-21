#!/usr/bin/env python3
"""
Mock NodeCompute base class for testing
"""


class NodeCompute:
    """Mock COMPUTE node base class"""

    def __init__(self, container=None):
        self.container = container
