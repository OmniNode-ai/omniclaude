"""
NodeContextProxyOrchestrator - Workflow Coordinator

This node coordinates the workflow by reading FSM state from the Reducer
and publishing domain events to trigger node execution.

Orchestrator Role:
- Read FSM state from NodeContextRequestReducer
- Coordinate workflow based on FSM state
- Publish domain events to trigger node execution
- Drive workflow to completion

FSM-Driven Pattern:
1. Orchestrator reads FSM state (from Reducer.get_state())
2. If state = request_received, start workflow
3. Publish domain events for each step
4. Wait for FSM transitions before proceeding
5. Return response when FSM = completed

Workflow Steps (Phase 1 - Skeleton):
1. Wait for FSM: request_received
2. Immediately return mock response (no intelligence/rewriting yet)

Workflow Steps (Phase 2+ - Full Implementation):
1. Query Intelligence (wait for FSM: request_received → intelligence_queried)
2. Rewrite Context (wait for FSM: intelligence_queried → context_rewritten)
3. Forward to Anthropic (wait for FSM: context_rewritten → completed)
4. Send Response (publish: context.response.completed.v1)

NOTE: Phase 1 uses simplified workflow for round-trip testing only!
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from config import settings

from ..models.event_envelope import (
    BaseEventEnvelope,
    ContextQueryRequestedEvent,
    ContextRewriteRequestedEvent,
    ContextForwardRequestedEvent,
    ContextResponseCompletedEvent,
    EventType,
    KafkaTopics,
)
from ..models.fsm_state import WorkflowState

logger = logging.getLogger(__name__)


class NodeContextProxyOrchestrator:
    """
    Orchestrator for intelligent context proxy workflow.

    Phase 1 (Skeleton):
    - Wait for FSM: request_received
    - Immediately return mock response

    Phase 2+ (Full):
    - Coordinate 3 sequential steps (Intelligence, Rewrite, Forward)
    - Wait for FSM transitions before proceeding

    FSM-Driven Pattern:
    - Reads FSM state from Reducer (NOT via events, via shared reference)
    - Publishes domain events to trigger node execution
    - Waits for FSM transitions before proceeding to next step
    """

    def __init__(
        self,
        reducer,  # Reference to NodeContextRequestReducer
        bootstrap_servers: Optional[str] = None,
        fsm_poll_interval_ms: int = 100,
    ):
        """
        Initialize orchestrator node.

        Args:
            reducer: Reference to NodeContextRequestReducer (for FSM state reads)
            bootstrap_servers: Kafka bootstrap servers (default from settings)
            fsm_poll_interval_ms: Poll interval for FSM state checks (ms)
        """
        self.reducer = reducer
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.fsm_poll_interval_ms = fsm_poll_interval_ms

        # Kafka consumer/producer (initialized in start())
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None

        # Step results cache: correlation_id → {intelligence, rewritten_context, anthropic_response}
        self._step_results: Dict[str, Dict[str, Any]] = {}

        # Running flag
        self._running = False

        logger.info(f"NodeContextProxyOrchestrator initialized (fsm_poll_interval={fsm_poll_interval_ms}ms)")

    async def start(self) -> None:
        """Start Kafka consumer and producer."""
        logger.info("Starting NodeContextProxyOrchestrator...")

        # Create Kafka consumer (listens for request events AND completed events for result caching)
        self.consumer = AIOKafkaConsumer(
            KafkaTopics.CONTEXT_REQUEST_RECEIVED,
            KafkaTopics.CONTEXT_QUERY_COMPLETED,
            KafkaTopics.CONTEXT_REWRITE_COMPLETED,
            KafkaTopics.CONTEXT_FORWARD_COMPLETED,
            bootstrap_servers=self.bootstrap_servers,
            group_id="orchestrator-group",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
        )

        # Create Kafka producer
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        # Start connections
        await self.consumer.start()
        await self.producer.start()

        self._running = True
        logger.info("NodeContextProxyOrchestrator started successfully")

    async def stop(self) -> None:
        """Stop Kafka consumer and producer."""
        logger.info("Stopping NodeContextProxyOrchestrator...")
        self._running = False

        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()

        logger.info("NodeContextProxyOrchestrator stopped")

    async def run(self) -> None:
        """
        Main event loop - coordinates workflow for each request.

        Phase 1 (Skeleton):
        - Wait for context.request.received.v1
        - Check FSM state = request_received
        - Immediately return mock response

        Phase 2+ (Full):
        - Query Intelligence
        - Rewrite Context
        - Forward to Anthropic
        - Send Response
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started - call start() first")

        logger.info("NodeContextProxyOrchestrator event loop started")

        try:
            async for message in self.consumer:
                if not self._running:
                    break

                try:
                    # Parse event
                    event = message.value
                    event_type = event.get("event_type")
                    correlation_id = event.get("correlation_id")
                    payload = event.get("payload", {})

                    # Handle different event types
                    if event_type == "REQUEST_RECEIVED":
                        logger.info(f"Orchestrating request (correlation_id={correlation_id})")

                        # Orchestrate workflow (async task to avoid blocking)
                        asyncio.create_task(
                            self.orchestrate_proxy_request(
                                request_data=payload.get("request_data", {}),
                                oauth_token=payload.get("oauth_token", ""),
                                correlation_id=correlation_id,
                            )
                        )

                    elif event_type == "QUERY_COMPLETED":
                        # Cache intelligence results
                        self._cache_step_result(correlation_id, "intelligence", payload)
                        logger.debug(f"Cached intelligence results (correlation_id={correlation_id})")

                    elif event_type == "REWRITE_COMPLETED":
                        # Cache rewritten context
                        self._cache_step_result(correlation_id, "rewritten_context", payload)
                        logger.debug(f"Cached rewritten context (correlation_id={correlation_id})")

                    elif event_type == "FORWARD_COMPLETED":
                        # Cache Anthropic response
                        self._cache_step_result(correlation_id, "anthropic_response", payload)
                        logger.debug(f"Cached Anthropic response (correlation_id={correlation_id})")

                except Exception as e:
                    logger.error(f"Error processing orchestration event: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Fatal error in orchestrator event loop: {e}", exc_info=True)
            raise

    async def orchestrate_proxy_request(
        self,
        request_data: Dict[str, Any],
        oauth_token: str,
        correlation_id: str,
    ) -> None:
        """
        High-level orchestration method for proxy requests.

        Phase 1 (Skeleton):
        - Wait for FSM state = request_received
        - Return mock response immediately

        Phase 2+ (Full):
        - Query Intelligence (wait for FSM: request_received → intelligence_queried)
        - Rewrite Context (wait for FSM: intelligence_queried → context_rewritten)
        - Forward to Anthropic (wait for FSM: context_rewritten → completed)
        - Send Response

        Args:
            request_data: Original HTTP request from Claude Code
            oauth_token: OAuth token for Anthropic API
            correlation_id: Request correlation ID
        """
        try:
            logger.info(f"Starting workflow orchestration (correlation_id={correlation_id})")

            # Step 1: Wait for FSM state = request_received
            await self._wait_for_fsm_state(
                correlation_id=correlation_id,
                expected_state=WorkflowState.REQUEST_RECEIVED,
                timeout_ms=5000,
            )

            logger.info(f"FSM state confirmed: request_received (correlation_id={correlation_id})")

            # ========================================================================
            # Phase 2+: Full Workflow Implementation
            # ========================================================================

            # Step 2: Query Intelligence
            logger.info(f"→ Step 1/3: Querying intelligence (correlation_id={correlation_id})")
            await self._publish_query_event(correlation_id=correlation_id, request_data=request_data)

            # Wait for FSM transition: request_received → intelligence_queried
            await self._wait_for_fsm_state(
                correlation_id=correlation_id,
                expected_state=WorkflowState.INTELLIGENCE_QUERIED,
                timeout_ms=5000,
            )

            intelligence_result = self._get_step_result(correlation_id, "intelligence")
            logger.info(f"✓ Intelligence queried (correlation_id={correlation_id})")

            # Step 3: Rewrite Context
            logger.info(f"→ Step 2/3: Rewriting context (correlation_id={correlation_id})")
            await self._publish_rewrite_event(
                correlation_id=correlation_id,
                messages=request_data.get("messages", []),
                system_prompt=request_data.get("system", ""),
                intelligence=intelligence_result.get("intelligence", {}),
                intent=intelligence_result.get("intent", {}),
            )

            # Wait for FSM transition: intelligence_queried → context_rewritten
            await self._wait_for_fsm_state(
                correlation_id=correlation_id,
                expected_state=WorkflowState.CONTEXT_REWRITTEN,
                timeout_ms=2000,
            )

            rewrite_result = self._get_step_result(correlation_id, "rewritten_context")
            logger.info(f"✓ Context rewritten (correlation_id={correlation_id})")

            # Step 4: Forward to Anthropic
            logger.info(f"→ Step 3/3: Forwarding to Anthropic (correlation_id={correlation_id})")
            await self._publish_forward_event(
                correlation_id=correlation_id,
                rewritten_request={
                    "model": request_data.get("model", "claude-sonnet-4"),
                    "messages": rewrite_result.get("messages", []),
                    "system": rewrite_result.get("system", ""),
                    "max_tokens": request_data.get("max_tokens", 4096),
                },
                oauth_token=oauth_token,
            )

            # Wait for FSM transition: context_rewritten → completed
            await self._wait_for_fsm_state(
                correlation_id=correlation_id,
                expected_state=WorkflowState.COMPLETED,
                timeout_ms=30000,
            )

            anthropic_result = self._get_step_result(correlation_id, "anthropic_response")
            logger.info(f"✓ Anthropic response received (correlation_id={correlation_id})")

            # Step 5: Send Response
            await self._publish_response(
                correlation_id=correlation_id,
                response_data=anthropic_result.get("response_data", {}),
                intelligence_query_time_ms=intelligence_result.get("query_time_ms", 0),
                context_rewrite_time_ms=rewrite_result.get("processing_time_ms", 0),
                anthropic_forward_time_ms=anthropic_result.get("forward_time_ms", 0),
                total_time_ms=0,
            )

            # Clean up
            self._step_results.pop(correlation_id, None)

            logger.info(f"✅ Workflow completed successfully (correlation_id={correlation_id})")

        except asyncio.TimeoutError:
            logger.error(f"Workflow timeout (correlation_id={correlation_id})")
            await self._publish_error(correlation_id, "Workflow timeout")

        except Exception as e:
            logger.error(f"Workflow error (correlation_id={correlation_id}): {e}", exc_info=True)
            await self._publish_error(correlation_id, str(e))

    async def _wait_for_fsm_state(
        self, correlation_id: str, expected_state: WorkflowState, timeout_ms: int
    ) -> None:
        """
        Wait for FSM state transition by polling Reducer.

        Args:
            correlation_id: Workflow ID
            expected_state: Expected FSM state
            timeout_ms: Timeout in milliseconds

        Raises:
            TimeoutError: If FSM state does not transition within timeout
        """
        start_time = asyncio.get_running_loop().time()
        timeout_seconds = timeout_ms / 1000.0

        while True:
            # Read current FSM state from Reducer
            current_state = self.reducer.get_state(correlation_id)

            if current_state == expected_state:
                # FSM transitioned successfully
                return

            if current_state == WorkflowState.FAILED:
                # Workflow failed
                raise Exception("Workflow failed during FSM transition")

            # Check timeout
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"FSM state did not transition to {expected_state} within {timeout_ms}ms "
                    f"(current state: {current_state})"
                )

            # Poll interval
            await asyncio.sleep(self.fsm_poll_interval_ms / 1000.0)

    def _create_mock_response(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create mock Anthropic API response (Phase 1 only).

        Args:
            request_data: Original request

        Returns:
            Mock response in Anthropic API format
        """
        return {
            "id": f"msg_{uuid4().hex[:16]}",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "[MOCK RESPONSE - Phase 1] This is a test response from the Intelligent Context Proxy. "
                    "The proxy is working correctly! In Phase 2+, this will be replaced with the actual "
                    "Anthropic API response with intelligence injection.",
                }
            ],
            "model": request_data.get("model", "claude-sonnet-4"),
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    async def _publish_response(
        self,
        correlation_id: str,
        response_data: Dict[str, Any],
        intelligence_query_time_ms: int,
        context_rewrite_time_ms: int,
        anthropic_forward_time_ms: int,
        total_time_ms: int,
    ) -> None:
        """
        Publish response event to Kafka.

        Args:
            correlation_id: Request correlation ID
            response_data: Anthropic API response
            intelligence_query_time_ms: Intelligence query time
            context_rewrite_time_ms: Context rewrite time
            anthropic_forward_time_ms: Anthropic forward time
            total_time_ms: Total processing time
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish response")
            return

        try:
            # Create response event
            event = ContextResponseCompletedEvent(
                correlation_id=correlation_id,
                payload={
                    "response_data": response_data,
                    "intelligence_query_time_ms": intelligence_query_time_ms,
                    "context_rewrite_time_ms": context_rewrite_time_ms,
                    "anthropic_forward_time_ms": anthropic_forward_time_ms,
                    "total_time_ms": total_time_ms,
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_RESPONSE_COMPLETED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published response event (correlation_id={correlation_id})")

        except Exception as e:
            logger.error(f"Failed to publish response event: {e}", exc_info=True)

    async def _publish_error(self, correlation_id: str, error_message: str) -> None:
        """
        Publish error event to Kafka.

        Args:
            correlation_id: Request correlation ID
            error_message: Error message
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish error")
            return

        try:
            # Create error event
            event = BaseEventEnvelope(
                event_type=EventType.FAILED,
                correlation_id=correlation_id,
                payload={
                    "error_message": error_message,
                    "error_code": "WORKFLOW_ERROR",
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
    # Phase 2+ Helper Methods (Full Workflow)
    # ============================================================================

    def _cache_step_result(self, correlation_id: str, step_name: str, result: Dict[str, Any]) -> None:
        """Cache step result for workflow aggregation."""
        if correlation_id not in self._step_results:
            self._step_results[correlation_id] = {}
        self._step_results[correlation_id][step_name] = result

    def _get_step_result(self, correlation_id: str, step_name: str) -> Dict[str, Any]:
        """Get cached step result."""
        if correlation_id not in self._step_results:
            logger.warning(f"No step results for correlation_id={correlation_id}")
            return {}
        return self._step_results[correlation_id].get(step_name, {})

    async def _publish_query_event(self, correlation_id: str, request_data: Dict[str, Any]) -> None:
        """Publish intelligence query event."""
        if not self.producer:
            raise RuntimeError("Producer not available")

        event = ContextQueryRequestedEvent(
            correlation_id=correlation_id,
            payload={"request_data": request_data, "intent": None},
        )

        await self.producer.send_and_wait(
            topic=KafkaTopics.CONTEXT_QUERY_REQUESTED,
            value=event.model_dump(),
            key=correlation_id.encode("utf-8"),
        )

    async def _publish_rewrite_event(
        self,
        correlation_id: str,
        messages: List[Dict[str, Any]],
        system_prompt: str,
        intelligence: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> None:
        """Publish context rewrite event."""
        if not self.producer:
            raise RuntimeError("Producer not available")

        event = ContextRewriteRequestedEvent(
            correlation_id=correlation_id,
            payload={
                "messages": messages,
                "system_prompt": system_prompt,
                "intelligence": intelligence,
                "intent": intent,
            },
        )

        await self.producer.send_and_wait(
            topic=KafkaTopics.CONTEXT_REWRITE_REQUESTED,
            value=event.model_dump(),
            key=correlation_id.encode("utf-8"),
        )

    async def _publish_forward_event(
        self, correlation_id: str, rewritten_request: Dict[str, Any], oauth_token: str
    ) -> None:
        """Publish Anthropic forward event."""
        if not self.producer:
            raise RuntimeError("Producer not available")

        event = ContextForwardRequestedEvent(
            correlation_id=correlation_id,
            payload={
                "rewritten_request": rewritten_request,
                "oauth_token": oauth_token,
            },
        )

        await self.producer.send_and_wait(
            topic=KafkaTopics.CONTEXT_FORWARD_REQUESTED,
            value=event.model_dump(),
            key=correlation_id.encode("utf-8"),
        )


# ============================================================================
# Main entry point (for testing)
# ============================================================================


async def main():
    """Main entry point for testing."""
    from .node_reducer import NodeContextRequestReducer

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create reducer (for FSM state reads)
    reducer = NodeContextRequestReducer()

    # Create orchestrator (with reducer reference)
    orchestrator = NodeContextProxyOrchestrator(reducer=reducer)

    try:
        # Start both nodes
        await reducer.start()
        await orchestrator.start()

        # Run both event loops concurrently
        await asyncio.gather(reducer.run(), orchestrator.run())

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await orchestrator.stop()
        await reducer.stop()


if __name__ == "__main__":
    asyncio.run(main())
