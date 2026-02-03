#!/usr/bin/env python3
"""Routing Event Client - Kafka-based Agent Routing via RequestResponseWiring.

Thin wrapper around omnibase_infra.runtime.RequestResponseWiring for event-based
agent routing. Migrated from bespoke AIOKafka implementation per OMN-1744.

Public API:
    - RoutingEventClient: Async client for routing requests
    - RoutingEventClientContext: Context manager for lifecycle management
    - route_via_events(): Convenience function with automatic fallback
"""

from __future__ import annotations

import logging
from typing import Any, cast
from uuid import uuid4

from omnibase_core.models.contracts.subcontracts import (
    ModelReplyTopics,
    ModelRequestResponseConfig,
    ModelRequestResponseInstance,
)
from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig
from omnibase_infra.runtime import RequestResponseWiring

from omniclaude.config import settings
from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.errors import EnumCoreErrorCode, OnexError

logger = logging.getLogger(__name__)
_ROUTING_INSTANCE_NAME = "routing"


class RoutingEventClient:
    """Kafka client for routing via RequestResponseWiring from omnibase_infra."""

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        request_timeout_ms: int = 5000,
    ) -> None:
        self.bootstrap_servers = (
            bootstrap_servers or settings.get_effective_kafka_bootstrap_servers()
        )
        if not self.bootstrap_servers:
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="bootstrap_servers required (set KAFKA_BOOTSTRAP_SERVERS)",
                details={"component": "RoutingEventClient"},
            )
        self.request_timeout_ms = request_timeout_ms
        self._event_bus: EventBusKafka | None = None
        self._wiring: RequestResponseWiring | None = None
        self._started = False
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Initialize Kafka event bus and wire request-response pattern."""
        if self._started:
            return
        kafka_env = settings.kafka_environment
        if not kafka_env:
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message="KAFKA_ENVIRONMENT required",
                details={"component": "RoutingEventClient"},
            )

        try:
            config = ModelKafkaEventBusConfig(
                bootstrap_servers=self.bootstrap_servers,
                environment=kafka_env,
                timeout_seconds=max(30, self.request_timeout_ms // 1000 + 10),
            )
            self._event_bus = EventBusKafka(config)
            await self._event_bus.start()

            self._wiring = RequestResponseWiring(
                event_bus=self._event_bus,
                environment=kafka_env,
                app_name="omniclaude",
                bootstrap_servers=self.bootstrap_servers,
            )
            await self._wiring.wire_request_response(
                ModelRequestResponseConfig(
                    instances=[
                        ModelRequestResponseInstance(
                            name=_ROUTING_INSTANCE_NAME,
                            request_topic=TopicBase.ROUTING_REQUESTED,
                            reply_topics=ModelReplyTopics(
                                completed=TopicBase.ROUTING_COMPLETED,
                                failed=TopicBase.ROUTING_FAILED,
                            ),
                            timeout_seconds=self.request_timeout_ms // 1000,
                        )
                    ]
                )
            )
            self._started = True
            self.logger.info("Routing event client started (RequestResponseWiring)")
        except Exception:
            await self.stop()  # cleanup partial state
            raise

    async def stop(self) -> None:
        """Close Kafka connections gracefully."""
        if self._wiring:
            await self._wiring.cleanup()
            self._wiring = None
        if self._event_bus:
            await self._event_bus.stop()
            self._event_bus = None
        self._started = False

    async def health_check(self) -> bool:
        """Check if client is started and ready."""
        return self._started and self._wiring is not None

    async def request_routing(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
        min_confidence: float = 0.6,
        routing_strategy: str = "enhanced_fuzzy_matching",
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Request agent routing via events. Returns list of recommendations."""
        if not self._started or not self._wiring:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message="Client not started. Call start() first.",
                details={"component": "RoutingEventClient"},
            )

        correlation_id = str(uuid4())
        timeout_sec = (timeout_ms or self.request_timeout_ms) // 1000
        payload: dict[str, object] = {
            "correlation_id": correlation_id,
            "event_type": TopicBase.ROUTING_REQUESTED,
            "service": "omniclaude-routing-client",
            "payload": {
                "user_request": user_request,
                "context": context or {},
                "options": {
                    "max_recommendations": max_recommendations,
                    "min_confidence": min_confidence,
                    "routing_strategy": routing_strategy,
                },
            },
        }
        try:
            response = await self._wiring.send_request(
                instance_name=_ROUTING_INSTANCE_NAME,
                payload=payload,
                timeout_seconds=timeout_sec,
            )
            return cast(
                "list[dict[str, Any]]",
                response.get("payload", {}).get("recommendations", []),
            )
        except TimeoutError as e:
            raise TimeoutError(f"Routing request timeout ({correlation_id})") from e
        except Exception as e:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Routing request failed: {e}",
                details={
                    "component": "RoutingEventClient",
                    "correlation_id": correlation_id,
                },
            ) from e


class RoutingEventClientContext:
    """Context manager for automatic client lifecycle management."""

    def __init__(
        self, bootstrap_servers: str | None = None, request_timeout_ms: int = 5000
    ):
        self.client = RoutingEventClient(
            bootstrap_servers=bootstrap_servers, request_timeout_ms=request_timeout_ms
        )

    async def __aenter__(self) -> RoutingEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        await self.client.stop()
        return False


def _format_recommendations(recommendations: list[Any]) -> list[dict[str, Any]]:
    """Convert AgentRecommendation objects to dict format."""
    return [
        {
            "agent_name": r.agent_name,
            "agent_title": r.agent_title,
            "confidence": {
                "total": r.confidence.total,
                "trigger_score": r.confidence.trigger_score,
                "context_score": r.confidence.context_score,
                "capability_score": r.confidence.capability_score,
                "historical_score": r.confidence.historical_score,
                "explanation": r.confidence.explanation,
            },
            "reason": r.reason,
            "definition_path": r.definition_path,
        }
        for r in recommendations
    ]


async def route_via_events(
    user_request: str,
    context: dict[str, Any] | None = None,
    max_recommendations: int = 5,
    min_confidence: float = 0.6,
    timeout_ms: int = 5000,
    fallback_to_local: bool = True,
) -> list[dict[str, Any]]:
    """Convenience function for routing requests. Falls back to local AgentRouter on failure."""
    if not settings.use_event_routing and fallback_to_local:
        logger.info("USE_EVENT_ROUTING=false, using local AgentRouter")
        from .agent_router import AgentRouter

        return _format_recommendations(
            AgentRouter().route(user_request, context or {}, max_recommendations)
        )

    event_error: Exception | None = None
    try:
        async with RoutingEventClientContext(request_timeout_ms=timeout_ms) as client:
            return await client.request_routing(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
                min_confidence=min_confidence,
                timeout_ms=timeout_ms,
            )
    except Exception as e:
        if not fallback_to_local:
            raise
        event_error = e
        logger.warning(f"Event-based routing failed: {e}")

    logger.info("Falling back to local AgentRouter")
    try:
        from .agent_router import AgentRouter

        return _format_recommendations(
            AgentRouter().route(user_request, context or {}, max_recommendations)
        )
    except Exception as fallback_error:
        raise OnexError(
            code=EnumCoreErrorCode.OPERATION_FAILED,
            message="Both event-based and local routing failed",
            details={
                "event_error": str(event_error),
                "local_error": str(fallback_error),
            },
        ) from event_error


__all__ = ["RoutingEventClient", "RoutingEventClientContext", "route_via_events"]
