#!/usr/bin/env python3
"""
Hook Event Processor Service

Background service that processes unprocessed hook events from the database.
Implements polling loop, event routing, retry mechanism, and comprehensive error tracking.

Performance Targets:
- Process events within 5 seconds of creation
- Error rate < 1%
- Graceful degradation and auto-recovery

Database Schema:
    hook_events table with columns:
    - id (UUID), source, action, resource, resource_id
    - payload (JSONB), metadata (JSONB)
    - processed (boolean), processing_errors (text array), retry_count (integer)
    - created_at, processed_at

Correlation ID: fe9bbe61-39d7-4124-b6ec-d61de1e0ee41-P0
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.event_handlers import EventHandlerRegistry, HandlerResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("/tmp/hook_event_processor.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class HookEventProcessor:
    """
    Background service for processing hook events from the database.

    Features:
    - Polling loop with configurable interval
    - Event handler routing based on source/action
    - Retry mechanism with exponential backoff
    - Comprehensive error tracking
    - Graceful shutdown on SIGTERM/SIGINT
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        poll_interval: float = 1.0,
        batch_size: int = 100,
        max_retry_count: int = 3,
        retry_backoff_base: float = 2.0,
    ):
        """
        Initialize the hook event processor.

        Args:
            connection_string: PostgreSQL connection string (uses default if None)
            poll_interval: Polling interval in seconds (default: 1.0)
            batch_size: Maximum events to process per batch (default: 100)
            max_retry_count: Maximum retry attempts (default: 3)
            retry_backoff_base: Base for exponential backoff (default: 2.0)
        """
        # Database connection
        if connection_string is None:
            # Honor POSTGRES_PASSWORD with fallback to DB_PASSWORD for backward compatibility
            db_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD", "")
            host = os.getenv("POSTGRES_HOST", "localhost")
            port = os.getenv("POSTGRES_PORT", "5436")
            db = os.getenv("POSTGRES_DB", "omninode_bridge")
            user = os.getenv("POSTGRES_USER", "postgres")
            connection_string = (
                f"host={host} port={port} "
                f"dbname={db} "
                f"user={user} "
                f"password={db_password}"
            )

        self.connection_string = connection_string
        self._conn: Optional[psycopg2.extensions.connection] = None

        # Configuration
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.max_retry_count = max_retry_count
        self.retry_backoff_base = retry_backoff_base

        # Event handler registry
        self.handler_registry = EventHandlerRegistry()

        # Service state
        self._running = False
        self._shutdown_requested = False

        # Metrics
        self.metrics = {
            "events_processed": 0,
            "events_succeeded": 0,
            "events_failed": 0,
            "events_retried": 0,
            "total_errors": 0,
            "start_time": None,
        }

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        logger.info("HookEventProcessor initialized")

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Get or create database connection with automatic reconnection."""
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg2.connect(
                    self.connection_string, cursor_factory=RealDictCursor
                )
                self._conn.autocommit = False
                logger.info("Database connection established")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise

        return self._conn

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self._shutdown_requested = True

    def fetch_unprocessed_events(self) -> List[Dict[str, Any]]:
        """
        Fetch unprocessed events from the database.

        Returns:
            List of event dictionaries ordered by created_at (oldest first)
        """
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM hook_events
                    WHERE processed = FALSE
                      AND COALESCE(retry_count, 0) < %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (self.max_retry_count, self.batch_size),
                )
                events = cur.fetchall()
                return [dict(event) for event in events]

        except Exception as e:
            logger.error(f"Failed to fetch unprocessed events: {e}")
            return []

    def process_event(self, event: Dict[str, Any]) -> HandlerResult:
        """
        Process a single event by routing to appropriate handler.

        Args:
            event: Event dictionary from database

        Returns:
            HandlerResult indicating success/failure and metadata
        """
        event_id = event["id"]
        source = event["source"]
        action = event["action"]

        try:
            # Route event to handler
            handler = self.handler_registry.get_handler(source, action)

            if handler is None:
                logger.warning(
                    f"No handler found for event {event_id} ({source}/{action})"
                )
                return HandlerResult(
                    success=True,  # Mark as success to avoid infinite retries
                    message=f"No handler registered for {source}/{action}",
                    metadata={"skipped": True},
                )

            # Execute handler
            logger.debug(f"Processing event {event_id} with handler {handler.__name__}")
            result = handler(event)

            if result.success:
                logger.info(
                    f"✓ Event {event_id} processed successfully: {result.message}"
                )
            else:
                logger.warning(
                    f"✗ Event {event_id} failed: {result.message} (retry_count={event['retry_count']})"
                )

            return result

        except Exception as e:
            logger.error(f"Exception processing event {event_id}: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                message=f"Exception: {str(e)}",
                error=str(e),
                metadata={"exception_type": type(e).__name__},
            )

    def mark_event_processed(self, event_id: UUID, result: HandlerResult) -> bool:
        """
        Mark event as processed or update retry count.

        Args:
            event_id: Event ID to update
            result: Handler result containing success status and metadata

        Returns:
            True if database update succeeded, False otherwise
        """
        conn = None  # Initialize before try to prevent UnboundLocalError
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                if result.success:
                    # Mark as successfully processed
                    cur.execute(
                        """
                        UPDATE hook_events
                        SET processed = TRUE,
                            processed_at = %s,
                            processing_errors = CASE
                                WHEN processing_errors IS NULL THEN ARRAY[]::text[]
                                ELSE processing_errors
                            END
                        WHERE id = %s
                        """,
                        (datetime.now(timezone.utc), event_id),
                    )
                else:
                    # Increment retry count and append error
                    error_message = result.error or result.message
                    cur.execute(
                        """
                        UPDATE hook_events
                        SET retry_count = COALESCE(retry_count, 0) + 1,
                            processing_errors = COALESCE(processing_errors, ARRAY[]::text[]) || %s
                        WHERE id = %s
                        """,
                        (error_message, event_id),
                    )

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to update event {event_id}: {e}")
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            return False

    def process_batch(self) -> Dict[str, int]:
        """
        Process a batch of unprocessed events.

        Returns:
            Dictionary with batch processing metrics
        """
        batch_metrics = {
            "fetched": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
        }

        try:
            # Fetch unprocessed events
            events = self.fetch_unprocessed_events()
            batch_metrics["fetched"] = len(events)

            if not events:
                logger.debug("No unprocessed events found")
                return batch_metrics

            logger.info(f"Processing batch of {len(events)} events")

            # Process each event
            for event in events:
                if self._shutdown_requested:
                    logger.info("Shutdown requested, stopping batch processing")
                    break

                event_id = event["id"]
                result = self.process_event(event)

                # Update database
                if self.mark_event_processed(event_id, result):
                    batch_metrics["processed"] += 1

                    if result.success:
                        batch_metrics["succeeded"] += 1
                        self.metrics["events_succeeded"] += 1
                    else:
                        batch_metrics["failed"] += 1
                        self.metrics["events_failed"] += 1
                        if (event["retry_count"] or 0) < self.max_retry_count:
                            self.metrics["events_retried"] += 1
                else:
                    logger.error(f"Failed to update event {event_id} in database")
                    batch_metrics["failed"] += 1
                    self.metrics["total_errors"] += 1

                self.metrics["events_processed"] += 1

            # Log batch summary
            logger.info(
                f"Batch complete: {batch_metrics['succeeded']} succeeded, "
                f"{batch_metrics['failed']} failed, {batch_metrics['skipped']} skipped"
            )

        except Exception as e:
            logger.error(f"Error processing batch: {e}", exc_info=True)
            self.metrics["total_errors"] += 1

        return batch_metrics

    def log_metrics(self):
        """Log current service metrics."""
        uptime = (
            time.time() - self.metrics["start_time"]
            if self.metrics["start_time"]
            else 0
        )

        logger.info(
            f"📊 Metrics: "
            f"Processed={self.metrics['events_processed']}, "
            f"Succeeded={self.metrics['events_succeeded']}, "
            f"Failed={self.metrics['events_failed']}, "
            f"Retried={self.metrics['events_retried']}, "
            f"Errors={self.metrics['total_errors']}, "
            f"Uptime={uptime:.0f}s"
        )

    def run(self):
        """
        Main service loop.

        Continuously polls for unprocessed events and processes them.
        Gracefully handles shutdown signals.
        """
        logger.info("🚀 Starting Hook Event Processor Service")
        logger.info(
            f"Configuration: poll_interval={self.poll_interval}s, batch_size={self.batch_size}"
        )

        self._running = True
        self.metrics["start_time"] = time.time()

        # Log metrics every 60 seconds
        last_metrics_log = time.time()
        metrics_interval = 60

        try:
            while self._running and not self._shutdown_requested:
                # Process batch
                batch_start = time.time()
                batch_metrics = self.process_batch()
                batch_duration = time.time() - batch_start

                # Log performance warning if batch takes too long
                if batch_duration > 5.0 and batch_metrics["fetched"] > 0:
                    logger.warning(
                        f"⚠️  Batch processing took {batch_duration:.2f}s "
                        f"(target: <5s for {batch_metrics['fetched']} events)"
                    )

                # Log metrics periodically
                if time.time() - last_metrics_log >= metrics_interval:
                    self.log_metrics()
                    last_metrics_log = time.time()

                # Sleep until next poll
                if not self._shutdown_requested:
                    time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}", exc_info=True)
            self.metrics["total_errors"] += 1
        finally:
            self._running = False
            self.shutdown()

    def shutdown(self):
        """Shutdown the processor service gracefully."""
        logger.info("🛑 Shutting down Hook Event Processor Service")

        # Log final metrics
        self.log_metrics()

        # Close database connection
        if self._conn and not self._conn.closed:
            try:
                self._conn.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")

        logger.info("✅ Hook Event Processor Service stopped")


def main():
    """Main entry point for the service."""
    # Load environment variables
    from dotenv import load_dotenv

    load_dotenv()

    # Create and run processor
    processor = HookEventProcessor(
        poll_interval=float(os.getenv("POLL_INTERVAL", "1.0")),
        batch_size=int(os.getenv("BATCH_SIZE", "100")),
        max_retry_count=int(os.getenv("MAX_RETRY_COUNT", "3")),
    )

    try:
        processor.run()
    except Exception as e:
        logger.error(f"Failed to start processor: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
