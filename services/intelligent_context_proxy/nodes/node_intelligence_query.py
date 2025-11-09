"""
NodeIntelligenceQueryEffect - Intelligence Queries via Kafka

This node queries OmniClaude's intelligence infrastructure (Qdrant, PostgreSQL,
Memgraph, Memory) via existing event bus infrastructure.

CRITICAL: **REUSES EXISTING CODE** - This node is a thin wrapper around:
- agents/lib/manifest_injector.py (3300 LOC) - Already queries all intelligence sources
- agents/lib/intelligence_event_client.py - Already handles Kafka communication
- claude_hooks/lib/memory/ - Already manages memory storage

Integration Strategy:
- REUSE ManifestInjector.generate_dynamic_manifest_async()
- REUSE IntelligenceEventClient for Kafka communication
- NO REIMPLEMENTATION - Just wrap existing functionality

Event Flow:
1. Consume: context.query.requested.v1
2. Call ManifestInjector (queries Qdrant, PostgreSQL, Memory via Kafka)
3. Return intelligence data
4. Publish: context.query.completed.v1

Intelligence Sources:
- Qdrant: 120+ patterns (execution_patterns + code_patterns)
- PostgreSQL: Debug intelligence (similar workflows - successes/failures)
- Memgraph: Relationship graphs
- Memory: Archived context from previous conversations

Performance:
- Target: <2000ms query time
- Parallel queries (already implemented in ManifestInjector)
- Caching via Valkey (already implemented)
"""

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from config import settings

# Add agents/lib to path for imports
agents_lib_path = Path(__file__).parent.parent.parent.parent / "agents" / "lib"
if str(agents_lib_path) not in sys.path:
    sys.path.insert(0, str(agents_lib_path))

# Import existing components (REUSE!)
from manifest_injector import ManifestInjector

from ..models.event_envelope import (
    ContextQueryCompletedEvent,
    ContextFailedEvent,
    EventType,
    KafkaTopics,
)

logger = logging.getLogger(__name__)


class NodeIntelligenceQueryEffect:
    """
    Effect node for querying intelligence systems.

    REUSES EXISTING CODE:
    - ManifestInjector (3300 LOC)
    - IntelligenceEventClient
    - Memory Client

    No reimplementation needed!
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        consumer_group: str = "intelligence-query-group",
    ):
        """
        Initialize intelligence query node.

        Args:
            bootstrap_servers: Kafka bootstrap servers (default from settings)
            consumer_group: Kafka consumer group
        """
        self.bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers

        # Kafka consumer/producer (initialized in start())
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.producer: Optional[AIOKafkaProducer] = None

        # Running flag
        self._running = False

        logger.info("NodeIntelligenceQueryEffect initialized (REUSES ManifestInjector)")

    async def start(self) -> None:
        """Start Kafka consumer and producer."""
        logger.info("Starting NodeIntelligenceQueryEffect...")

        # Create Kafka consumer
        self.consumer = AIOKafkaConsumer(
            KafkaTopics.CONTEXT_QUERY_REQUESTED,
            bootstrap_servers=self.bootstrap_servers,
            group_id="intelligence-query-group",
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
        logger.info("NodeIntelligenceQueryEffect started successfully")

    async def stop(self) -> None:
        """Stop Kafka consumer and producer."""
        logger.info("Stopping NodeIntelligenceQueryEffect...")
        self._running = False

        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()

        logger.info("NodeIntelligenceQueryEffect stopped")

    async def run(self) -> None:
        """
        Main event loop - processes intelligence query requests.

        For each request:
        1. Extract user prompt and correlation ID
        2. Call ManifestInjector (queries Qdrant, PostgreSQL, Memory)
        3. Return intelligence data
        4. Publish completed event
        """
        if not self.consumer:
            raise RuntimeError("Consumer not started - call start() first")

        logger.info("NodeIntelligenceQueryEffect event loop started")

        try:
            async for message in self.consumer:
                if not self._running:
                    break

                try:
                    # Parse event
                    event = message.value
                    correlation_id = event.get("correlation_id")
                    payload = event.get("payload", {})

                    logger.info(f"Processing intelligence query (correlation_id={correlation_id})")

                    # Process query (async task to avoid blocking)
                    asyncio.create_task(
                        self._process_intelligence_query(
                            correlation_id=correlation_id,
                            request_data=payload.get("request_data", {}),
                            intent=payload.get("intent"),
                        )
                    )

                except Exception as e:
                    logger.error(f"Error processing query event: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Fatal error in intelligence query event loop: {e}", exc_info=True)
            raise

    async def _process_intelligence_query(
        self,
        correlation_id: str,
        request_data: Dict[str, Any],
        intent: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Process intelligence query using ManifestInjector.

        Args:
            correlation_id: Request correlation ID
            request_data: Original HTTP request from Claude Code
            intent: Extracted intent (task_type, entities, operations, files)
        """
        start_time = asyncio.get_event_loop().time()

        try:
            # Extract user prompt from request
            user_prompt = self._extract_latest_user_message(request_data)

            logger.info(
                f"Querying intelligence for correlation_id={correlation_id}, "
                f"prompt_length={len(user_prompt)}"
            )

            # REUSE: Call existing ManifestInjector
            # This already queries everything via Kafka events!
            async with ManifestInjector(agent_name="context-proxy") as injector:
                manifest_data = await injector.generate_dynamic_manifest_async(
                    correlation_id=correlation_id,
                    user_prompt=user_prompt,
                    force_refresh=False,  # Use cache if available
                )

            end_time = asyncio.get_event_loop().time()
            query_time_ms = int((end_time - start_time) * 1000)

            logger.info(
                f"Intelligence query completed in {query_time_ms}ms "
                f"(correlation_id={correlation_id})"
            )

            # Extract intelligence sections
            intelligence_result = {
                "patterns": manifest_data.get("patterns", []),
                "debug_intelligence": manifest_data.get("debug_intelligence", {}),
                "infrastructure": manifest_data.get("infrastructure", {}),
                "models": manifest_data.get("models", {}),
                "database_schemas": manifest_data.get("database_schemas", {}),
                "filesystem": manifest_data.get("filesystem", {}),
                "query_time_ms": query_time_ms,
            }

            # Publish completed event
            await self._publish_completed(
                correlation_id=correlation_id,
                intelligence=intelligence_result,
                query_time_ms=query_time_ms,
            )

        except asyncio.TimeoutError:
            logger.error(f"Intelligence query timeout (correlation_id={correlation_id})")
            await self._publish_error(correlation_id, "Intelligence query timeout")

        except Exception as e:
            logger.error(
                f"Intelligence query error (correlation_id={correlation_id}): {e}", exc_info=True
            )
            await self._publish_error(correlation_id, str(e))

    def _extract_latest_user_message(self, request_data: Dict[str, Any]) -> str:
        """
        Extract latest user message for intelligence context.

        Args:
            request_data: Original HTTP request

        Returns:
            Latest user message text
        """
        messages = request_data.get("messages", [])
        if not messages:
            return ""

        # Find last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle multi-part content
                    text_parts = [p["text"] for p in content if p.get("type") == "text"]
                    return " ".join(text_parts)
                return content

        return ""

    async def _publish_completed(
        self,
        correlation_id: str,
        intelligence: Dict[str, Any],
        query_time_ms: int,
    ) -> None:
        """
        Publish completed event with intelligence data.

        Args:
            correlation_id: Request correlation ID
            intelligence: Intelligence data (patterns, debug_intel, etc.)
            query_time_ms: Query time in milliseconds
        """
        if not self.producer:
            logger.warning("Producer not available - cannot publish completed event")
            return

        try:
            # Create completed event
            event = ContextQueryCompletedEvent(
                correlation_id=correlation_id,
                payload={
                    "intelligence": intelligence,
                    "query_time_ms": query_time_ms,
                },
            )

            # Publish event
            await self.producer.send_and_wait(
                topic=KafkaTopics.CONTEXT_QUERY_COMPLETED,
                value=event.model_dump(),
                key=correlation_id.encode("utf-8"),
            )

            logger.info(f"Published query completed event (correlation_id={correlation_id})")

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
                    "error_code": "INTELLIGENCE_QUERY_ERROR",
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

    node = NodeIntelligenceQueryEffect()

    try:
        await node.start()
        await node.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await node.stop()


if __name__ == "__main__":
    asyncio.run(main())
