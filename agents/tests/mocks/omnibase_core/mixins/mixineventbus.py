#!/usr/bin/env python3
"""Mock MixinEventBus for testing"""


class MixinEventBus:
    """Mock event bus mixin"""

    async def publish_event(self, topic: str, event: dict):
        """Publish event to topic"""
        pass

    async def subscribe_event(self, topic: str, handler):
        """Subscribe to topic"""
        pass
