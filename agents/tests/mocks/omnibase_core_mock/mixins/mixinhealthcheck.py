#!/usr/bin/env python3
"""Mock MixinHealthCheck for testing"""


class MixinHealthCheck:
    """Mock health check mixin"""

    async def get_health_status(self):
        """Get health status"""
        return {"status": "healthy"}
