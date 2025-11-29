"""
Routing Request Handler.

Processes routing requests from Kafka events and generates routing recommendations
using the AgentRouter. Follows ONEX v2.0 patterns for event processing.

Event Flow:
    1. Consume routing request event from Kafka
    2. Extract user request and context
    3. Call AgentRouter.route() to get recommendations
    4. Publish routing response event to Kafka
    5. Log routing decision to PostgreSQL (async, non-blocking)

Implementation: Phase 1 & 2 - Event-Driven Routing with PostgreSQL Logging
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, Dict, Optional


# Import AgentRouter (PYTHONPATH includes /app/lib via Dockerfile)
try:
    from agent_router import AgentRouter

    AGENT_ROUTER_AVAILABLE = True
except ImportError:
    AGENT_ROUTER_AVAILABLE = False
    AgentRouter = None  # type: ignore

from .postgres_logger import PostgresLogger


logger = logging.getLogger(__name__)


class RoutingHandler:
    """
    Handler for routing request events.

    Integrates with AgentRouter to provide intelligent agent selection
    based on user requests and context. Logs all routing decisions to
    PostgreSQL for audit trail and analytics.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize routing handler.

        Args:
            config: Optional configuration dict with PostgreSQL settings:
                - postgres_host
                - postgres_port
                - postgres_database
                - postgres_user
                - postgres_password
                - postgres_pool_min_size
                - postgres_pool_max_size
        """
        self._config = config or {}
        self._agent_router: Optional[AgentRouter] = None
        self._postgres_logger: Optional[PostgresLogger] = None
        self._initialized = False
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_routing_time_ms = 0.0

    async def initialize(self) -> None:
        """
        Initialize AgentRouter, PostgresLogger, and dependencies.

        Raises:
            RuntimeError: If AgentRouter is not available or initialization fails
        """
        if not AGENT_ROUTER_AVAILABLE:
            raise RuntimeError(
                "AgentRouter not available. Ensure agents/lib/agent_router.py exists."
            )

        logger.info("Initializing RoutingHandler...")

        # Initialize AgentRouter with registry path from config
        try:
            registry_path = self._config.get(
                "agent_registry_path", "/agents/onex/agent-registry.yaml"
            )
            cache_ttl = self._config.get("cache_ttl_seconds", 3600)

            logger.info(
                "Initializing AgentRouter...",
                extra={
                    "registry_path": registry_path,
                    "cache_ttl": cache_ttl,
                },
            )
            self._agent_router = AgentRouter(
                registry_path=registry_path,
                cache_ttl=cache_ttl,
            )
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

        # Initialize PostgresLogger (optional - don't fail if DB unavailable)
        try:
            if self._config.get("postgres_password"):
                logger.info("Initializing PostgresLogger...")
                self._postgres_logger = PostgresLogger(
                    host=self._config.get("postgres_host", "192.168.86.200"),
                    port=self._config.get("postgres_port", 5436),
                    database=self._config.get("postgres_database", "omninode_bridge"),
                    user=self._config.get("postgres_user", "postgres"),
                    password=self._config["postgres_password"],
                    pool_min_size=self._config.get("postgres_pool_min_size", 2),
                    pool_max_size=self._config.get("postgres_pool_max_size", 10),
                )
                await self._postgres_logger.initialize()
                logger.info("PostgresLogger initialized successfully")
            else:
                logger.warning(
                    "PostgreSQL password not provided - routing decisions will not be logged to database"
                )
        except Exception as e:
            # Don't fail handler initialization if DB logger fails
            logger.error(
                f"Failed to initialize PostgresLogger (continuing without DB logging): {e}",
                exc_info=True,
            )
            self._postgres_logger = None

        self._initialized = True
        logger.info("RoutingHandler initialized successfully")

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
                agent_title = "Polymorphic Agent"
                confidence = 0.0
                reason = "No specialized agents matched the request"
                definition_path = (
                    self._config.get("agent_definitions_path", "/agents/onex")
                    + "/polymorphic-agent.yaml"
                )
                alternatives = []
            else:
                best_rec = recommendations[0]
                selected_agent = best_rec.agent_name
                agent_title = best_rec.agent_title
                confidence = best_rec.confidence.total
                reason = best_rec.reason
                definition_path = best_rec.definition_path

                # Format alternatives
                alternatives = [
                    {
                        "agent_name": rec.agent_name,
                        "agent_title": rec.agent_title,
                        "confidence": rec.confidence.total,
                        "reason": rec.reason,
                        "definition_path": rec.definition_path,
                    }
                    for rec in recommendations[1:]
                ]

            # Build response event
            response = {
                "correlation_id": correlation_id,
                "selected_agent": selected_agent,
                "agent_title": agent_title,
                "confidence": confidence,
                "reason": reason,
                "definition_path": definition_path,
                "alternatives": alternatives,
                "routing_time_ms": int(round(routing_time_ms)),
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

            # Log to database (non-blocking)
            if self._postgres_logger:
                asyncio.create_task(
                    self._log_routing_decision_async(
                        correlation_id=correlation_id,
                        user_request=user_request,
                        selected_agent=selected_agent,
                        confidence=confidence,
                        reason=reason,
                        alternatives=alternatives,
                        routing_time_ms=routing_time_ms,
                        routing_strategy=response["routing_strategy"],
                        context=context,
                    )
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

    async def _log_routing_decision_async(
        self,
        correlation_id: str,
        user_request: str,
        selected_agent: str,
        confidence: float,
        reason: str,
        alternatives: list,
        routing_time_ms: float,
        routing_strategy: str,
        context: dict,
    ) -> None:
        """
        Helper method to log routing decision asynchronously.

        This is called as a background task and will not block routing response.
        All errors are caught and logged internally by PostgresLogger.
        """
        try:
            await self._postgres_logger.log_routing_decision(
                correlation_id=correlation_id,
                user_request=user_request,
                selected_agent=selected_agent,
                confidence_score=confidence,
                routing_strategy=routing_strategy,
                routing_time_ms=routing_time_ms,
                alternatives=alternatives,
                reasoning=reason,
                context=context,
                # Optional fields - could be extracted from context if available
                project_path=context.get("project_path"),
                project_name=context.get("project_name"),
                claude_session_id=context.get("claude_session_id"),
            )
        except Exception as e:
            # Should never happen (PostgresLogger handles all errors internally)
            # but log just in case
            logger.error(
                f"Unexpected error in background logging task: {e}",
                extra={"correlation_id": correlation_id},
                exc_info=True,
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
            - postgres_logger_metrics: PostgresLogger metrics (if available)
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

        metrics = {
            "request_count": self._request_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": round(success_rate, 2),
            "avg_routing_time_ms": round(avg_routing_time_ms, 2),
        }

        # Include PostgresLogger metrics if available
        if self._postgres_logger:
            metrics["postgres_logger_metrics"] = self._postgres_logger.get_metrics()

        return metrics

    async def shutdown(self) -> None:
        """Shutdown routing handler and cleanup resources."""
        logger.info(
            "Shutting down routing handler",
            extra={
                "final_metrics": self.get_metrics(),
            },
        )

        # Shutdown PostgresLogger if initialized
        if self._postgres_logger:
            try:
                await self._postgres_logger.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down PostgresLogger: {e}", exc_info=True)

        self._initialized = False
        self._agent_router = None
        self._postgres_logger = None
