"""
NodeContextRequestReducer - FSM State Tracker

This node is the FIRST consumer of FastAPI events and tracks workflow state
using a Finite State Machine (FSM).

Single Role: FSM State Tracking ONLY
- Consume domain events (*.completed.v1, *.received.v1, *.failed.v1)
- Update FSM state in-memory (state transitions)
- Emit persistence intent (PERSIST_STATE)
- NO decision logic, NO aggregation, PURE FSM state machine

FSM States:
- idle → request_received → intelligence_queried → context_rewritten → completed
- Any state can transition to 'failed' on error

Event Flow:
1. FastAPI publishes context.request.received.v1
2. Reducer consumes event → updates FSM (idle → request_received)
3. Reducer emits intent: intents.persist-state.v1
4. Intelligence Effect completes → publishes context.query.completed.v1
5. Reducer consumes event → updates FSM (request_received → intelligence_queried)
6. ... and so on

Orchestrator Independence:
- Orchestrator reads FSM state from this Reducer
- Orchestrator drives workflow based on FSM state
- NO intents from Reducer to Orchestrator (Orchestrator is independent)
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from config import settings

from ..models.event_envelope import (
    BaseEventEnvelope,
    EventType,
    KafkaTopics,
    PersistStateIntent,
)
from ..models.fsm_state import FSMStateManager, FSMTrigger, WorkflowState

logger = logging.getLogger(__name__)


class NodeContextRequestReducer:
    """
    Reducer node for intelligent context proxy.

    Single Role: FSM State Tracking ONLY

    FSM Logic:
    - Track workflow state via FSM manager
    - Validate state transitions
    - Emit intents for persistence (no direct I/O)

    NO Decision Logic:
    - Does NOT decide what operations to run
    - Does NOT aggregate results
    - Does NOT emit workflow coordination intents

    Pure FSM State Machine:
    - Consumes domain events → Updates FSM state → Emits persistence intent
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        consumer_group: str = "context-reducer-group",
    ):
        """
        Initialize reducer node.

        Args:
            bootstrap_servers: Kafka bootstrap servers (default from settings)
            consumer_group: Kafka consumer group
        """
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self.consumer_group = consumer_group

        # FSM state manager (pure in-memory state tracking)
        self.fsm_manager = FSMStateManager()

        # Kafka consumer/producer (initialized in start())
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None

        # Running flag
        self._running = False

        logger.info("NodeContextRequestReducer initialized")

    async def start(self) -> None:
        """Start Kafka consumer and producer."""
        logger.info("Starting NodeContextRequestReducer...")

        # Create Kafka consumer
        self.consumer = AIOKafkaConsumer(
            # Subscribe to ALL domain event topics
            KafkaTopics.CONTEXT_REQUEST_RECEIVED,
            KafkaTopics.CONTEXT_QUERY_COMPLETED,
            KafkaTopics.CONTEXT_REWRITE_COMPLETED,
            KafkaTopics.CONTEXT_FORWARD_COMPLETED,
            KafkaTopics.CONTEXT_FAILED,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.consumer_group,
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
        logger.info("NodeContextRequestReducer started successfully")

    async def stop(self) -> None:
        """Stop Kafka consumer and producer."""
        logger.info("Stopping NodeContextRequestReducer...")
        self._running = False

        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()

        logger.info("NodeContextRequestReducer stopped")

    async def run(self) -> None:
        """
        Main event loop - consumes events and updates FSM state.

        Consumes events from:
        - context.request.received.v1
        - context.query.completed.v1
        - context.rewrite.completed.v1
        - context.forward.completed.v1
        - context.*.failed.v1

        For each event:
        1. Extract event type and correlation ID
        2. Map event type to FSM trigger
        3. Update FSM state (transition validation)
        4. Emit persistence intent (no direct PostgreSQL)
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started - call start() first")

        logger.info("NodeContextRequestReducer event loop started")

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

                    logger.debug(
                        f"Received event: {event_type} (correlation_id={correlation_id})"
                    )

                    # Process event (update FSM state)
                    await self._process_event(
                        event_type=event_type,
                        correlation_id=correlation_id,
                        payload=payload,
                    )

                except Exception as e:
                    logger.error(f"Error processing event: {e}", exc_info=True)
                    # Continue processing (non-blocking)

        except Exception as e:
            logger.error(f"Fatal error in event loop: {e}", exc_info=True)
            raise

    async def _process_event(
        self, event_type: str, correlation_id: str, payload: Dict[str, Any]
    ) -> None:
        """
        Process event and update FSM state.

        Args:
            event_type: Event type (REQUEST_RECEIVED, QUERY_COMPLETED, etc.)
            correlation_id: Request correlation ID
            payload: Event payload
        """
        # Map event type to FSM trigger
        trigger = self._map_event_to_trigger(event_type)
        if not trigger:
            logger.warning(f"Unknown event type: {event_type}")
            return

        # Initialize workflow if needed (for REQUEST_RECEIVED)
        if trigger == FSMTrigger.REQUEST_RECEIVED:
            self.fsm_manager.initialize_workflow(
                workflow_id=correlation_id, metadata={"started_at": datetime.now(UTC).isoformat()}
            )

        # Update FSM state (transition validation)
        success = self.fsm_manager.transition(
            workflow_id=correlation_id, trigger=trigger, metadata={"event_type": event_type}
        )

        if not success:
            logger.error(
                f"Invalid FSM transition: {event_type} (correlation_id={correlation_id})"
            )
            return

        # Get updated FSM state
        current_state = self.fsm_manager.get_state(correlation_id)

        logger.info(
            f"FSM transition: {trigger} → {current_state} (correlation_id={correlation_id})"
        )

        # Emit persistence intent (no direct PostgreSQL)
        await self._emit_persist_state_intent(
            correlation_id=correlation_id,
            current_state=current_state,
        )

    def _map_event_to_trigger(self, event_type: str) -> Optional[FSMTrigger]:
        """
        Map domain event type to FSM trigger.

        Args:
            event_type: Event type string

        Returns:
            FSM trigger or None if unknown
        """
        event_to_trigger = {
            "REQUEST_RECEIVED": FSMTrigger.REQUEST_RECEIVED,
            "QUERY_COMPLETED": FSMTrigger.INTELLIGENCE_QUERIED,
            "REWRITE_COMPLETED": FSMTrigger.CONTEXT_REWRITTEN,
            "FORWARD_COMPLETED": FSMTrigger.ANTHROPIC_FORWARDED,
            "FAILED": FSMTrigger.ERROR,
        }
        return event_to_trigger.get(event_type)

    async def _emit_persist_state_intent(
        self, correlation_id: str, current_state: WorkflowState
    ) -> None:
        """
        Emit intent for FSM state persistence (no direct PostgreSQL).

        Args:
            correlation_id: Request correlation ID
            current_state: Current FSM state
        """
        if not self.producer:
            logger.warning("Producer not available - skipping persistence intent")
            return

        try:
            # Get transition history
            transition_history = self.fsm_manager.get_transition_history(correlation_id)

            # Create persistence intent
            intent = PersistStateIntent(
                correlation_id=correlation_id,
                current_state=str(current_state.value),
                previous_state=str(transition_history[-2].from_state.value)
                if len(transition_history) >= 2
                else None,
                transition_history=[
                    {
                        "from": str(t.from_state.value),
                        "to": str(t.to_state.value),
                        "trigger": str(t.trigger.value),
                        "timestamp": t.timestamp,
                    }
                    for t in transition_history
                ],
                timestamp=datetime.now(UTC).isoformat(),
            )

            # Publish intent
            await self.producer.send_and_wait(
                topic=KafkaTopics.INTENTS_PERSIST_STATE,
                value=intent.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.debug(
                f"Emitted persistence intent: {current_state} (correlation_id={correlation_id})"
            )

        except Exception as e:
            logger.error(f"Failed to emit persistence intent: {e}", exc_info=True)
            # Non-blocking - continue processing

    # ============================================================================
    # Public API for Orchestrator
    # ============================================================================

    def get_state(self, correlation_id: str) -> Optional[WorkflowState]:
        """
        Get current FSM state for workflow.

        Used by Orchestrator to check workflow progress.

        Args:
            correlation_id: Request correlation ID

        Returns:
            Current FSM state or None if not found
        """
        return self.fsm_manager.get_state(correlation_id)

    def get_transition_history(self, correlation_id: str) -> list:
        """
        Get FSM transition history for workflow.

        Args:
            correlation_id: Request correlation ID

        Returns:
            List of transitions (chronological order)
        """
        return self.fsm_manager.get_transition_history(correlation_id)


# ============================================================================
# Main entry point (for testing)
# ============================================================================

async def main():
    """Main entry point for testing."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    reducer = NodeContextRequestReducer()

    try:
        await reducer.start()
        await reducer.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await reducer.stop()


if __name__ == "__main__":
    asyncio.run(main())
