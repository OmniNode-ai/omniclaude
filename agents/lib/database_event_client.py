#!/usr/bin/env python3
"""
Database Event Client - Kafka-based Database Operations

This module provides a Kafka client for event-based database operations,
enabling agents to interact with PostgreSQL via Kafka events instead of
direct asyncpg connections.

Key Features:
- Request-response pattern with correlation tracking
- Async producer/consumer using aiokafka
- CRUD operations: query, insert, update, delete, upsert
- Timeout handling with graceful fallback
- Health check for circuit breaker integration
- Connection pooling and management

Event Flow:
1. Client publishes DATABASE_QUERY_REQUESTED event
2. omninode-bridge database adapter handler processes request
3. Client waits for DATABASE_QUERY_COMPLETED or DATABASE_QUERY_FAILED response
4. On timeout/error: graceful degradation with caller handling fallback

Integration:
- Wire-compatible with omninode-bridge database adapter
- Designed for request-response client usage (not 24/7 consumer service)
- Supports all PostgreSQL CRUD operations

Performance Targets:
- Response time: <100ms p95
- Timeout: 5000ms default (configurable)
- Memory overhead: <20MB
- Success rate: >95%

Created: 2025-10-30
Reference: intelligence_event_client.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path as PathLib
from typing import Any, Dict, List, Optional
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

sys.path.insert(0, str(PathLib.home() / ".claude" / "lib"))
from kafka_config import get_kafka_bootstrap_servers

logger = logging.getLogger(__name__)


class DatabaseEventClient:
    """
    Kafka client for database event publishing and consumption.

    Provides request-response pattern with correlation tracking,
    timeout handling, and graceful fallback for database operations.

    This client uses aiokafka for native async/await integration, perfect
    for request-response patterns. It is wire-compatible with omninode-bridge's
    database adapter service.

    Usage:
        client = DatabaseEventClient(
            bootstrap_servers="localhost:9092",
            request_timeout_ms=5000,
        )

        await client.start()

        try:
            # Query operation
            rows = await client.query(
                query="SELECT * FROM agent_routing_decisions WHERE confidence_score > $1",
                params=[0.8],
                timeout_ms=5000,
            )

            # Insert operation
            result = await client.insert(
                table="agent_execution_logs",
                data={"agent_name": "test-agent", "status": "success"},
            )

            # Update operation
            result = await client.update(
                table="agent_execution_logs",
                data={"status": "completed"},
                filters={"execution_id": "abc123"},
            )

        finally:
            await client.stop()
    """

    # Kafka topic names (following omninode-bridge event architecture)
    TOPIC_REQUEST = "dev.omninode-bridge.database.query-requested.v1"
    TOPIC_COMPLETED = "dev.omninode-bridge.database.query-completed.v1"
    TOPIC_FAILED = "dev.omninode-bridge.database.query-failed.v1"

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        request_timeout_ms: int = 5000,
        consumer_group_id: Optional[str] = None,
    ):
        """
        Initialize database event client.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            request_timeout_ms: Default timeout for requests in milliseconds
            consumer_group_id: Optional consumer group ID (default: auto-generated)
        """
        # Bootstrap servers - use centralized configuration if not provided
        self.bootstrap_servers = bootstrap_servers or get_kafka_bootstrap_servers()
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers must be provided or set via environment variables.\n"
                "Checked variables (in order):\n"
                "  1. KAFKA_BOOTSTRAP_SERVERS (general config)\n"
                "  2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)\n"
                "  3. KAFKA_BROKERS (legacy compatibility)\n"
                "Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092\n"
                "Current values: KAFKA_BOOTSTRAP_SERVERS={}, KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS={}, KAFKA_BROKERS={}".format(
                    os.getenv("KAFKA_BOOTSTRAP_SERVERS", "not set"),
                    os.getenv("KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS", "not set"),
                    os.getenv("KAFKA_BROKERS", "not set"),
                )
            )
        self.request_timeout_ms = request_timeout_ms
        self.consumer_group_id = (
            consumer_group_id or f"omniclaude-database-{uuid4().hex[:8]}"
        )

        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._started = False
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._consumer_ready = asyncio.Event()  # Signal when consumer is polling

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Initialize Kafka producer and consumer.

        Creates producer for publishing requests and consumer for receiving responses.
        Should be called once before making requests.

        Raises:
            KafkaError: If Kafka connection fails
        """
        if self._started:
            self.logger.debug("Database event client already started")
            return

        try:
            self.logger.info(
                f"Starting database event client (broker: {self.bootstrap_servers})"
            )

            # Initialize producer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="gzip",
                linger_ms=20,
                acks="all",
                api_version="auto",
                request_timeout_ms=30000,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()

            # Initialize consumer for response topics
            self._consumer = AIOKafkaConsumer(
                self.TOPIC_COMPLETED,
                self.TOPIC_FAILED,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.consumer_group_id,
                enable_auto_commit=True,
                auto_offset_reset="earliest",  # CRITICAL: Prevent race condition
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await self._consumer.start()

            # CRITICAL: Wait for consumer to have partition assignments
            self.logger.info(
                f"Waiting for consumer partition assignment (topics: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED})..."
            )
            max_wait_seconds = 10
            start_time = asyncio.get_event_loop().time()
            check_count = 0

            while not self._consumer.assignment():
                check_count += 1
                await asyncio.sleep(0.1)
                elapsed = asyncio.get_event_loop().time() - start_time

                # Log progress every 1 second
                if check_count % 10 == 0:
                    self.logger.debug(
                        f"Still waiting for partition assignment... ({elapsed:.1f}s elapsed)"
                    )

                if elapsed > max_wait_seconds:
                    error_msg = (
                        f"Consumer failed to get partition assignment after {max_wait_seconds}s.\n"
                        f"Troubleshooting:\n"
                        f"  1. Check Kafka broker is accessible: {self.bootstrap_servers}\n"
                        f"  2. Verify topics exist: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}\n"
                        f"  3. Check consumer group permissions: {self.consumer_group_id}\n"
                        f"  4. Review Kafka broker logs for connection issues\n"
                        f"  5. Verify network connectivity to Kafka cluster"
                    )
                    self.logger.error(error_msg)
                    raise TimeoutError(error_msg)

            partition_count = len(self._consumer.assignment())
            self.logger.info(
                f"Consumer ready with {partition_count} partition(s): {self._consumer.assignment()}"
            )

            # Start background consumer task AFTER partition assignment confirmed
            asyncio.create_task(self._consume_responses())

            # CRITICAL: Wait for consumer task to actually start polling
            self.logger.info("Waiting for consumer task to start polling...")
            consumer_ready_timeout = 5.0
            try:
                await asyncio.wait_for(
                    self._consumer_ready.wait(), timeout=consumer_ready_timeout
                )
                self.logger.info("Consumer task confirmed polling - ready for requests")
            except asyncio.TimeoutError:
                error_msg = (
                    f"Consumer task failed to start polling within {consumer_ready_timeout}s.\n"
                    f"This indicates the consumer loop did not start properly."
                )
                self.logger.error(error_msg)
                raise TimeoutError(error_msg)

            self._started = True
            self.logger.info("Database event client started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start database event client: {e}")
            await self.stop()
            raise KafkaError(f"Failed to start Kafka client: {e}") from e

    async def stop(self) -> None:
        """
        Close Kafka connections gracefully.

        Stops producer and consumer, cleans up pending requests.
        Should be called when client is no longer needed.
        """
        if not self._started:
            return

        self.logger.info("Stopping database event client")

        try:
            # Stop producer
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

            # Stop consumer
            if self._consumer is not None:
                await self._consumer.stop()
                self._consumer = None

            # Cancel pending requests
            for correlation_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(
                        RuntimeError("Client stopped while request pending")
                    )
            self._pending_requests.clear()

            # Clear consumer ready flag for restart capability
            self._consumer_ready.clear()

            self._started = False
            self.logger.info("Database event client stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping database event client: {e}")

    async def health_check(self) -> bool:
        """
        Check Kafka connection health.

        Returns:
            True if Kafka connection is healthy, False otherwise

        Usage:
            if await client.health_check():
                rows = await client.query(...)
            else:
                # Use fallback database connection
                pass
        """
        if not self._started:
            return False

        try:
            # Verify producer is connected
            if self._producer is None:
                return False

            return True

        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            return False

    async def query(
        self,
        query: str,
        params: Optional[List[Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        timeout_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query via events.

        Args:
            query: SQL query string (use $1, $2 for parameters)
            params: Query parameters (default: None)
            limit: Maximum number of rows to return
            offset: Number of rows to skip
            timeout_ms: Response timeout in milliseconds (default: request_timeout_ms)

        Returns:
            List of rows as dictionaries

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            rows = await client.query(
                query="SELECT * FROM agent_routing_decisions WHERE confidence_score > $1",
                params=[0.8],
                limit=10,
            )

            for row in rows:
                print(f"Agent: {row['selected_agent']}, Confidence: {row['confidence_score']}")
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            operation_type="QUERY",
            query=query,
            params=params or [],
            limit=limit,
            offset=offset,
        )

        # Publish request and wait for response
        try:
            self.logger.debug(
                f"Publishing query request (correlation_id: {correlation_id}, query: {query[:100]}...)"
            )

            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            self.logger.debug(
                f"Query completed (correlation_id: {correlation_id}, rows: {result.get('rows_affected', 0)})"
            )

            return result.get("rows", [])

        except asyncio.TimeoutError:
            self.logger.warning(
                f"Query request timeout (correlation_id: {correlation_id}, timeout: {timeout}ms)"
            )
            raise TimeoutError(
                f"Request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

        except Exception as e:
            self.logger.error(
                f"Query request failed (correlation_id: {correlation_id}): {e}"
            )
            raise

    async def insert(
        self,
        table: str,
        data: Dict[str, Any],
        returning: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Insert a row into a table via events.

        Args:
            table: Table name
            data: Row data as dictionary
            returning: Optional column to return (e.g., "id")
            timeout_ms: Response timeout in milliseconds

        Returns:
            Result dictionary with rows_affected and optional returned columns

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            result = await client.insert(
                table="agent_execution_logs",
                data={
                    "agent_name": "test-agent",
                    "status": "success",
                    "quality_score": 0.95,
                },
                returning="execution_id",
            )

            print(f"Inserted with ID: {result['rows'][0]['execution_id']}")
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Build INSERT query
        columns = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(columns))]
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"

        if returning:
            query += f" RETURNING {returning}"

        params = [data[col] for col in columns]

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            operation_type="INSERT",
            query=query,
            params=params,
            entity_type=table,
        )

        # Publish request and wait for response
        try:
            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            return result

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Insert request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

    async def update(
        self,
        table: str,
        data: Dict[str, Any],
        filters: Dict[str, Any],
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update rows in a table via events.

        Args:
            table: Table name
            data: Columns to update with new values
            filters: WHERE clause conditions
            timeout_ms: Response timeout in milliseconds

        Returns:
            Result dictionary with rows_affected

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            result = await client.update(
                table="agent_execution_logs",
                data={"status": "completed", "quality_score": 0.98},
                filters={"execution_id": "abc123"},
            )

            print(f"Updated {result['rows_affected']} rows")
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Build UPDATE query
        set_clauses = [f"{col} = ${i+1}" for i, col in enumerate(data.keys())]
        where_clauses = [
            f"{col} = ${i+len(data)+1}" for i, col in enumerate(filters.keys())
        ]

        query = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"
        params = list(data.values()) + list(filters.values())

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            operation_type="UPDATE",
            query=query,
            params=params,
            entity_type=table,
            filters=filters,
        )

        # Publish request and wait for response
        try:
            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            return result

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Update request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

    async def delete(
        self,
        table: str,
        filters: Dict[str, Any],
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Delete rows from a table via events.

        Args:
            table: Table name
            filters: WHERE clause conditions
            timeout_ms: Response timeout in milliseconds

        Returns:
            Result dictionary with rows_affected

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            result = await client.delete(
                table="agent_execution_logs",
                filters={"execution_id": "abc123"},
            )

            print(f"Deleted {result['rows_affected']} rows")
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Build DELETE query
        where_clauses = [f"{col} = ${i+1}" for i, col in enumerate(filters.keys())]
        query = f"DELETE FROM {table} WHERE {' AND '.join(where_clauses)}"
        params = list(filters.values())

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            operation_type="DELETE",
            query=query,
            params=params,
            entity_type=table,
            filters=filters,
        )

        # Publish request and wait for response
        try:
            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            return result

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Delete request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

    async def upsert(
        self,
        table: str,
        data: Dict[str, Any],
        conflict_columns: List[str],
        update_columns: Optional[List[str]] = None,
        returning: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Insert or update a row via events (PostgreSQL UPSERT).

        Args:
            table: Table name
            data: Row data as dictionary
            conflict_columns: Columns for conflict detection
            update_columns: Columns to update on conflict (default: all except conflict_columns)
            returning: Optional column to return (e.g., "id")
            timeout_ms: Response timeout in milliseconds

        Returns:
            Result dictionary with rows_affected and optional returned columns

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            result = await client.upsert(
                table="agent_execution_logs",
                data={
                    "execution_id": "abc123",
                    "status": "completed",
                    "quality_score": 0.98,
                },
                conflict_columns=["execution_id"],
                update_columns=["status", "quality_score"],
            )
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Build UPSERT query (INSERT ... ON CONFLICT ... DO UPDATE)
        columns = list(data.keys())
        placeholders = [f"${i+1}" for i in range(len(columns))]

        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        query += f" ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE SET "

        # Determine which columns to update on conflict
        if update_columns is None:
            update_columns = [col for col in columns if col not in conflict_columns]

        update_clauses = [f"{col} = EXCLUDED.{col}" for col in update_columns]
        query += ", ".join(update_clauses)

        if returning:
            query += f" RETURNING {returning}"

        params = [data[col] for col in columns]

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            operation_type="UPSERT",
            query=query,
            params=params,
            entity_type=table,
        )

        # Publish request and wait for response
        try:
            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            return result

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Upsert request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

    def _create_request_payload(
        self,
        correlation_id: str,
        operation_type: str,
        query: str,
        params: List[Any],
        entity_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Build request payload for database operations.

        Args:
            correlation_id: Unique request identifier
            operation_type: Operation type (QUERY, INSERT, UPDATE, DELETE, UPSERT)
            query: SQL query string
            params: Query parameters
            entity_type: Optional table name
            filters: Optional structured filters
            limit: Optional row limit
            offset: Optional row offset

        Returns:
            Request payload dictionary
        """
        payload = {
            "event_id": str(uuid4()),
            "event_type": "DATABASE_QUERY_REQUESTED",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "omniclaude",
            "payload": {
                "operation_type": operation_type,
                "entity_type": entity_type,
                "query": query,
                "params": params,
                "filters": filters or {},
                "limit": limit,
                "offset": offset,
            },
        }

        return payload

    async def _publish_and_wait(
        self,
        correlation_id: str,
        payload: Dict[str, Any],
        timeout_ms: int,
    ) -> Dict[str, Any]:
        """
        Publish request and wait for response with timeout.

        Implements request-response pattern:
        1. Create future for this correlation_id
        2. Publish request event
        3. Wait for response with timeout
        4. Return response or raise timeout

        Args:
            correlation_id: Request correlation ID
            payload: Request payload
            timeout_ms: Response timeout in milliseconds

        Returns:
            Response payload

        Raises:
            asyncio.TimeoutError: If timeout occurs
            KafkaError: If Kafka operation fails
        """
        # Create future for this request
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[correlation_id] = future

        try:
            # Publish request
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")
            await self._producer.send_and_wait(self.TOPIC_REQUEST, payload)

            # Wait for response with timeout
            result = await asyncio.wait_for(
                future, timeout=timeout_ms / 1000.0  # Convert to seconds
            )

            return result

        finally:
            # Clean up pending request
            self._pending_requests.pop(correlation_id, None)

    async def _consume_responses(self) -> None:
        """
        Background task to consume response events.

        Continuously polls for DATABASE_QUERY_COMPLETED and DATABASE_QUERY_FAILED
        events, matches them to pending requests by correlation_id, and resolves
        the corresponding futures.

        This task runs in the background for the lifetime of the client.
        """
        self.logger.info("Starting response consumer task")
        self.logger.info(
            f"Consumer subscribed to topics: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}"
        )

        try:
            if self._consumer is None:
                raise RuntimeError("Consumer not initialized. Call start() first.")

            # Signal that consumer is ready to poll (fixes race condition)
            self._consumer_ready.set()
            self.logger.debug("Consumer task entered polling loop - signaling ready")

            async for msg in self._consumer:
                self.logger.debug(
                    f"[CONSUMER] Received message: topic={msg.topic}, partition={msg.partition}, offset={msg.offset}"
                )
                try:
                    # Parse response
                    response = msg.value

                    # Extract correlation_id
                    correlation_id = response.get("correlation_id")
                    if not correlation_id:
                        self.logger.warning(
                            f"Response missing correlation_id, skipping: {response}"
                        )
                        continue

                    # Find pending request
                    future = self._pending_requests.get(correlation_id)
                    if future is None:
                        self.logger.debug(
                            f"No pending request for correlation_id: {correlation_id}"
                        )
                        continue

                    # Determine event type
                    event_type = response.get("event_type", "")

                    if (
                        event_type == "DATABASE_QUERY_COMPLETED"
                        or msg.topic == self.TOPIC_COMPLETED
                    ):
                        # Success response
                        payload = response.get("payload", {})
                        if not future.done():
                            future.set_result(payload)
                            self.logger.debug(
                                f"Completed request (correlation_id: {correlation_id})"
                            )

                    elif (
                        event_type == "DATABASE_QUERY_FAILED"
                        or msg.topic == self.TOPIC_FAILED
                    ):
                        # Error response
                        payload = response.get("payload", {})
                        error_code = payload.get("error_code", "UNKNOWN")
                        error_message = payload.get("error", "Query failed")

                        if not future.done():
                            future.set_exception(
                                KafkaError(f"{error_code}: {error_message}")
                            )
                            self.logger.warning(
                                f"Failed request (correlation_id: {correlation_id}, error: {error_code})"
                            )

                    else:
                        self.logger.warning(
                            f"Unknown event type: {event_type} (correlation_id: {correlation_id})"
                        )

                except Exception as e:
                    self.logger.error(f"Error processing response: {e}", exc_info=True)
                    continue

        except asyncio.CancelledError:
            self.logger.debug("Response consumer task cancelled")
            raise

        except Exception as e:
            self.logger.error(f"Response consumer task failed: {e}", exc_info=True)
            raise

        finally:
            self.logger.debug("Response consumer task stopped")


# Convenience context manager for automatic start/stop
class DatabaseEventClientContext:
    """
    Context manager for automatic client lifecycle management.

    Usage:
        async with DatabaseEventClientContext() as client:
            rows = await client.query("SELECT * FROM agent_routing_decisions")
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        request_timeout_ms: int = 5000,
    ):
        self.client = DatabaseEventClient(
            bootstrap_servers=bootstrap_servers,
            request_timeout_ms=request_timeout_ms,
        )

    async def __aenter__(self) -> DatabaseEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.stop()
        return False


__all__ = [
    "DatabaseEventClient",
    "DatabaseEventClientContext",
]
