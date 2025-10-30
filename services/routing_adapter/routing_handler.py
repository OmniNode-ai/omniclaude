"""
Routing Request Handler.

Processes routing requests from Kafka events and generates routing recommendations
using the AgentRouter. Follows ONEX v2.0 patterns for event processing.

Event Flow:
    1. Consume routing request event from Kafka
    2. Extract user request and context
    3. Call AgentRouter.route() to get recommendations
    4. Publish routing response event to Kafka
    5. Log routing decision to PostgreSQL (via separate event)

Implementation: Phase 1 - Event-Driven Routing Adapter
"""

import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any, Optional

# Add agents/lib to path for AgentRouter import
sys.path.insert(0, "/Users/jonah/.claude/agents/lib")

try:
    from agent_router import AgentRouter

    AGENT_ROUTER_AVAILABLE = True
except ImportError:
    AGENT_ROUTER_AVAILABLE = False
    AgentRouter = None  # type: ignore

logger = logging.getLogger(__name__)


class RoutingHandler:
    """
    Handler for routing request events.

    Integrates with AgentRouter to provide intelligent agent selection
    based on user requests and context.
    """

    def __init__(self):
        """Initialize routing handler."""
        self._agent_router: Optional[AgentRouter] = None
        self._initialized = False
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_routing_time_ms = 0.0

    async def initialize(self) -> None:
        """
        Initialize AgentRouter and dependencies.

        Raises:
            RuntimeError: If AgentRouter is not available
        """
        if not AGENT_ROUTER_AVAILABLE:
            raise RuntimeError(
                "AgentRouter not available. Ensure agents/lib/agent_router.py exists."
            )

        logger.info("Initializing AgentRouter...")
        try:
            self._agent_router = AgentRouter()
            self._initialized = True
            logger.info(
                "AgentRouter initialized successfully",
                extra={
                    "registry_loaded": True,
                    "capabilities_indexed": True,
                },
            )
        except Exception as e:
            logger.error(f"Failed to initialize AgentRouter: {e}", exc_info=True)
            raise RuntimeError(f"AgentRouter initialization failed: {e}") from e

    async def handle_routing_request(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Handle routing request event and generate routing response.

        Args:
            event: Kafka event containing routing request
                Required fields:
                - correlation_id (str): Request correlation ID
                - user_request (str): User's request text
                - context (dict, optional): Additional context
                - max_recommendations (int, optional): Max agents to return (default: 3)

        Returns:
            Routing response event dict with:
            - correlation_id: Same as request
            - selected_agent: Best agent recommendation
            - confidence: Confidence score (0.0-1.0)
            - reason: Selection reasoning
            - alternatives: Alternative agent recommendations
            - routing_time_ms: Time taken for routing
            - timestamp: ISO timestamp

        Raises:
            ValueError: If request validation fails
            RuntimeError: If routing fails
        """
        if not self._initialized:
            raise RuntimeError(
                "RoutingHandler not initialized. Call initialize() first."
            )

        # Track metrics
        self._request_count += 1
        start_time = time.perf_counter()

        try:
            # Validate request
            correlation_id = event.get("correlation_id")
            if not correlation_id:
                raise ValueError("Missing required field: correlation_id")

            user_request = event.get("user_request")
            if not user_request:
                raise ValueError("Missing required field: user_request")

            context = event.get("context", {})
            max_recommendations = event.get("max_recommendations", 3)

            logger.info(
                "Processing routing request",
                extra={
                    "correlation_id": correlation_id,
                    "user_request_length": len(user_request),
                    "context_keys": list(context.keys()) if context else [],
                    "max_recommendations": max_recommendations,
                },
            )

            # Call AgentRouter
            routing_start = time.perf_counter()
            recommendations = self._agent_router.route(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
            )
            routing_time_ms = (time.perf_counter() - routing_start) * 1000

            # Extract best recommendation
            if not recommendations or len(recommendations) == 0:
                # No recommendations - fallback to polymorphic-agent
                selected_agent = "polymorphic-agent"
                confidence = 0.0
                reason = "No specialized agents matched the request"
                alternatives = []
            else:
                best_rec = recommendations[0]
                selected_agent = best_rec.agent_name
                confidence = best_rec.confidence.total
                reason = best_rec.reason

                # Format alternatives
                alternatives = [
                    {
                        "agent_name": rec.agent_name,
                        "agent_title": rec.agent_title,
                        "confidence": rec.confidence.total,
                        "reason": rec.reason,
                    }
                    for rec in recommendations[1:]
                ]

            # Build response event
            response = {
                "correlation_id": correlation_id,
                "selected_agent": selected_agent,
                "confidence": confidence,
                "reason": reason,
                "alternatives": alternatives,
                "routing_time_ms": round(routing_time_ms, 2),
                "timestamp": datetime.now(UTC).isoformat(),
                "routing_strategy": "enhanced_fuzzy_matching",
            }

            # Update metrics
            self._success_count += 1
            self._total_routing_time_ms += routing_time_ms

            logger.info(
                "Routing request completed successfully",
                extra={
                    "correlation_id": correlation_id,
                    "selected_agent": selected_agent,
                    "confidence": confidence,
                    "routing_time_ms": round(routing_time_ms, 2),
                    "alternatives_count": len(alternatives),
                },
            )

            return response

        except ValueError as e:
            # Validation error
            self._error_count += 1
            logger.warning(
                f"Routing request validation failed: {e}",
                extra={"correlation_id": event.get("correlation_id"), "error": str(e)},
            )
            raise

        except Exception as e:
            # Routing error
            self._error_count += 1
            logger.error(
                f"Routing request failed: {e}",
                extra={"correlation_id": event.get("correlation_id")},
                exc_info=True,
            )
            raise RuntimeError(f"Routing failed: {e}") from e

        finally:
            # Track total request time
            total_time_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                "Request processing completed",
                extra={
                    "total_time_ms": round(total_time_ms, 2),
                    "request_count": self._request_count,
                },
            )

    def get_metrics(self) -> dict[str, Any]:
        """
        Get routing handler metrics.

        Returns:
            Dictionary of metrics:
            - request_count: Total requests processed
            - success_count: Successful requests
            - error_count: Failed requests
            - success_rate: Success percentage
            - avg_routing_time_ms: Average routing time
        """
        success_rate = (
            (self._success_count / self._request_count * 100)
            if self._request_count > 0
            else 0.0
        )

        avg_routing_time_ms = (
            (self._total_routing_time_ms / self._success_count)
            if self._success_count > 0
            else 0.0
        )

        return {
            "request_count": self._request_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": round(success_rate, 2),
            "avg_routing_time_ms": round(avg_routing_time_ms, 2),
        }

    async def shutdown(self) -> None:
        """Shutdown routing handler and cleanup resources."""
        logger.info(
            "Shutting down routing handler",
            extra={
                "final_metrics": self.get_metrics(),
            },
        )
        self._initialized = False
        self._agent_router = None
