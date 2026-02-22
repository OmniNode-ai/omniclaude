"""
NodeAnthropicForwarderEffect - HTTP Forwarding to Anthropic API

This node forwards rewritten requests to Anthropic's API with OAuth passthrough.

Type: ONEX Effect Node
Characteristics:
- **External I/O** - HTTPS request to Anthropic API
- **OAuth Passthrough** - No token modification (transparent)
- **Response Capture** - Store for learning (async, non-blocking)

Key Responsibilities:
1. Forward Request - Build HTTPS request to Anthropic API
2. OAuth Passthrough - Pass token unchanged (transparent)
3. Capture Response - Extract response data for learning
4. Return Response - Return to Orchestrator with metrics

Event Flow:
1. Consume: context.forward.requested.v1
2. Forward to Anthropic API (HTTPS POST)
3. Capture response (non-blocking)
4. Publish: context.forward.completed.v1

Performance Targets:
- Forwarding time: <500ms (depends on Anthropic API)
- Capture overhead: <50ms (non-blocking)
- Error handling: Retry with exponential backoff
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import httpx
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from config import settings

from ..models.event_envelope import (
    ContextForwardCompletedEvent,
    ContextFailedEvent,
    EventType,
    KafkaTopics,
)

logger = logging.getLogger(__name__)


class NodeAnthropicForwarderEffect:
    """
    Effect node for forwarding requests to Anthropic API.

    External I/O:
    - HTTPS POST to Anthropic API
    - OAuth token passthrough (no modification)
    - Response capture for learning
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        anthropic_base_url: str = "https://api.anthropic.com",
        default_timeout_seconds: int = 300,  # 5 minutes
        max_retries: int = 3,
    ):
        """
        Initialize Anthropic forwarder node.

        Args:
            bootstrap_servers: Kafka bootstrap servers (default from settings)
            anthropic_base_url: Anthropic API base URL
            default_timeout_seconds: Request timeout (default 300s)
            max_retries: Maximum retry attempts on failure
        """
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.anthropic_base_url = anthropic_base_url
        self.default_timeout_seconds = default_timeout_seconds
        self.max_retries = max_retries

        # Kafka consumer/producer (initialized in start())
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None

        # HTTP client (initialized in start())
        self.http_client: Optional[httpx.AsyncClient] = None

        # Running flag
        self._running = False

        logger.info("NodeAnthropicForwarderEffect initialized")

    async def start(self) -> None:
        """Start Kafka consumer, producer, and HTTP client."""
        logger.info("Starting NodeAnthropicForwarderEffect...")

        # Create Kafka consumer
        self.consumer = AIOKafkaConsumer(
            KafkaTopics.CONTEXT_FORWARD_REQUESTED,
            bootstrap_servers=self.bootstrap_servers,
            group_id="anthropic-forwarder-group",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
        )

        # Create Kafka producer
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        # Create HTTP client
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.default_timeout_seconds),
            follow_redirects=True,
        )

        # Start connections (clean up on partial failure)
        try:
            await self.consumer.start()
            await self.producer.start()
        except Exception:
            if self.consumer:
                await self.consumer.stop()
            if self.producer:
                await self.producer.stop()
            if self.http_client:
                await self.http_client.aclose()
            raise

        self._running = True
        logger.info("NodeAnthropicForwarderEffect started successfully")

    async def stop(self) -> None:
        """Stop Kafka consumer, producer, and HTTP client."""
        logger.info("Stopping NodeAnthropicForwarderEffect...")
        self._running = False

        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()
        if self.http_client:
            await self.http_client.aclose()

        logger.info("NodeAnthropicForwarderEffect stopped")

    async def run(self) -> None:
        """
        Main event loop - processes forward requests.

        For each request:
        1. Extract rewritten request + OAuth token
        2. Build HTTPS request to Anthropic
        3. Forward with retry logic
        4. Capture response (non-blocking)
        5. Publish completed event
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started - call start() first")

        logger.info("NodeAnthropicForwarderEffect event loop started")

        try:
            async for message in self.consumer:
                if not self._running:
                    break

                try:
                    # Parse event
                    event = message.value
                    correlation_id = event.get("correlation_id")
                    payload = event.get("payload", {})

                    if not correlation_id:
                        logger.warning("Received event missing correlation_id, skipping")
                        continue

                    logger.info(f"Processing forward request (correlation_id={correlation_id})")

                    # Process forward (async task to avoid blocking)
                    asyncio.create_task(
                        self._process_forward_request(
                            correlation_id=correlation_id,
                            rewritten_request=payload.get("rewritten_request", {}),
                            oauth_token=payload.get("oauth_token", ""),
                        )
                    )

                except Exception as e:
                    logger.error(f"Error processing forward event: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Fatal error in forwarder event loop: {e}", exc_info=True)
            raise

    async def _process_forward_request(
        self,
        correlation_id: str,
        rewritten_request: Dict[str, Any],
        oauth_token: str,
    ) -> None:
        """
        Process forward request to Anthropic API.

        Args:
            correlation_id: Request correlation ID
            rewritten_request: Rewritten messages + system prompt
            oauth_token: OAuth token (passthrough)
        """
        start_time = asyncio.get_running_loop().time()

        try:
            # Build headers
            headers = {
                "Authorization": oauth_token,  # Pass through unchanged
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }

            # Extract request data
            request_data = {
                "model": rewritten_request.get("model", "claude-sonnet-4"),
                "messages": rewritten_request.get("messages", []),
                "system": rewritten_request.get("system", ""),
                "max_tokens": rewritten_request.get("max_tokens", 4096),
            }

            # Add optional parameters
            if "temperature" in rewritten_request:
                request_data["temperature"] = rewritten_request["temperature"]
            if "top_p" in rewritten_request:
                request_data["top_p"] = rewritten_request["top_p"]
            if "top_k" in rewritten_request:
                request_data["top_k"] = rewritten_request["top_k"]

            logger.info(
                f"Forwarding to Anthropic: model={request_data['model']}, "
                f"messages={len(request_data['messages'])}, "
                f"system_chars={len(request_data.get('system', ''))} "
                f"(correlation_id={correlation_id})"
            )

            # Forward to Anthropic with retry
            response_data, status_code = await self._forward_with_retry(
                url=f"{self.anthropic_base_url}/v1/messages",
                headers=headers,
                json_data=request_data,
            )

            end_time = asyncio.get_running_loop().time()
            forward_time_ms = int((end_time - start_time) * 1000)

            logger.info(
                f"Anthropic response received: status={status_code}, "
                f"time={forward_time_ms}ms (correlation_id={correlation_id})"
            )

            # Capture response (async, non-blocking)
            asyncio.create_task(
                self._capture_response(
                    correlation_id=correlation_id,
                    request_data=request_data,
                    response_data=response_data,
                )
            )

            # Publish completed event
            await self._publish_completed(
                correlation_id=correlation_id,
                response_data=response_data,
                status_code=status_code,
                forward_time_ms=forward_time_ms,
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Anthropic API error: {e.response.status_code} (correlation_id={correlation_id})"
            )
            await self._publish_error(
                correlation_id, f"Anthropic API error: {e.response.status_code}"
            )

        except httpx.TimeoutException:
            logger.error(f"Anthropic API timeout (correlation_id={correlation_id})")
            await self._publish_error(correlation_id, "Anthropic API timeout")

        except Exception as e:
            logger.error(f"Forward error (correlation_id={correlation_id}): {e}", exc_info=True)
            await self._publish_error(correlation_id, str(e))

    async def _forward_with_retry(
        self,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
    ) -> tuple[Dict[str, Any], int]:
        """
        Forward request to Anthropic with retry logic.

        Args:
            url: Anthropic API URL
            headers: Request headers
            json_data: Request body

        Returns:
            (response_data, status_code) tuple

        Raises:
            httpx.HTTPStatusError: On non-2xx response after retries
            httpx.TimeoutException: On timeout after retries
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = await self.http_client.post(url, json=json_data, headers=headers)
                response.raise_for_status()

                # Success
                return response.json(), response.status_code

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt  # Exponential backoff
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {backoff}s: {e}"
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"Request failed after {self.max_retries} attempts: {e}")
                    raise

            except httpx.HTTPStatusError as e:
                # Don't retry on client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise

                # Retry on server errors (5xx)
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        f"Server error {e.response.status_code} (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        f"Server error {e.response.status_code} after {self.max_retries} attempts"
                    )
                    raise

        # Should not reach here (all paths either return or raise above)
        # Defensive fallback in case max_retries=0 or logic changes
        if last_exception:
            raise last_exception
        raise RuntimeError("_forward_with_retry exhausted retries without result or exception")

    async def _capture_response(
        self,
        correlation_id: str,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
    ) -> None:
        """
        Capture response for learning (async, non-blocking).

        This will be expanded in Phase 4 to include:
        - Log to PostgreSQL (agent_execution_logs)
        - Publish to Kafka (intelligence events)
        - Update memory client (pattern learning)

        Args:
            correlation_id: Request correlation ID
            request_data: Request data
            response_data: Response data
        """
        try:
            # Phase 2: Minimal capture (just log)
            # Phase 4: Full capture (PostgreSQL, Kafka, Memory)

            logger.debug(
                f"Response captured for learning: "
                f"id={response_data.get('id')}, "
                f"model={response_data.get('model')}, "
                f"usage={response_data.get('usage')} "
                f"(correlation_id={correlation_id})"
            )

            # TODO Phase 4: Add PostgreSQL logging
            # TODO Phase 4: Add Kafka event publishing
            # TODO Phase 4: Add memory client update

        except Exception as e:
            logger.warning(f"Failed to capture response: {e}")
            # Non-blocking - don't fail request

    async def _publish_completed(
        self,
        correlation_id: str,
        response_data: Dict[str, Any],
        status_code: int,
        forward_time_ms: int,
    ) -> None:
        """
        Publish completed event with Anthropic response.

        Args:
            correlation_id: Request correlation ID
            response_data: Anthropic API response
            status_code: HTTP status code
            forward_time_ms: Forward time in milliseconds
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish completed event")
            return

        try:
            # Create completed event
            event = ContextForwardCompletedEvent(
                correlation_id=correlation_id,
                payload={
                    "response_data": response_data,
                    "status_code": status_code,
                    "forward_time_ms": forward_time_ms,
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_FORWARD_COMPLETED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published forward completed event (correlation_id={correlation_id})")

        except Exception as e:
            logger.error(f"Failed to publish completed event: {e}", exc_info=True)

    async def _publish_error(self, correlation_id: str, error_message: str) -> None:
        """
        Publish error event.

        Args:
            correlation_id: Request correlation ID
            error_message: Error message
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish error")
            return

        try:
            # Create error event
            event = ContextFailedEvent(
                correlation_id=correlation_id,
                payload={
                    "error_message": error_message,
                    "error_code": "ANTHROPIC_FORWARD_ERROR",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_FAILED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published error event (correlation_id={correlation_id})")

        except Exception as e:
            logger.error(f"Failed to publish error event: {e}", exc_info=True)


# ============================================================================
# Main entry point (for testing)
# ============================================================================

async def main():
    """Main entry point for testing."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    node = NodeAnthropicForwarderEffect()

    try:
        await node.start()
        await node.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
