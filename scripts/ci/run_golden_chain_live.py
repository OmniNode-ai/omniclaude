#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run the required live golden-chain CI gate.

The gate exercises the authoritative omniclaude sweep over real Redpanda and
Postgres service containers. A bounded CI projection bridge consumes the five
golden-chain topics and materializes the synthetic rows the sweep polls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2 import sql

from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
    GOLDEN_CHAIN_DEFINITIONS,
)

TOPIC_TO_TABLE: dict[str, str] = {
    str(chain.head_topic): chain.tail_table for chain in GOLDEN_CHAIN_DEFINITIONS
}

ALLOWED_TABLES = frozenset(TOPIC_TO_TABLE.values()) | {"golden_chain_sweep_results"}

DDL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS agent_routing_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id UUID UNIQUE NOT NULL,
    selected_agent TEXT NOT NULL,
    confidence_score NUMERIC(5,4),
    routing_strategy TEXT,
    entity_id TEXT,
    session_id TEXT,
    emitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pattern_learning_artifacts (
    pattern_name TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,
    state TEXT NOT NULL,
    correlation_id TEXT,
    emitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS delegation_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id TEXT UNIQUE NOT NULL,
    session_id TEXT,
    task_type TEXT NOT NULL,
    delegate_model TEXT,
    delegated_to TEXT,
    cost_usd NUMERIC DEFAULT 0,
    cost_savings_usd NUMERIC DEFAULT 0,
    delegation_latency_ms INTEGER,
    emitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_routing_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id UUID UNIQUE NOT NULL,
    session_id TEXT,
    selected_model TEXT NOT NULL,
    selected_agent TEXT,
    decision_method TEXT NOT NULL DEFAULT 'fallback',
    emitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_outcomes (
    session_id TEXT PRIMARY KEY,
    correlation_id TEXT UNIQUE NOT NULL,
    outcome TEXT NOT NULL,
    emitted_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS golden_chain_sweep_results (
    id BIGSERIAL PRIMARY KEY,
    sweep_id TEXT NOT NULL,
    chain_name TEXT NOT NULL,
    head_topic TEXT NOT NULL,
    tail_table TEXT NOT NULL,
    status TEXT NOT NULL,
    publish_latency_ms NUMERIC,
    projection_latency_ms NUMERIC,
    assertion_results JSONB,
    error_reason TEXT,
    correlation_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live golden-chain CI gate.")
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=int(os.environ.get("GOLDEN_CHAIN_TIMEOUT_MS", "30000")),
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
    )
    parser.add_argument(
        "--db-dsn",
        default=(
            os.environ.get("OMNIDASH_ANALYTICS_DB_URL")
            or os.environ.get("DATABASE_URL")
        ),
    )
    return parser


def _require(value: str | None, name: str) -> str:
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def initialize_database(db_dsn: str) -> None:
    with psycopg2.connect(db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(DDL)


def _valid_uuid(value: object) -> str:
    return str(UUID(str(value)))


def _timestamp(value: object | None) -> str:
    if isinstance(value, str) and value:
        return value
    return datetime.now(UTC).isoformat()


def _upsert(
    db_dsn: str,
    table: str,
    conflict_key: str,
    row: dict[str, object],
) -> None:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Unsupported projection table: {table}")
    conflict_keys = [key.strip() for key in conflict_key.split(",") if key.strip()]
    if not conflict_keys:
        raise ValueError("conflict_key must contain at least one column")

    columns = list(row)
    assignments = [
        sql.SQL("{} = EXCLUDED.{}").format(
            sql.Identifier(column), sql.Identifier(column)
        )
        for column in columns
        if column not in conflict_keys
    ]
    query = sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"
    ).format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        conflict=sql.SQL(", ").join(sql.Identifier(key) for key in conflict_keys),
        assignments=sql.SQL(", ").join(assignments)
        or sql.SQL("{} = EXCLUDED.{}").format(
            sql.Identifier(conflict_keys[0]), sql.Identifier(conflict_keys[0])
        ),
    )
    with psycopg2.connect(db_dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(query, [row[column] for column in columns])


def _project_registration(payload: dict[str, object], db_dsn: str) -> None:
    _upsert(
        db_dsn,
        "agent_routing_decisions",
        "correlation_id",
        {
            "correlation_id": _valid_uuid(payload["correlation_id"]),
            "selected_agent": str(payload["selected_agent"]),
            "confidence_score": payload.get("confidence_score"),
            "routing_strategy": payload.get("routing_strategy"),
            "entity_id": payload.get("entity_id"),
            "session_id": payload.get("session_id"),
            "emitted_at": _timestamp(payload.get("emitted_at")),
            "projected_at": datetime.now(UTC).isoformat(),
        },
    )


def _project_pattern_learning(payload: dict[str, object], db_dsn: str) -> None:
    _upsert(
        db_dsn,
        "pattern_learning_artifacts",
        "pattern_name",
        {
            "pattern_name": str(payload["pattern_name"]),
            "pattern_type": str(payload["pattern_type"]),
            "state": str(payload["state"]),
            "correlation_id": str(payload.get("correlation_id", "")),
            "emitted_at": _timestamp(payload.get("emitted_at")),
            "projected_at": datetime.now(UTC).isoformat(),
        },
    )


def _project_delegation(payload: dict[str, object], db_dsn: str) -> None:
    delegate_model = str(payload.get("delegate_model") or payload.get("delegated_to"))
    _upsert(
        db_dsn,
        "delegation_events",
        "correlation_id",
        {
            "correlation_id": str(payload["correlation_id"]),
            "session_id": payload.get("session_id"),
            "task_type": str(payload["task_type"]),
            "delegate_model": delegate_model,
            "delegated_to": delegate_model,
            "cost_usd": payload.get("cost_usd", 0),
            "cost_savings_usd": payload.get("cost_savings_usd", 0),
            "delegation_latency_ms": payload.get("delegation_latency_ms"),
            "emitted_at": _timestamp(payload.get("emitted_at")),
            "projected_at": datetime.now(UTC).isoformat(),
        },
    )


def _project_routing(payload: dict[str, object], db_dsn: str) -> None:
    _upsert(
        db_dsn,
        "llm_routing_decisions",
        "correlation_id",
        {
            "correlation_id": _valid_uuid(payload["correlation_id"]),
            "session_id": payload.get("session_id"),
            "selected_model": str(payload["selected_model"]),
            "selected_agent": str(payload["selected_model"]),
            "decision_method": str(payload["decision_method"]),
            "emitted_at": _timestamp(payload.get("emitted_at")),
            "projected_at": datetime.now(UTC).isoformat(),
        },
    )


def _project_evaluation(payload: dict[str, object], db_dsn: str) -> None:
    _upsert(
        db_dsn,
        "session_outcomes",
        "session_id",
        {
            "session_id": str(payload["session_id"]),
            "correlation_id": str(payload["correlation_id"]),
            "outcome": str(payload["outcome"]),
            "emitted_at": _timestamp(payload.get("emitted_at")),
            "projected_at": datetime.now(UTC).isoformat(),
        },
    )


PROJECTORS: dict[str, Callable[[dict[str, object], str], None]] = {
    "agent_routing_decisions": _project_registration,
    "pattern_learning_artifacts": _project_pattern_learning,
    "delegation_events": _project_delegation,
    "llm_routing_decisions": _project_routing,
    "session_outcomes": _project_evaluation,
}


def project_envelope(envelope: dict[str, Any], db_dsn: str) -> None:
    topic = str(envelope.get("event_type") or "")
    table = TOPIC_TO_TABLE.get(topic)
    if table is None:
        return
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"Envelope payload must be an object for topic {topic}")
    PROJECTORS[table](payload, db_dsn)


async def _consume_until_cancelled(
    bootstrap_servers: str,
    db_dsn: str,
    consumer_ready: asyncio.Event,
) -> None:
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        *TOPIC_TO_TABLE,
        bootstrap_servers=bootstrap_servers,
        group_id=f"omniclaude-golden-chain-live-ci-{os.getpid()}",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
    )
    last_error: Exception | None = None
    for attempt in range(1, 31):
        try:
            await consumer.start()
            break
        except Exception as exc:  # noqa: BLE001 - retry service-container startup
            last_error = exc
            sys.stdout.write(
                f"Waiting for Kafka consumer startup ({attempt}/30): {exc}\n"
            )
            await asyncio.sleep(2)
    else:
        raise RuntimeError("Kafka consumer did not start") from last_error
    for _ in range(30):
        if consumer.assignment():
            consumer_ready.set()
            break
        await asyncio.sleep(1)
    else:
        raise RuntimeError("Kafka consumer did not receive partition assignment")
    try:
        async for message in consumer:
            value = message.value
            if not isinstance(value, dict):
                continue
            project_envelope(value, db_dsn)
    finally:
        await consumer.stop()


async def _run_sweep_subprocess(
    bootstrap_servers: str,
    db_dsn: str,
    timeout_ms: int,
) -> int:
    env = os.environ.copy()
    env["KAFKA_BOOTSTRAP_SERVERS"] = bootstrap_servers
    env["OMNIDASH_ANALYTICS_DB_URL"] = db_dsn
    command = [
        sys.executable,
        "-m",
        "omniclaude.nodes.node_golden_chain_sweep_orchestrator",
        "--timeout-ms",
        str(timeout_ms),
        "--bootstrap-servers",
        bootstrap_servers,
        "--db-dsn",
        db_dsn,
        "--json",
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    if stdout:
        sys.stdout.write(stdout.decode("utf-8", errors="replace"))
    return int(process.returncode or 0)


async def run_gate(bootstrap_servers: str, db_dsn: str, timeout_ms: int) -> int:
    initialize_database(db_dsn)
    consumer_ready = asyncio.Event()
    consumer_task = asyncio.create_task(
        _consume_until_cancelled(bootstrap_servers, db_dsn, consumer_ready)
    )
    try:
        await asyncio.wait_for(consumer_ready.wait(), timeout=65)
        return await _run_sweep_subprocess(bootstrap_servers, db_dsn, timeout_ms)
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bootstrap_servers = _require(args.bootstrap_servers, "KAFKA_BOOTSTRAP_SERVERS")
    db_dsn = _require(args.db_dsn, "OMNIDASH_ANALYTICS_DB_URL or DATABASE_URL")
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    return asyncio.run(run_gate(bootstrap_servers, db_dsn, args.timeout_ms))


if __name__ == "__main__":
    sys.exit(main())
