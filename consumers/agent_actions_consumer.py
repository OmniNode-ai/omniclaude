#!/usr/bin/env python3
"""
Agent Observability Kafka Consumer - Production Implementation

Consumes agent observability events from multiple Kafka topics and persists to PostgreSQL with:
- Multi-topic subscription (agent-actions, agent-routing-decisions, agent-transformation-events, router-performance-metrics)
- Topic-based routing to appropriate database tables
- Batch processing (100 events or 1 second intervals)
- Dead letter queue for failed messages
- Graceful shutdown on SIGTERM
- Health check endpoint
- Consumer lag monitoring
- Idempotency handling

Usage:
    python agent_actions_consumer.py [--config config.json]

Environment Variables:
    KAFKA_BROKERS: Comma-separated Kafka brokers (REQUIRED - no default)
    KAFKA_GROUP_ID: Consumer group ID (default: agent-observability-postgres)
    POSTGRES_HOST: PostgreSQL host (REQUIRED - no default)
    POSTGRES_PORT: PostgreSQL port (default: 5436)
    POSTGRES_DATABASE: Database name (default: omninode_bridge)
    POSTGRES_USER: Database user (default: postgres)
    POSTGRES_PASSWORD: Database password (REQUIRED - no default for security)
    BATCH_SIZE: Max events per batch (default: 100)
    BATCH_TIMEOUT_MS: Max wait time for batch (default: 1000)
    HEALTH_CHECK_PORT: Health check HTTP port (default: 8080)
    LOG_LEVEL: Logging level (default: INFO)
"""

import argparse
import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any, Dict, List, Optional

import psycopg2
from kafka import KafkaConsumer, KafkaProducer, OffsetAndMetadata, TopicPartition
from psycopg2.extras import execute_batch

# Add _shared to path for db_helper
SCRIPT_DIR = Path(__file__).parent
SHARED_DIR = SCRIPT_DIR.parent / "skills" / "_shared"
sys.path.insert(0, str(SHARED_DIR))

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("agent_actions_consumer")


class ConsumerMetrics:
    """Track consumer performance metrics."""

    def __init__(self):
        self.messages_consumed = 0
        self.messages_inserted = 0
        self.messages_failed = 0
        self.batches_processed = 0
        self.total_processing_time_ms = 0
        self.last_commit_time = datetime.now(timezone.utc)
        self.started_at = datetime.now(timezone.utc)

    def record_batch(
        self, consumed: int, inserted: int, failed: int, processing_time_ms: float
    ):
        """Record batch processing metrics."""
        self.messages_consumed += consumed
        self.messages_inserted += inserted
        self.messages_failed += failed
        self.batches_processed += 1
        self.total_processing_time_ms += processing_time_ms
        self.last_commit_time = datetime.now(timezone.utc)

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        uptime_seconds = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        avg_processing_time = (
            self.total_processing_time_ms / self.batches_processed
            if self.batches_processed > 0
            else 0
        )

        return {
            "uptime_seconds": uptime_seconds,
            "messages_consumed": self.messages_consumed,
            "messages_inserted": self.messages_inserted,
            "messages_failed": self.messages_failed,
            "batches_processed": self.batches_processed,
            "avg_batch_processing_ms": round(avg_processing_time, 2),
            "messages_per_second": (
                round(self.messages_consumed / uptime_seconds, 2)
                if uptime_seconds > 0
                else 0
            ),
            "last_commit_time": self.last_commit_time.isoformat(),
        }


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks."""

    consumer_instance = None

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self.send_health_response()
        elif self.path == "/metrics":
            self.send_metrics_response()
        else:
            self.send_response(404)
            self.end_headers()

    def send_health_response(self):
        """Send health check response with thread-safe state verification."""
        # Thread-safe atomic health check to prevent TOCTOU race conditions
        # Keep entire response generation inside lock to prevent state changes
        with self.consumer_instance._health_lock:
            is_healthy = (
                self.consumer_instance is not None
                and self.consumer_instance.running
                and not self.consumer_instance.shutdown_event.is_set()
            )

            if is_healthy:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "healthy", "consumer": "running"}
                self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "unhealthy", "consumer": "stopped"}
                self.wfile.write(json.dumps(response).encode())

    def send_metrics_response(self):
        """Send metrics response."""
        if self.consumer_instance:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            metrics = self.consumer_instance.metrics.get_stats()
            self.wfile.write(json.dumps(metrics, indent=2).encode())
        else:
            self.send_response(503)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress access logs."""
        pass


class AgentActionsConsumer:
    """Production-ready Kafka consumer for agent actions."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.shutdown_event = Event()
        self.running = False
        self.metrics = ConsumerMetrics()

        # Retry management for poison message handling
        self.retry_counts: Dict[str, int] = {}  # Track retries per message
        self.max_retries = 3
        self.backoff_base_ms = 100

        # Thread safety for health checks
        self._health_lock = threading.Lock()

        # Kafka configuration (no localhost default - must be explicitly configured)
        kafka_brokers_str = config.get("kafka_brokers") or os.getenv("KAFKA_BROKERS")
        if not kafka_brokers_str:
            raise ValueError(
                "KAFKA_BROKERS must be set via config file or environment variable. "
                "Example: KAFKA_BROKERS=192.168.86.200:9092"
            )
        self.kafka_brokers = kafka_brokers_str.split(",")
        self.group_id = config.get(
            "group_id", os.getenv("KAFKA_GROUP_ID", "agent-observability-postgres")
        )
        # Subscribe to all agent observability topics
        self.topics = config.get(
            "topics",
            [
                "agent-actions",
                "agent-routing-decisions",
                "agent-transformation-events",
                "router-performance-metrics",
                "agent-detection-failures",
            ],
        )

        # Batch configuration
        self.batch_size = int(config.get("batch_size", os.getenv("BATCH_SIZE", "100")))
        self.batch_timeout_ms = int(
            config.get("batch_timeout_ms", os.getenv("BATCH_TIMEOUT_MS", "1000"))
        )

        # PostgreSQL configuration
        # Security: POSTGRES_PASSWORD must be set via environment variable (no default)
        postgres_password = config.get("postgres_password") or os.getenv(
            "POSTGRES_PASSWORD"
        )
        if not postgres_password:
            raise ValueError(
                "POSTGRES_PASSWORD environment variable must be set. "
                "No default value provided for security reasons. "
                "Set it in your environment or .env file before starting the consumer."
            )

        # Database host (no localhost default - must be explicitly configured)
        postgres_host = config.get("postgres_host") or os.getenv("POSTGRES_HOST")
        if not postgres_host:
            raise ValueError(
                "POSTGRES_HOST environment variable must be set. "
                "Example: POSTGRES_HOST=192.168.86.200"
            )

        self.db_config = {
            "host": postgres_host,
            "port": int(
                config.get("postgres_port", os.getenv("POSTGRES_PORT", "5436"))
            ),
            "database": config.get(
                "postgres_database", os.getenv("POSTGRES_DATABASE", "omninode_bridge")
            ),
            "user": config.get("postgres_user", os.getenv("POSTGRES_USER", "postgres")),
            "password": postgres_password,
        }

        # Health check configuration
        self.health_check_port = int(
            config.get("health_check_port", os.getenv("HEALTH_CHECK_PORT", "8080"))
        )

        # Components (initialized in start())
        self.consumer: Optional[KafkaConsumer] = None
        self.dlq_producer: Optional[KafkaProducer] = None
        self.db_conn: Optional[Any] = None
        self.health_server: Optional[HTTPServer] = None

        logger.info(
            "AgentActionsConsumer initialized with config: %s", self._safe_config()
        )

    def _safe_config(self) -> Dict[str, Any]:
        """Return config with sensitive data redacted."""
        safe = self.config.copy()
        if "postgres_password" in safe:
            safe["postgres_password"] = "***REDACTED***"
        return safe

    def setup_kafka_consumer(self):
        """Initialize Kafka consumer."""
        logger.info("Setting up Kafka consumer...")
        self.consumer = KafkaConsumer(
            *self.topics,  # Subscribe to multiple topics
            bootstrap_servers=self.kafka_brokers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=False,  # Manual commit after batch insert
            max_poll_records=self.batch_size,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=self.batch_timeout_ms,
        )
        logger.info(
            "Kafka consumer connected to brokers: %s, group: %s, topics: %s",
            self.kafka_brokers,
            self.group_id,
            ", ".join(self.topics),
        )

    def setup_dlq_producer(self):
        """Initialize dead letter queue producer."""
        logger.info("Setting up DLQ producer...")
        self.dlq_producer = KafkaProducer(
            bootstrap_servers=self.kafka_brokers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        logger.info("DLQ producer initialized")

    def setup_database(self):
        """Initialize database connection."""
        logger.info("Setting up database connection...")
        self.db_conn = psycopg2.connect(**self.db_config)
        self.db_conn.autocommit = False  # Use transactions
        logger.info(
            "Database connection established: %s:%s/%s",
            self.db_config["host"],
            self.db_config["port"],
            self.db_config["database"],
        )

    def setup_health_check(self):
        """Start health check HTTP server."""
        logger.info(
            "Starting health check server on port %s...", self.health_check_port
        )
        HealthCheckHandler.consumer_instance = self
        self.health_server = HTTPServer(
            ("0.0.0.0", self.health_check_port), HealthCheckHandler
        )

        # Run in background thread
        health_thread = Thread(target=self.health_server.serve_forever, daemon=True)
        health_thread.start()
        logger.info(
            "Health check server running at http://0.0.0.0:%s/health",
            self.health_check_port,
        )

    def insert_batch(
        self, events_by_topic: Dict[str, List[Dict[str, Any]]]
    ) -> tuple[int, int]:
        """
        Insert batch of events to PostgreSQL with idempotency.
        Routes events to appropriate tables based on topic.

        Args:
            events_by_topic: Dictionary mapping topic names to lists of events

        Returns:
            Tuple of (inserted_count, duplicate_count)
        """
        if not events_by_topic:
            return 0, 0

        total_inserted = 0
        total_duplicates = 0

        try:
            cursor = self.db_conn.cursor()

            # Process each topic's events
            for topic, events in events_by_topic.items():
                if not events:
                    continue

                if topic == "agent-actions":
                    inserted, duplicates = self._insert_agent_actions(cursor, events)
                elif topic == "agent-routing-decisions":
                    inserted, duplicates = self._insert_routing_decisions(
                        cursor, events
                    )
                elif topic == "agent-transformation-events":
                    inserted, duplicates = self._insert_transformation_events(
                        cursor, events
                    )
                elif topic == "router-performance-metrics":
                    inserted, duplicates = self._insert_performance_metrics(
                        cursor, events
                    )
                elif topic == "agent-detection-failures":
                    inserted, duplicates = self._insert_detection_failures(
                        cursor, events
                    )
                else:
                    logger.warning(
                        "Unknown topic: %s, skipping %d events", topic, len(events)
                    )
                    continue

                total_inserted += inserted
                total_duplicates += duplicates

            self.db_conn.commit()
            cursor.close()

            logger.info(
                "Batch insert: %d inserted, %d duplicates (total: %d)",
                total_inserted,
                total_duplicates,
                total_inserted + total_duplicates,
            )

            return total_inserted, total_duplicates

        except Exception as e:
            logger.error("Batch insert failed: %s", e, exc_info=True)
            self.db_conn.rollback()
            raise

    def _insert_agent_actions(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_actions events."""
        insert_sql = """
            INSERT INTO agent_actions (
                id, correlation_id, agent_name, action_type, action_name,
                action_details, debug_mode, duration_ms, created_at,
                project_path, project_name, working_directory
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            correlation_id = event.get("correlation_id")
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            batch_data.append(
                (
                    event_id,
                    correlation_id,
                    event.get("agent_name"),
                    event.get("action_type"),
                    event.get("action_name"),
                    json.dumps(event.get("action_details", {})),
                    event.get("debug_mode", True),
                    event.get("duration_ms"),
                    timestamp,
                    event.get("project_path"),  # Extract project context
                    event.get("project_name"),
                    event.get("working_directory"),
                )
            )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted
        return inserted, duplicates

    def _insert_routing_decisions(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_routing_decisions events."""
        insert_sql = """
            INSERT INTO agent_routing_decisions (
                id, project_name, user_request, selected_agent, confidence_score, alternatives,
                reasoning, routing_strategy, context, routing_time_ms, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            batch_data.append(
                (
                    event_id,
                    event.get("project_name"),  # Extract project_name from event
                    event.get("user_request", ""),
                    event.get("selected_agent"),
                    event.get("confidence_score"),
                    json.dumps(event.get("alternatives", [])),
                    event.get("reasoning"),
                    event.get("routing_strategy"),
                    json.dumps(event.get("context", {})),
                    event.get("routing_time_ms"),
                    timestamp,
                )
            )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted
        return inserted, duplicates

    def _insert_transformation_events(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_transformation_events events."""
        insert_sql = """
            INSERT INTO agent_transformation_events (
                id, source_agent, target_agent, transformation_reason,
                confidence_score, transformation_duration_ms, success, created_at,
                project_path, project_name, claude_session_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            batch_data.append(
                (
                    event_id,
                    event.get("source_agent"),
                    event.get("target_agent"),
                    event.get("transformation_reason"),
                    event.get("confidence_score"),
                    event.get("transformation_duration_ms"),
                    event.get("success", True),
                    timestamp,
                    event.get("project_path"),  # Extract project context
                    event.get("project_name"),
                    event.get(
                        "session_id"
                    ),  # Note: event uses session_id, DB uses claude_session_id
                )
            )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted
        return inserted, duplicates

    def _insert_performance_metrics(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert router_performance_metrics events."""
        insert_sql = """
            INSERT INTO router_performance_metrics (
                id, query_text, routing_duration_ms, cache_hit,
                trigger_match_strategy, confidence_components, candidates_evaluated, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            batch_data.append(
                (
                    event_id,
                    event.get("query_text"),
                    event.get("routing_duration_ms"),
                    event.get("cache_hit", False),
                    event.get("trigger_match_strategy"),
                    json.dumps(event.get("confidence_components", {})),
                    event.get("candidates_evaluated"),
                    timestamp,
                )
            )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted
        return inserted, duplicates

    def _derive_detection_status(self, failure_reason: str) -> str:
        """
        Derive detection status from failure reason text.

        Args:
            failure_reason: The failure reason string from the event

        Returns:
            Detection status: "no_detection", "timeout", "low_confidence", or "error"
        """
        reason_lower = failure_reason.lower()

        # Use mapping approach for cleaner logic
        if "no agent" in reason_lower or "not detected" in reason_lower:
            return "no_detection"
        elif "timeout" in reason_lower:
            return "timeout"
        elif "confidence" in reason_lower:
            return "low_confidence"
        else:
            return "error"

    def _insert_detection_failures(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_detection_failures events."""
        insert_sql = """
            INSERT INTO agent_detection_failures (
                correlation_id, user_prompt, prompt_length, prompt_hash,
                detection_status, failure_reason, detection_metadata,
                attempted_methods, project_path, project_name,
                claude_session_id, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (correlation_id) DO NOTHING
        """

        batch_data = []
        for event in events:
            correlation_id = event.get("correlation_id")
            user_request = event.get("user_request", "")
            prompt_length = len(user_request)
            prompt_hash = hashlib.sha256(user_request.encode()).hexdigest()
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            # Derive detection status from failure reason using helper method
            failure_reason = event.get("failure_reason", "")
            detection_status = self._derive_detection_status(failure_reason)

            batch_data.append(
                (
                    correlation_id,
                    user_request,
                    prompt_length,
                    prompt_hash,
                    detection_status,
                    failure_reason,
                    json.dumps(event.get("error_details", {})),
                    json.dumps(event.get("attempted_methods", [])),
                    event.get("project_path"),
                    event.get("project_name"),
                    event.get("session_id"),
                    timestamp,
                )
            )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted
        return inserted, duplicates

    def send_to_dlq(
        self,
        events: List[Dict[str, Any]],
        error: str,
        topic: str = "agent-observability",
    ):
        """Send failed events to dead letter queue."""
        dlq_topic = f"{topic}-dlq"

        for event in events:
            try:
                dlq_event = {
                    "original_event": event,
                    "error": str(error),
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "consumer_group": self.group_id,
                }

                self.dlq_producer.send(dlq_topic, value=dlq_event)
                logger.warning("Event sent to DLQ: %s", event.get("correlation_id"))

            except Exception as e:
                logger.error("Failed to send event to DLQ: %s", e)

        # Flush to ensure delivery
        self.dlq_producer.flush()

    def process_batch(self, messages: List[Any]) -> tuple[int, int]:
        """
        Process a batch of Kafka messages.

        Returns:
            Tuple of (inserted_count, failed_count)
        """
        if not messages:
            return 0, 0

        start_time = time.time()
        events_by_topic = {}
        failed_events = []

        # Extract and group events by topic
        for msg in messages:
            try:
                topic = msg.topic
                if topic not in events_by_topic:
                    events_by_topic[topic] = []
                events_by_topic[topic].append(msg.value)
            except Exception as e:
                logger.error("Failed to deserialize message: %s", e)
                failed_events.append(msg.value)

        # Insert batch to database
        inserted = 0
        failed = 0

        try:
            inserted, duplicates = self.insert_batch(events_by_topic)
            failed = len(failed_events)

            # Commit Kafka offsets after successful DB insert
            self.consumer.commit()

            # Send failed events to DLQ
            if failed_events:
                self.send_to_dlq(failed_events, "Deserialization failed")

        except Exception as e:
            logger.error("Batch processing failed: %s", e, exc_info=True)

            # Track retries and apply exponential backoff to prevent infinite loops
            failed_events = []
            committable_offsets = []

            for msg in messages:
                msg_key = f"{msg.topic}:{msg.partition}:{msg.offset}"
                retry_count = self.retry_counts.get(msg_key, 0)

                if retry_count >= self.max_retries:
                    # Exceeded retries - send to DLQ and commit offset to move past poison message
                    logger.error(
                        "Message %s exceeded %d retries, sending to DLQ and committing offset",
                        msg_key,
                        self.max_retries,
                    )
                    failed_events.append(msg.value)
                    committable_offsets.append(msg)
                    # Clean up retry tracking
                    del self.retry_counts[msg_key]
                else:
                    # Increment retry count and apply exponential backoff
                    self.retry_counts[msg_key] = retry_count + 1
                    backoff_ms = self.backoff_base_ms * (2**retry_count)
                    logger.warning(
                        "Message %s retry %d/%d, backoff %dms",
                        msg_key,
                        retry_count + 1,
                        self.max_retries,
                        backoff_ms,
                    )
                    time.sleep(backoff_ms / 1000)

            # Send poison messages to DLQ
            if failed_events:
                self.send_to_dlq(failed_events, str(e))

            # CRITICAL: Commit offsets for messages that exceeded retries
            # This prevents infinite retry loops by moving the consumer past poison messages
            if committable_offsets:
                for msg in committable_offsets:
                    self.consumer.commit(
                        {
                            TopicPartition(msg.topic, msg.partition): OffsetAndMetadata(
                                msg.offset + 1, None
                            )
                        }
                    )
                logger.info(
                    "Committed %d offsets after max retries to prevent infinite loop",
                    len(committable_offsets),
                )

            failed = len(failed_events)

        # Record metrics
        processing_time_ms = (time.time() - start_time) * 1000
        self.metrics.record_batch(len(messages), inserted, failed, processing_time_ms)

        logger.info(
            "Batch processed: %d messages, %d inserted, %d failed, %.2f ms (topics: %s)",
            len(messages),
            inserted,
            failed,
            processing_time_ms,
            ", ".join(events_by_topic.keys()),
        )

        return inserted, failed

    def consume_loop(self):
        """Main consumer loop with batch processing."""
        logger.info("Starting consume loop...")

        batch = []
        batch_start_time = time.time()

        while not self.shutdown_event.is_set():
            try:
                # Poll for messages with timeout
                messages = self.consumer.poll(timeout_ms=100)

                for topic_partition, msgs in messages.items():
                    batch.extend(msgs)

                # Process batch if size threshold or timeout reached
                current_time = time.time()
                batch_age_ms = (current_time - batch_start_time) * 1000

                if len(batch) >= self.batch_size or (
                    batch and batch_age_ms >= self.batch_timeout_ms
                ):
                    self.process_batch(batch)
                    batch = []
                    batch_start_time = time.time()

            except Exception as e:
                logger.error("Error in consume loop: %s", e, exc_info=True)
                time.sleep(1)  # Backoff on error

        # Process remaining messages before shutdown
        if batch:
            logger.info(
                "Processing remaining %d messages before shutdown...", len(batch)
            )
            self.process_batch(batch)

    def start(self):
        """Start the consumer."""
        logger.info("Starting AgentActionsConsumer...")

        try:
            # Setup components
            self.setup_kafka_consumer()
            self.setup_dlq_producer()
            self.setup_database()
            self.setup_health_check()

            # Register signal handlers
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)

            self.running = True
            logger.info("Consumer started successfully")

            # Start consuming
            self.consume_loop()

        except Exception as e:
            logger.error("Failed to start consumer: %s", e, exc_info=True)
            self.shutdown()
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Received signal %s, shutting down gracefully...", signum)
        self.shutdown()

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down consumer...")
        self.shutdown_event.set()
        self.running = False

        # Close Kafka consumer
        if self.consumer:
            logger.info("Closing Kafka consumer...")
            self.consumer.close()

        # Close DLQ producer
        if self.dlq_producer:
            logger.info("Closing DLQ producer...")
            self.dlq_producer.close()

        # Close database connection
        if self.db_conn:
            logger.info("Closing database connection...")
            self.db_conn.close()

        # Shutdown health check server
        if self.health_server:
            logger.info("Stopping health check server...")
            self.health_server.shutdown()

        logger.info("Consumer shutdown complete")

        # Log final metrics
        final_metrics = self.metrics.get_stats()
        logger.info("Final metrics: %s", json.dumps(final_metrics, indent=2))


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file or environment."""
    config = {}

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            config = json.load(f)
        logger.info("Loaded config from file: %s", config_path)

    return config


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Agent Actions Kafka Consumer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", help="Path to config JSON file")

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Create and start consumer
    consumer = AgentActionsConsumer(config)

    try:
        consumer.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        consumer.shutdown()
    except Exception as e:
        logger.error("Consumer failed: %s", e, exc_info=True)
        consumer.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
