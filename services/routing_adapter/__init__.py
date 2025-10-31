"""
Routing Adapter Service Package.

Event-driven service for agent routing requests using Kafka message bus.
Follows ONEX v2.0 architecture patterns.

Components:
    - RoutingAdapterService: Main service with Kafka consumer/producer
    - RoutingHandler: Request processing logic with AgentRouter
    - RoutingAdapterConfig: Configuration management

Usage:
    from services.routing_adapter import RoutingAdapterService

    # Create and run service
    service = RoutingAdapterService()
    await service.initialize()
    # Service runs event consumption loop automatically

Implementation: Phase 1 - Event-Driven Routing Adapter
"""

from .config import RoutingAdapterConfig, get_config
from .routing_adapter_service import RoutingAdapterService
from .routing_handler import RoutingHandler

__all__ = [
    "RoutingAdapterService",
    "RoutingHandler",
    "RoutingAdapterConfig",
    "get_config",
]

__version__ = "1.0.0"
