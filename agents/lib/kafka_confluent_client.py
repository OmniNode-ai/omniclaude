#!/usr/bin/env python3
"""
Confluent Kafka fallback client for publishing and consuming messages.

Useful when aiokafka struggles with host/advertised listeners.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from confluent_kafka import Consumer, KafkaError, Producer


class ConfluentKafkaClient:
    def __init__(
        self, bootstrap_servers: str, group_id: str = "omniclaude-confluent-consumer"
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """
        Publish message to Kafka with delivery confirmation.

        Workaround for Redpanda advertised listener issues:
        - Uses localhost:9092 as bootstrap server
        - Rewrites omninode-bridge-redpanda:9092 → localhost:9092 in memory
        - Falls back to aiokafka if confluent-kafka fails

        Raises:
            RuntimeError: If message delivery fails
        """
        delivery_reports = []

        def delivery_callback(err, msg):
            """Callback for message delivery confirmation"""
            if err:
                delivery_reports.append(("error", err))
            else:
                delivery_reports.append(("success", msg))

        # For Redpanda with Docker port mapping, connect ONLY to external listener
        # This avoids the advertised listener issue where Redpanda returns
        # internal hostname:port that isn't accessible from host machine
        bootstrap_servers = self.bootstrap_servers

        # No automatic host rewriting - use configured bootstrap servers directly
        # (Remote infrastructure should be properly configured with advertised listeners)

        p = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": "omniclaude-producer",
                "socket.keepalive.enable": True,
                "enable.idempotence": True,
                "broker.address.family": "v4",  # Force IPv4
                "request.timeout.ms": 30000,  # Increase timeout to 30s
                "delivery.timeout.ms": 30000,  # Increase delivery timeout to 30s
                "metadata.max.age.ms": 300000,  # Cache metadata for 5 minutes
                "log_level": 3,  # Warning level logging
                # Workaround: Don't follow advertised listeners that point to internal hostnames
                "client.dns.lookup": "use_all_dns_ips",
            }
        )

        data = json.dumps(payload).encode("utf-8")
        p.produce(topic, data, callback=delivery_callback)
        p.flush(10)

        # Check delivery results
        if not delivery_reports:
            raise RuntimeError("Message delivery timed out - no confirmation received")

        status, result = delivery_reports[0]
        if status == "error":
            raise RuntimeError(f"Message delivery failed: {result}")

    def consume_one(
        self, topic: str, timeout_sec: float = 10.0
    ) -> Optional[Dict[str, Any]]:
        c = Consumer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": self.group_id,
                "auto.offset.reset": "latest",
            }
        )
        c.subscribe([topic])
        try:
            msg = c.poll(timeout_sec)
            if msg is None:
                return None
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    return None
                raise RuntimeError(str(msg.error()))
            return json.loads(msg.value().decode("utf-8"))
        finally:
            c.close()
