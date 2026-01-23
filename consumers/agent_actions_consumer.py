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
    KAFKA_BOOTSTRAP_SERVERS: Comma-separated Kafka brokers (REQUIRED - no default)
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
import asyncio
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
import psycopg2.pool
from kafka import KafkaConsumer, KafkaProducer, OffsetAndMetadata, TopicPartition
from psycopg2.extras import execute_batch


# Add _shared to path for db_helper
SCRIPT_DIR = Path(__file__).parent
SHARED_DIR = SCRIPT_DIR.parent / "skills" / "_shared"
sys.path.insert(0, str(SHARED_DIR))

# Add agents/lib to path for AgentTraceabilityLogger
AGENTS_LIB_DIR = SCRIPT_DIR.parent / "agents" / "lib"
sys.path.insert(0, str(AGENTS_LIB_DIR))

try:
    from agent_traceability_logger import AgentTraceabilityLogger

    TRACEABILITY_AVAILABLE = True
except ImportError as e:
    logger_temp = logging.getLogger("agent_actions_consumer")
    logger_temp.warning(f"AgentTraceabilityLogger not available: {e}")
    TRACEABILITY_AVAILABLE = False

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings

    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False

# Configure logging
LOG_LEVEL = settings.log_level if SETTINGS_AVAILABLE else os.getenv("LOG_LEVEL", "INFO")
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


# ONEX: exempt - implements external interface (http.server.BaseHTTPRequestHandler)
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks."""

    consumer_instance = None

    def do_GET(self):  # noqa: N802 - Required by HTTPServer
        """Handle GET requests."""
        if self.path == "/health":
            self.send_health_response()
        elif self.path == "/metrics":
            self.send_metrics_response()
        else:
            self.send_response(404)
            self.end_headers()

    def send_health_response(self):
        """Send health check response with atomic state verification."""
        # Atomic health check using threading.Event to prevent race conditions
        # Events provide atomic is_set() checks without requiring locks
        ci = self.consumer_instance
        if ci is not None:
            is_healthy = ci.running_event.is_set() and not ci.shutdown_event.is_set()
        else:
            is_healthy = False

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
        self.running_event = (
            Event()
        )  # Atomic state management to prevent race conditions
        self.metrics = ConsumerMetrics()

        # Retry management for poison message handling
        self.retry_counts: Dict[str, int] = {}  # Track retries per message
        self.max_retries = 3
        self.backoff_base_ms = 100

        # Kafka configuration (no localhost default - must be explicitly configured)
        if SETTINGS_AVAILABLE:
            kafka_brokers_str = (
                config.get("kafka_brokers")
                or settings.get_effective_kafka_bootstrap_servers()
            )
        else:
            kafka_brokers_str = config.get("kafka_brokers") or os.getenv(
                "KAFKA_BOOTSTRAP_SERVERS"
            )

        if not kafka_brokers_str:
            raise ValueError(
                "KAFKA_BOOTSTRAP_SERVERS must be set via config file or environment variable. "
                "Example: KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092"
            )
        self.kafka_brokers = kafka_brokers_str.split(",")

        if SETTINGS_AVAILABLE:
            self.group_id = config.get("group_id", settings.kafka_group_id)
        else:
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
                "agent-execution-logs",
            ],
        )

        # Batch configuration
        if SETTINGS_AVAILABLE:
            self.batch_size = int(config.get("batch_size", settings.batch_size))
            self.batch_timeout_ms = int(
                config.get("batch_timeout_ms", settings.batch_timeout_ms)
            )
        else:
            self.batch_size = int(
                config.get("batch_size", os.getenv("BATCH_SIZE", "100"))
            )
            self.batch_timeout_ms = int(
                config.get("batch_timeout_ms", os.getenv("BATCH_TIMEOUT_MS", "1000"))
            )

        # PostgreSQL configuration
        # Security: POSTGRES_PASSWORD must be set via environment variable (no default)
        if SETTINGS_AVAILABLE:
            postgres_password = (
                config.get("postgres_password")
                or settings.get_effective_postgres_password()
            )
            postgres_host = config.get("postgres_host", settings.postgres_host)
        else:
            postgres_password = config.get("postgres_password") or os.getenv(
                "POSTGRES_PASSWORD"
            )
            postgres_host = config.get("postgres_host") or os.getenv("POSTGRES_HOST")

        if not postgres_password:
            raise ValueError(
                "POSTGRES_PASSWORD environment variable must be set. "
                "No default value provided for security reasons. "
                "Set it in your environment or .env file before starting the consumer."
            )

        # Database host (no localhost default - must be explicitly configured)
        if not postgres_host:
            raise ValueError(
                "POSTGRES_HOST environment variable must be set. "
                "Example: POSTGRES_HOST=192.168.86.200"
            )

        if SETTINGS_AVAILABLE:
            self.db_config = {
                "host": postgres_host,
                "port": int(config.get("postgres_port", settings.postgres_port)),
                "database": config.get("postgres_database", settings.postgres_database),
                "user": config.get("postgres_user", settings.postgres_user),
                "password": postgres_password,
            }
        else:
            self.db_config = {
                "host": postgres_host,
                "port": int(
                    config.get("postgres_port", os.getenv("POSTGRES_PORT", "5436"))
                ),
                "database": config.get(
                    "postgres_database",
                    os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
                ),
                "user": config.get(
                    "postgres_user", os.getenv("POSTGRES_USER", "postgres")
                ),
                "password": postgres_password,
            }

        # Health check configuration
        if SETTINGS_AVAILABLE:
            self.health_check_port = int(
                config.get("health_check_port", settings.health_check_port)
            )
        else:
            self.health_check_port = int(
                config.get("health_check_port", os.getenv("HEALTH_CHECK_PORT", "8080"))
            )

        # Components (initialized in start())
        self.consumer: Optional[KafkaConsumer] = None
        self.dlq_producer: Optional[KafkaProducer] = None
        self.db_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
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

    def _validate_correlation_id(self, event: Dict[str, Any]) -> str:
        """
        Standardized correlation_id validation.

        Tries to extract correlation_id from:
        1. Top-level event field
        2. metadata field (if top-level not found)

        Validates UUID format and generates new UUID if missing or invalid.

        Args:
            event: Event dictionary

        Returns:
            Valid correlation_id string (UUID format)
        """
        # Extract correlation_id from event (try top-level first, then metadata)
        correlation_id = event.get("correlation_id")
        if not correlation_id and "metadata" in event:
            correlation_id = event.get("metadata", {}).get("correlation_id")

        # Validate and normalize correlation_id
        if not correlation_id:
            return str(uuid.uuid4())

        # Handle UUID objects
        if isinstance(correlation_id, uuid.UUID):
            return str(correlation_id)

        # Validate string format
        try:
            uuid.UUID(correlation_id)
            return correlation_id
        except ValueError:
            logger.warning(
                "Invalid correlation_id format: %s, generating new UUID",
                correlation_id,
            )
            return str(uuid.uuid4())

    def _log_file_operation_async(
        self,
        correlation_id: str,
        agent_name: str,
        action_name: str,
        action_details: Dict[str, Any],
        duration_ms: Optional[int] = None,
    ):
        """
        Log file operation to agent_file_operations table asynchronously.

        This runs in a background thread to avoid blocking the consumer.
        If traceability logging fails, it logs a warning but doesn't affect processing.

        Args:
            correlation_id: Correlation ID for tracing
            agent_name: Name of the agent
            action_name: Tool name (Read, Write, Edit, Glob, Grep)
            action_details: Tool parameters and results
            duration_ms: Operation duration
        """
        if not TRACEABILITY_AVAILABLE:
            return

        def run_async_logging():
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Create traceability logger
                tracer = AgentTraceabilityLogger(
                    agent_name=agent_name,
                    correlation_id=correlation_id,
                )

                # Map tool name to operation type
                operation_type_map = {
                    "Read": "read",
                    "Write": "write",
                    "Edit": "edit",
                    "Glob": "glob",
                    "Grep": "grep",
                    "Delete": "delete",
                }
                operation_type = operation_type_map.get(
                    action_name, action_name.lower()
                )

                # Extract file path and content
                file_path = action_details.get("file_path", "unknown")
                content = action_details.get("content")
                content_before = action_details.get("content_before")
                content_after = action_details.get("content_after") or content
                line_range = action_details.get("line_range")

                # Log the file operation
                loop.run_until_complete(
                    tracer.log_file_operation(
                        operation_type=operation_type,
                        file_path=file_path,
                        content_before=content_before,
                        content_after=content_after,
                        tool_name=action_name,
                        line_range=line_range,
                        operation_params=action_details,
                        success=True,
                        duration_ms=duration_ms,
                    )
                )

                logger.debug(
                    f"File operation logged: {operation_type} on {file_path}",
                    extra={
                        "correlation_id": correlation_id,
                        "agent_name": agent_name,
                    },
                )

            except Exception as e:
                logger.warning(
                    f"Failed to log file operation traceability: {e}",
                    extra={
                        "correlation_id": correlation_id,
                        "agent_name": agent_name,
                        "action_name": action_name,
                    },
                )
            finally:
                loop.close()

        # Run in background thread (fire and forget)
        thread = Thread(target=run_async_logging, daemon=True)
        thread.start()

    def setup_kafka_consumer(self):
        """Initialize Kafka consumer."""
        logger.info("Setting up Kafka consumer with consumer group coordination...")
        self.consumer = KafkaConsumer(
            *self.topics,  # Subscribe to multiple topics
            bootstrap_servers=self.kafka_brokers,
            group_id=self.group_id,  # Consumer group for coordination (prevents duplicate processing)
            auto_offset_reset="earliest",
            enable_auto_commit=False,  # Manual commit after batch insert for reliability
            max_poll_records=self.batch_size,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=self.batch_timeout_ms,
        )
        logger.info(
            "Kafka consumer connected to brokers: %s, group: %s (coordination enabled), topics: %s",
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
        """Initialize database connection pool for improved scalability under load."""
        logger.info("Setting up database connection pool...")
        self.db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=5, maxconn=20, **self.db_config
        )
        logger.info(
            "Database connection pool established: %s:%s/%s (min=5, max=20)",
            self.db_config["host"],
            self.db_config["port"],
            self.db_config["database"],
        )

    def _get_db_connection(self):
        """
        Get a connection from the pool.

        Returns a connection that must be returned to the pool using putconn() when done.
        Connection pool handles reconnection automatically for failed connections.
        """
        if self.db_pool is None:
            raise RuntimeError("Database connection pool not initialized")
        return self.db_pool.getconn()

    def setup_health_check(self):
        """Start health check HTTP server."""
        logger.info(
            "Starting health check server on port %s...", self.health_check_port
        )
        HealthCheckHandler.consumer_instance = self
        self.health_server = HTTPServer(
            (
                "0.0.0.0",  # noqa: S104 - Intentional for Docker health checks
                self.health_check_port,
            ),
            HealthCheckHandler,
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

        # Get a connection from the pool
        db_conn = self._get_db_connection()

        try:
            db_conn.autocommit = False  # Use transactions

            with db_conn.cursor() as cursor:
                # Process each topic's events
                for topic, events in events_by_topic.items():
                    if not events:
                        continue

                    if topic == "agent-actions":
                        inserted, duplicates = self._insert_agent_actions(
                            cursor, events
                        )
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
                    elif topic == "agent-execution-logs":
                        inserted, duplicates = self._insert_execution_logs(
                            cursor, events
                        )
                    else:
                        logger.warning(
                            "Unknown topic: %s, skipping %d events", topic, len(events)
                        )
                        continue

                    total_inserted += inserted
                    total_duplicates += duplicates

                db_conn.commit()

            logger.info(
                "Batch insert: %d inserted, %d duplicates (total: %d)",
                total_inserted,
                total_duplicates,
                total_inserted + total_duplicates,
            )

            return total_inserted, total_duplicates

        except Exception as e:
            logger.error("Batch insert failed: %s", e, exc_info=True)
            db_conn.rollback()
            raise
        finally:
            # Always return connection to the pool
            self.db_pool.putconn(db_conn)

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
        file_operations = []  # Track file operations for traceability logging

        for event in events:
            event_id = str(uuid.uuid4())
            correlation_id = self._validate_correlation_id(event)
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

            # Detect file operations for traceability logging
            action_name = event.get("action_name")
            if action_name in ["Read", "Write", "Edit", "Glob", "Grep", "Delete"]:
                file_operations.append(
                    {
                        "correlation_id": correlation_id,
                        "agent_name": event.get("agent_name"),
                        "action_name": action_name,
                        "action_details": event.get("action_details", {}),
                        "duration_ms": event.get("duration_ms"),
                    }
                )

        execute_batch(cursor, insert_sql, batch_data, page_size=100)
        inserted = cursor.rowcount
        duplicates = len(events) - inserted

        # Log file operations to agent_file_operations table asynchronously
        if file_operations and TRACEABILITY_AVAILABLE:
            for file_op in file_operations:
                try:
                    self._log_file_operation_async(
                        correlation_id=file_op["correlation_id"],
                        agent_name=file_op["agent_name"],
                        action_name=file_op["action_name"],
                        action_details=file_op["action_details"],
                        duration_ms=file_op["duration_ms"],
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to initiate file operation traceability: {e}",
                        extra={
                            "correlation_id": file_op["correlation_id"],
                            "action_name": file_op["action_name"],
                        },
                    )

        return inserted, duplicates

    def _insert_routing_decisions(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_routing_decisions events."""
        insert_sql = """
            INSERT INTO agent_routing_decisions (
                id, correlation_id, user_request, selected_agent, confidence_score, alternatives,
                reasoning, routing_strategy, context_snapshot, routing_time_ms, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            # Use standardized correlation_id validation
            correlation_id = self._validate_correlation_id(event)

            batch_data.append(
                (
                    event_id,
                    correlation_id,  # Already a string from validation
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
        """
        Insert agent_transformation_events events with comprehensive schema support.

        Handles both old format (confidence_score) and new format (routing_confidence).
        """
        insert_sql = """
            INSERT INTO agent_transformation_events (
                id, event_type, correlation_id, session_id,
                source_agent, target_agent, transformation_reason,
                user_request, routing_confidence, routing_strategy,
                transformation_duration_ms, initialization_duration_ms, total_execution_duration_ms,
                success, error_message, error_type, quality_score,
                context_snapshot, context_keys, context_size_bytes,
                agent_definition_id, parent_event_id,
                started_at, completed_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s
            )
            ON CONFLICT (id) DO NOTHING
        """

        batch_data = []
        for event in events:
            event_id = str(uuid.uuid4())
            timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())

            # Handle both old format (confidence_score) and new format (routing_confidence)
            # IMPORTANT: Use explicit None check to preserve zero confidence values
            routing_confidence = event.get("routing_confidence")
            if routing_confidence is None:
                routing_confidence = event.get("confidence_score")

            # Use standardized correlation_id validation
            correlation_id = self._validate_correlation_id(event)

            session_id = event.get("session_id")
            if session_id and not isinstance(session_id, uuid.UUID):
                try:
                    session_id = uuid.UUID(session_id)
                except ValueError:
                    session_id = None

            # Parse context_snapshot as JSONB
            context_snapshot = event.get("context_snapshot")
            if context_snapshot and not isinstance(context_snapshot, str):
                context_snapshot = json.dumps(context_snapshot)

            # Parse agent_definition_id and parent_event_id as UUIDs
            agent_definition_id = event.get("agent_definition_id")
            if agent_definition_id:
                try:
                    agent_definition_id = uuid.UUID(agent_definition_id)
                except ValueError:
                    agent_definition_id = None

            parent_event_id = event.get("parent_event_id")
            if parent_event_id:
                try:
                    parent_event_id = uuid.UUID(parent_event_id)
                except ValueError:
                    parent_event_id = None

            batch_data.append(
                (
                    event_id,
                    event.get("event_type", "transformation_complete"),
                    correlation_id,  # Already a string from validation
                    (
                        str(session_id) if session_id else None
                    ),  # Convert UUID to string for psycopg2
                    event.get("source_agent"),
                    event.get("target_agent"),
                    event.get("transformation_reason"),
                    event.get("user_request"),
                    routing_confidence,
                    event.get("routing_strategy"),
                    event.get("transformation_duration_ms"),
                    event.get("initialization_duration_ms"),
                    event.get("total_execution_duration_ms"),
                    event.get("success", True),
                    event.get("error_message"),
                    event.get("error_type"),
                    event.get("quality_score"),
                    context_snapshot,
                    event.get("context_keys"),
                    event.get("context_size_bytes"),
                    (
                        str(agent_definition_id) if agent_definition_id else None
                    ),  # Convert UUID to string for psycopg2
                    (
                        str(parent_event_id) if parent_event_id else None
                    ),  # Convert UUID to string for psycopg2
                    event.get("started_at", timestamp),
                    event.get("completed_at"),
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
            correlation_id = self._validate_correlation_id(event)
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

    def _insert_execution_logs(
        self, cursor, events: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert agent_execution_logs events with upsert for start/complete."""
        insert_sql = """
            INSERT INTO agent_execution_logs (
                execution_id, correlation_id, session_id, agent_name,
                user_prompt, status, metadata, started_at, completed_at,
                duration_ms, quality_score, error_message, error_type,
                project_path, project_name, claude_session_id, terminal_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (execution_id) DO UPDATE SET
                completed_at = COALESCE(EXCLUDED.completed_at, agent_execution_logs.completed_at),
                status = CASE
                    WHEN EXCLUDED.status IN ('success', 'error', 'cancelled')
                    THEN EXCLUDED.status
                    ELSE agent_execution_logs.status
                END,
                duration_ms = COALESCE(EXCLUDED.duration_ms, agent_execution_logs.duration_ms),
                quality_score = COALESCE(EXCLUDED.quality_score, agent_execution_logs.quality_score),
                error_message = COALESCE(EXCLUDED.error_message, agent_execution_logs.error_message),
                error_type = COALESCE(EXCLUDED.error_type, agent_execution_logs.error_type),
                metadata = agent_execution_logs.metadata || COALESCE(EXCLUDED.metadata, '{}'::jsonb)
        """

        batch_data = []
        for event in events:
            execution_id = event.get("execution_id")
            if not execution_id:
                logger.warning(
                    "Skipping event without execution_id: %s",
                    self._validate_correlation_id(event),
                )
                continue

            # Use standardized correlation_id validation
            correlation_id = self._validate_correlation_id(event)

            # Parse timestamps - may be string or datetime
            started_at = event.get("started_at")
            if isinstance(started_at, str):
                started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            elif not started_at:
                started_at = datetime.now(timezone.utc)

            completed_at = event.get("completed_at")
            if isinstance(completed_at, str):
                completed_at = datetime.fromisoformat(
                    completed_at.replace("Z", "+00:00")
                )

            batch_data.append(
                (
                    execution_id,
                    correlation_id,
                    event.get("session_id"),
                    event.get("agent_name"),
                    event.get("user_prompt"),
                    event.get("status", "in_progress"),
                    json.dumps(event.get("metadata", {})),
                    started_at,
                    completed_at,
                    event.get("duration_ms"),
                    event.get("quality_score"),
                    event.get("error_message"),
                    event.get("error_type"),
                    event.get("project_path"),
                    event.get("project_name"),
                    event.get("claude_session_id"),
                    event.get("terminal_id"),
                )
            )

        if not batch_data:
            return 0, 0

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
                logger.warning(
                    "Event sent to DLQ: %s", self._validate_correlation_id(event)
                )

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

            # Commit Kafka offsets after successful DB insert (ensures exactly-once processing with consumer group coordination)
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

            self.running_event.set()  # Atomic state update
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
        self.running_event.clear()  # Atomic state update

        # Close Kafka consumer
        if self.consumer:
            logger.info("Closing Kafka consumer...")
            self.consumer.close()

        # Close DLQ producer
        if self.dlq_producer:
            logger.info("Closing DLQ producer...")
            self.dlq_producer.close()

        # Close database connection pool
        if self.db_pool:
            logger.info("Closing database connection pool...")
            self.db_pool.closeall()

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
