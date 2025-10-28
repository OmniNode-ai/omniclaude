#!/usr/bin/env python3
"""
Codegen Kafka Smoke Test

Publishes a CodegenAnalysisRequest event. Use --dry-run to print instead of sending.

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/parallel_execution/codegen_smoke.py

    Or install the package in development mode:

        pip install -e .
"""

import argparse
import asyncio
import json
import os
from uuid import uuid4

from agents.lib.codegen_events import CodegenAnalysisRequest
from agents.lib.kafka_codegen_client import KafkaCodegenClient
from agents.lib.kafka_confluent_client import ConfluentKafkaClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not send to Kafka; just print payload",
    )
    parser.add_argument(
        "--prd-file", type=str, default=None, help="Path to PRD markdown file"
    )
    parser.add_argument(
        "--bootstrap", type=str, default=None, help="Kafka bootstrap servers override"
    )
    parser.add_argument(
        "--confluent", action="store_true", help="Use confluent-kafka client"
    )
    parser.add_argument(
        "--rpk", action="store_true", help="Publish via rpk inside container"
    )
    args = parser.parse_args()

    prd_content = "# Sample PRD\n\n## Overview\nGenerate a user management EFFECT node."
    if args.prd_file:
        with open(args.prd_file, "r") as f:
            prd_content = f.read()

    evt = CodegenAnalysisRequest()
    evt.correlation_id = uuid4()
    evt.payload = {"prd_content": prd_content}

    if args.dry_run:
        print("[DRY-RUN] Would publish to:", evt.to_kafka_topic())
        print(
            json.dumps(
                {
                    "id": str(evt.id),
                    "correlation_id": str(evt.correlation_id),
                    "payload": evt.payload,
                },
                indent=2,
            )
        )
        return

    if args.rpk:
        # Produce inside Redpanda container to bypass advertised-listener issues
        import shlex
        import subprocess

        topic = evt.to_kafka_topic()
        payload = json.dumps(
            {
                "id": str(evt.id),
                "service": evt.service,
                "timestamp": evt.timestamp,
                "correlation_id": str(evt.correlation_id),
                "metadata": evt.metadata,
                "payload": evt.payload,
            }
        )
        cmd = f"docker exec omninode-bridge-redpanda bash -lc 'echo {shlex.quote(payload)} | rpk topic produce {shlex.quote(topic)} --brokers localhost:9092'"
        subprocess.run(cmd, shell=True, check=False)
        print("[rpk] Published CodegenAnalysisRequest", evt.correlation_id)
        return
    elif args.confluent:
        # Use environment variable or fall back to external Redpanda address
        bootstrap_servers = args.bootstrap or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092"
        )
        client = ConfluentKafkaClient(bootstrap_servers=bootstrap_servers)
        client.publish(
            evt.to_kafka_topic(),
            {
                "id": str(evt.id),
                "service": evt.service,
                "timestamp": evt.timestamp,
                "correlation_id": str(evt.correlation_id),
                "metadata": evt.metadata,
                "payload": evt.payload,
            },
        )
        print("[confluent] Published CodegenAnalysisRequest", evt.correlation_id)
        return
    else:
        client = KafkaCodegenClient(bootstrap_servers=args.bootstrap)
        try:
            await client.publish(evt)
            print("Published CodegenAnalysisRequest", evt.correlation_id)
        finally:
            await client.stop_producer()


if __name__ == "__main__":
    asyncio.run(main())
