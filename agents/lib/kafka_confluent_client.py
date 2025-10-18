#!/usr/bin/env python3
"""
Confluent Kafka fallback client for publishing and consuming messages.

Useful when aiokafka struggles with host/advertised listeners.
"""

from __future__ import annotations

import json
from typing import Optional, Dict, Any

from confluent_kafka import Producer, Consumer, KafkaError


class ConfluentKafkaClient:
    def __init__(self, bootstrap_servers: str, group_id: str = "omniclaude-confluent-consumer") -> None:
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        p = Producer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "socket.keepalive.enable": True,
                "enable.idempotence": True,
            }
        )
        data = json.dumps(payload).encode("utf-8")
        p.produce(topic, data)
        p.flush(10)

    def consume_one(self, topic: str, timeout_sec: float = 10.0) -> Optional[Dict[str, Any]]:
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
