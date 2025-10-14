#!/usr/bin/env python3
"""
Codegen Kafka Consumer Smoke Test

Subscribes to analysis response topic and prints the first matching message.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.lib.kafka_codegen_client import KafkaCodegenClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=str, default=None)
    parser.add_argument("--correlation-id", type=str, default=None)
    args = parser.parse_args()

    topic = "dev.omniclaude.codegen.analyze.response.v1"

    def matches(payload: dict) -> bool:
        if args.correlation_id:
            return payload.get("correlation_id") == args.correlation_id
        return True

    client = KafkaCodegenClient(bootstrap_servers=args.bootstrap)
    msg = await client.consume_until(topic, matches, timeout_seconds=10.0)
    if msg is None:
        print("No message received within timeout")
    else:
        import json
        print(json.dumps(msg, indent=2))
    await client.stop_consumer()


if __name__ == "__main__":
    asyncio.run(main())


