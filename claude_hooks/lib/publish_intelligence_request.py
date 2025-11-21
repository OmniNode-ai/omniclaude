#!/usr/bin/env python3
"""
Intelligence Request/Response Event Publisher

Publishes intelligence requests to Kafka event bus and waits for responses.
Replaces direct HTTP calls to Archon MCP with async event-driven pattern.

Usage:
    python publish_intelligence_request.py \\
        --query-type domain \\
        --query "Python async patterns" \\
        --correlation-id "uuid" \\
        --agent-name "agent-research" \\
        --agent-domain "research" \\
        --output-file "{REPO}/tmp/agent_intelligence_domain_uuid.json" \\
        --timeout-ms 500

Topics:
    - intelligence.requests (publish)
    - intelligence.responses (consume with correlation_id filter)

Exit codes:
    0 - Success (response received)
    1 - Timeout (no response within timeout)
    2 - Error (configuration or Kafka error)
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any, Dict, Optional


try:
    from kafka import KafkaConsumer, KafkaProducer
except ImportError:
    print(
        "ERROR: kafka-python not installed. Install with: pip install kafka-python",
        file=sys.stderr,
    )
    sys.exit(2)

logging.basicConfig(
    level=logging.WARNING,  # Reduce noise for hook usage
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class IntelligenceRequestPublisher:
    """
    Publishes intelligence requests to Kafka and waits for responses.

    Uses request/response pattern with correlation IDs for matching.
    """

    TOPIC_REQUESTS = "intelligence.requests"
    TOPIC_RESPONSES = "intelligence.responses"

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        timeout_ms: int = 2000,
    ):
        """
        Initialize intelligence request publisher.

        Args:
            bootstrap_servers: Kafka bootstrap servers
            timeout_ms: Response timeout in milliseconds (default: 2000ms)
        """
        self.bootstrap_servers = bootstrap_servers or os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "omninode-bridge-redpanda:9092"
        )
        self.timeout_ms = timeout_ms

        self._producer: Optional[KafkaProducer] = None
        self._consumer: Optional[KafkaConsumer] = None

        logger.debug(
            f"Initialized publisher (brokers: {self.bootstrap_servers}, timeout: {timeout_ms}ms)"
        )

    def _get_producer(self) -> KafkaProducer:
        """
        Get or create Kafka producer (lazy initialization).

        Returns:
            Kafka producer instance
        """
        if self._producer is None:
            try:
                self._producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    compression_type="gzip",
                    acks=1,
                    retries=2,  # Reduced from 3 for faster failure
                    # CRITICAL: Timeout settings to prevent hangs
                    request_timeout_ms=1000,  # 1s max per request
                    connections_max_idle_ms=5000,  # Close idle connections after 5s
                    metadata_max_age_ms=5000,  # Force metadata refresh after 5s
                    max_block_ms=2000,  # Max 2s block waiting for buffer/metadata
                    api_version_auto_timeout_ms=1000,  # 1s for API version detection
                )
                logger.debug("Kafka producer initialized")
            except Exception as e:
                logger.error(f"Failed to create Kafka producer: {e}")
                raise

        return self._producer

    def _get_consumer(self, correlation_id: str) -> KafkaConsumer:
        """
        Get or create Kafka consumer for responses (lazy initialization).

        Args:
            correlation_id: Correlation ID to filter responses

        Returns:
            Kafka consumer instance
        """
        if self._consumer is None:
            try:
                # Use unique group ID per request to ensure fresh reads
                group_id = f"intelligence-request-{correlation_id}"

                self._consumer = KafkaConsumer(
                    self.TOPIC_RESPONSES,
                    bootstrap_servers=self.bootstrap_servers.split(","),
                    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                    auto_offset_reset="latest",  # Only read new responses
                    group_id=group_id,
                    consumer_timeout_ms=self.timeout_ms,
                    enable_auto_commit=True,
                    # CRITICAL: Timeout hierarchy to prevent hangs
                    # heartbeat < fetch_max_wait < session_timeout < request_timeout < connections_max_idle
                    heartbeat_interval_ms=1000,  # 1s heartbeat
                    fetch_max_wait_ms=2000,  # 2s fetch wait
                    session_timeout_ms=30000,  # 30s session timeout (minimum 6s required by Kafka)
                    request_timeout_ms=40000,  # 40s request timeout
                    connections_max_idle_ms=50000,  # 50s idle before close
                    metadata_max_age_ms=10000,  # 10s metadata refresh
                    api_version_auto_timeout_ms=2000,  # 2s for API version detection
                    max_poll_interval_ms=35000,  # 35s max between polls
                )
                logger.debug(f"Kafka consumer initialized (group: {group_id})")
            except Exception as e:
                logger.error(f"Failed to create Kafka consumer: {e}")
                raise

        return self._consumer

    def publish_request(
        self,
        query_type: str,
        query: str,
        correlation_id: str,
        agent_name: str,
        agent_domain: str,
        match_count: int = 5,
        context: str = "general",
    ) -> bool:
        """
        Publish intelligence request to Kafka.

        Args:
            query_type: Type of query (domain or implementation)
            query: Query text
            correlation_id: Correlation ID for response matching
            agent_name: Agent name requesting intelligence
            agent_domain: Agent domain
            match_count: Number of matches to return
            context: Query context

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "query_type": query_type,
            "query": query,
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "match_count": match_count,
            "context": context,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            producer = self._get_producer()

            # Use correlation_id for partitioning (maintains ordering)
            partition_key = correlation_id.encode("utf-8")

            # Publish sync (wait for acknowledgment)
            future = producer.send(self.TOPIC_REQUESTS, value=event, key=partition_key)
            future.get(timeout=2.0)

            logger.debug(
                f"Published intelligence request (correlation_id: {correlation_id}, query_type: {query_type})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to publish intelligence request: {e}")
            return False

    def wait_for_response(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """
        Wait for intelligence response matching correlation ID.

        Args:
            correlation_id: Correlation ID to match

        Returns:
            Response event if received, None if timeout
        """
        try:
            consumer = self._get_consumer(correlation_id)

            # Poll for messages until timeout
            for message in consumer:
                response = message.value

                # Check if correlation ID matches
                if response.get("correlation_id") == correlation_id:
                    logger.debug(
                        f"Received intelligence response (correlation_id: {correlation_id})"
                    )
                    return response

                # Wrong correlation ID, keep polling
                logger.debug(
                    f"Received response for different correlation_id: {response.get('correlation_id')}"
                )

            # Consumer timeout reached
            logger.warning(
                f"Intelligence response timeout (correlation_id: {correlation_id})"
            )
            return None

        except Exception as e:
            logger.error(f"Error waiting for intelligence response: {e}")
            return None

    def request_and_wait(
        self,
        query_type: str,
        query: str,
        correlation_id: str,
        agent_name: str,
        agent_domain: str,
        output_file: str,
        match_count: int = 5,
    ) -> int:
        """
        Publish intelligence request and wait for response (synchronous MVP).

        Args:
            query_type: Type of query (domain or implementation)
            query: Query text
            correlation_id: Correlation ID for response matching
            agent_name: Agent name requesting intelligence
            agent_domain: Agent domain
            output_file: Path to write response JSON
            match_count: Number of matches to return

        Returns:
            Exit code (0=success, 1=timeout, 2=error)
        """
        # Publish request
        success = self.publish_request(
            query_type=query_type,
            query=query,
            correlation_id=correlation_id,
            agent_name=agent_name,
            agent_domain=agent_domain,
            match_count=match_count,
        )

        if not success:
            logger.error("Failed to publish intelligence request")
            return 2

        # Wait for response
        response = self.wait_for_response(correlation_id)

        if response is None:
            # Timeout - write empty intelligence
            logger.warning(
                f"Intelligence response timeout, writing empty response to {output_file}"
            )
            empty_response = {
                "matches": [],
                "query": query,
                "query_type": query_type,
                "correlation_id": correlation_id,
                "timeout": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            try:
                with open(output_file, "w") as f:
                    json.dump(empty_response, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to write empty response to {output_file}: {e}")
                return 2

            return 1

        # Success - write response to file
        try:
            with open(output_file, "w") as f:
                json.dump(response, f, indent=2)

            logger.info(f"Intelligence response written to {output_file}")
            return 0

        except Exception as e:
            logger.error(f"Failed to write response to {output_file}: {e}")
            return 2

    def close(self):
        """Close Kafka connections."""
        if self._producer is not None:
            try:
                self._producer.flush()
                self._producer.close()
                logger.debug("Kafka producer closed")
            except Exception as e:
                logger.error(f"Error closing Kafka producer: {e}")
            finally:
                self._producer = None

        if self._consumer is not None:
            try:
                self._consumer.close()
                logger.debug("Kafka consumer closed")
            except Exception as e:
                logger.error(f"Error closing Kafka consumer: {e}")
            finally:
                self._consumer = None


def main():
    """Command-line interface for intelligence request publishing."""
    parser = argparse.ArgumentParser(
        description="Publish intelligence request to Kafka event bus and wait for response"
    )

    parser.add_argument(
        "--query-type",
        required=True,
        choices=["domain", "implementation"],
        help="Type of intelligence query (domain or implementation)",
    )

    parser.add_argument(
        "--query",
        required=True,
        help="Query text for intelligence gathering",
    )

    parser.add_argument(
        "--correlation-id",
        required=True,
        help="Correlation ID for response matching",
    )

    parser.add_argument(
        "--agent-name",
        required=True,
        help="Agent name requesting intelligence",
    )

    parser.add_argument(
        "--agent-domain",
        required=True,
        help="Agent domain",
    )

    parser.add_argument(
        "--output-file",
        required=True,
        help="Path to write intelligence response JSON",
    )

    parser.add_argument(
        "--match-count",
        type=int,
        default=5,
        help="Number of matches to return (default: 5)",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=2000,
        help="Response timeout in milliseconds (default: 2000)",
    )

    parser.add_argument(
        "--kafka-brokers",
        default=None,
        help="Kafka bootstrap servers (default: KAFKA_BOOTSTRAP_SERVERS env or omninode-bridge-redpanda:9092)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create publisher
    publisher = IntelligenceRequestPublisher(
        bootstrap_servers=args.kafka_brokers,
        timeout_ms=args.timeout_ms,
    )

    try:
        # Publish request and wait for response
        exit_code = publisher.request_and_wait(
            query_type=args.query_type,
            query=args.query,
            correlation_id=args.correlation_id,
            agent_name=args.agent_name,
            agent_domain=args.agent_domain,
            output_file=args.output_file,
            match_count=args.match_count,
        )

        return exit_code

    finally:
        publisher.close()


if __name__ == "__main__":
    sys.exit(main())
