"""
Check Kafka Topics - Kafka topic status and message flow

Monitors Kafka topic health, consumer group lag, message throughput,
and event bus connectivity for the OmniNode platform.
"""

from .execute import main


__all__ = ["main"]
