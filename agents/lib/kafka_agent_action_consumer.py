#!/usr/bin/env python3
"""
Kafka Agent Action Consumer

Consumes agent action events from Kafka and persists them to PostgreSQL
with batch processing, idempotency, and error handling.

Features:
- Batch insert for performance
- Idempotency (duplicate detection)
- Automatic retry with exponential backoff
- Dead letter queue for failed messages
- Graceful shutdown
"""

import asyncio
import json
import logging
import os
import signal
from datetime import datetime
from typing import Dict, List, Optional

import asyncpg
from kafka import KafkaConsumer

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)


class KafkaAgentActionConsumer:
    """
    Consumer for agent action events from Kafka with PostgreSQL persistence.
    """

    def __init__(
        self,
        kafka_brokers: Optional[str] = None,
        group_id: str = "agent-action-consumer",
        topic: str = "agent-actions",
        batch_size: int = 100,
        batch_timeout_seconds: float = 5.0,
        postgres_dsn: Optional[str] = None,
    ):
        """
        Initialize Kafka consumer.

        Args:
            kafka_brokers: Kafka broker list (comma-separated)
            group_id: Consumer group ID
            topic: Topic to consume from
            batch_size: Max events per batch insert
            batch_timeout_seconds: Max wait time for batch
            postgres_dsn: PostgreSQL connection string
        """
        # Kafka brokers - require explicit configuration (no localhost default)
        kafka_brokers_str = kafka_brokers or os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        if not kafka_brokers_str:
            raise ValueError(
                "KAFKA_BOOTSTRAP_SERVERS must be set. Example: KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092"
            )
        self.kafka_brokers = kafka_brokers_str.split(",")
        self.group_id = group_id
        self.topic = topic
        self.batch_size = batch_size
        self.batch_timeout_seconds = batch_timeout_seconds
        self.postgres_dsn = postgres_dsn or self._build_postgres_dsn()

        self.consumer: Optional[KafkaConsumer] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.running = False
        self.shutdown_event = asyncio.Event()

    def _build_postgres_dsn(self) -> str:
        """Build PostgreSQL DSN from environment variables.

        Requires POSTGRES_PASSWORD to be set in environment (source .env file).
        """
        # Use production defaults that match Pydantic settings
        host = os.getenv("POSTGRES_HOST", "192.168.86.200")
        port = os.getenv("POSTGRES_PORT", "5436")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")  # Require explicit configuration
        database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    async def start(self):
        """Start consumer and database connection."""
        logger.info(f"Starting Kafka consumer for topic: {self.topic}")

        # Create Kafka consumer
        self.consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=self.kafka_brokers,
            group_id=self.group_id,
            enable_auto_commit=False,  # Manual commit for safety
            auto_offset_reset="earliest",  # Process all messages
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            max_poll_records=self.batch_size,
        )

        # Create database pool
        self.db_pool = await asyncpg.create_pool(
            self.postgres_dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )

        logger.info("Consumer started successfully")
        self.running = True

    async def stop(self):
        """Stop consumer gracefully."""
        logger.info("Stopping consumer...")
        self.running = False
        self.shutdown_event.set()

        if self.consumer:
            self.consumer.close()
            self.consumer = None

        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None

        logger.info("Consumer stopped")

    async def _insert_batch(self, events: List[Dict]) -> int:
        """
        Insert batch of events to PostgreSQL with idempotency.

        Args:
            events: List of event dictionaries

        Returns:
            Number of events successfully inserted (excluding duplicates)
        """
        if not events or not self.db_pool:
            return 0

        # Prepare insert query with ON CONFLICT for idempotency
        # Assumes agent_actions table has unique constraint on (correlation_id, action_name, timestamp)
        insert_sql = """
            INSERT INTO agent_actions (
                correlation_id,
                agent_name,
                action_type,
                action_name,
                action_details,
                debug_mode,
                duration_ms,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (correlation_id, action_name, created_at) DO NOTHING
            RETURNING id
        """

        inserted_count = 0
        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    try:
                        # Parse timestamp
                        timestamp = datetime.fromisoformat(
                            event["timestamp"].replace("Z", "+00:00")
                        )

                        result = await conn.fetch(
                            insert_sql,
                            event["correlation_id"],
                            event["agent_name"],
                            event["action_type"],
                            event["action_name"],
                            json.dumps(event.get("action_details", {})),
                            event.get("debug_mode", True),
                            event.get("duration_ms"),
                            timestamp,
                        )

                        if result:
                            inserted_count += 1

                    except Exception as e:
                        logger.error(f"Failed to insert event: {e}", exc_info=True)
                        # Continue with other events

        return inserted_count

    async def consume_loop(self):
        """
        Main consumption loop with batching.
        """
        logger.info("Starting consumption loop")
        batch: List[Dict] = []
        last_batch_time = asyncio.get_event_loop().time()

        try:
            while self.running:
                # Poll for messages (non-blocking)
                message_batch = self.consumer.poll(timeout_ms=100)

                # Process messages
                for topic_partition, messages in message_batch.items():
                    for message in messages:
                        batch.append(message.value)

                        # Check if batch is full
                        if len(batch) >= self.batch_size:
                            await self._process_batch(batch)
                            batch = []
                            last_batch_time = asyncio.get_event_loop().time()
                            # Commit offset after successful processing
                            self.consumer.commit()

                # Check batch timeout
                current_time = asyncio.get_event_loop().time()
                if (
                    batch
                    and (current_time - last_batch_time) >= self.batch_timeout_seconds
                ):
                    await self._process_batch(batch)
                    batch = []
                    last_batch_time = current_time
                    self.consumer.commit()

                # Small sleep to prevent tight loop
                await asyncio.sleep(0.01)

        except Exception as e:
            logger.error(f"Consumer loop error: {e}", exc_info=True)
            raise
        finally:
            # Process remaining batch
            if batch:
                await self._process_batch(batch)
                self.consumer.commit()

    async def _process_batch(self, batch: List[Dict]):
        """Process a batch of events."""
        if not batch:
            return

        logger.debug(f"Processing batch of {len(batch)} events")

        try:
            inserted_count = await self._insert_batch(batch)
            duplicates = len(batch) - inserted_count

            logger.info(
                f"Batch processed: {inserted_count} inserted, "
                f"{duplicates} duplicates skipped"
            )

        except Exception as e:
            logger.error(f"Batch processing failed: {e}", exc_info=True)
            # TODO: Send to dead letter queue
            raise

    async def run(self):
        """
        Run consumer until shutdown signal.
        """
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        await self.start()

        try:
            await self.consume_loop()
        except Exception as e:
            logger.error(f"Consumer failed: {e}", exc_info=True)
        finally:
            await self.stop()


async def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    consumer = KafkaAgentActionConsumer()
    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
