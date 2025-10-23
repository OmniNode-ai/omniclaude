#!/usr/bin/env python3
"""
Codegen Kafka Consumer Smoke Test

Subscribes to analysis response topic and prints the first matching message.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/codegen_consume_smoke.py

    Or install the package in development mode:

        pip install -e .
"""

import argparse
import asyncio

from agents.lib.kafka_codegen_client import KafkaCodegenClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=str, default=None)
    parser.add_argument("--correlation-id", type=str, default=None)
    parser.add_argument(
        "--rpk", action="store_true", help="Consume via rpk inside container"
    )
    args = parser.parse_args()

    topic = "dev.omniclaude.codegen.analyze.response.v1"

    def matches(payload: dict) -> bool:
        if args.correlation_id:
            return payload.get("correlation_id") == args.correlation_id
        return True

    if args.rpk:
        import json
        import subprocess

        # Use rpk inside the container; read a single message and filter client-side
        cmd = [
            "bash",
            "-lc",
            "docker exec omninode-bridge-redpanda bash -lc 'rpk topic consume dev.omniclaude.codegen.analyze.response.v1 -n 1 -f \"{{.message.value}}\" --brokers localhost:9092'",
        ]
        try:
            out = subprocess.check_output(cmd, text=True)
            try:
                payload = json.loads(out.strip())
                if matches(payload):
                    print(json.dumps(payload, indent=2))
                else:
                    print("No matching message (correlation_id mismatch)")
            except Exception:
                print("Received non-JSON payload from rpk")
        except Exception as e:
            print(f"rpk consume failed: {e}")
        return
    else:
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
