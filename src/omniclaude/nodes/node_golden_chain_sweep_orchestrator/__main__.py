# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI entrypoint for the live golden-chain sweep orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from omniclaude.nodes.node_golden_chain_sweep_orchestrator.models.model_sweep_request import (
    ModelSweepRequest,
)
from omniclaude.nodes.node_golden_chain_sweep_orchestrator.node import run_sweep


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the live golden-chain Kafka-to-DB sweep."
    )
    parser.add_argument(
        "--chains",
        nargs="+",
        default=None,
        help="Optional chain names to run. Defaults to all registered chains.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=15000,
        help="Per-chain DB poll timeout in milliseconds.",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
        help="Kafka bootstrap servers. Defaults to KAFKA_BOOTSTRAP_SERVERS.",
    )
    parser.add_argument(
        "--db-dsn",
        default=(
            os.environ.get("OMNIDASH_ANALYTICS_DB_URL")
            or os.environ.get("DATABASE_URL")
        ),
        help="Postgres DSN for omnidash_analytics.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the sweep summary as JSON.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if not args.bootstrap_servers:
        raise SystemExit("KAFKA_BOOTSTRAP_SERVERS or --bootstrap-servers is required")
    if not args.db_dsn:
        raise SystemExit(
            "OMNIDASH_ANALYTICS_DB_URL, DATABASE_URL, or --db-dsn is required"
        )

    summary = await run_sweep(
        ModelSweepRequest(chain_filter=args.chains, timeout_ms=args.timeout_ms),
        bootstrap_servers=str(args.bootstrap_servers),
        db_dsn=str(args.db_dsn),
    )
    summary_json = summary.model_dump(mode="json")
    sys.stdout.write(json.dumps(summary_json, indent=2, sort_keys=True))
    sys.stdout.write("\n")

    if (
        summary.overall_status == "pass"
        and summary.fail_count == 0
        and summary.timeout_count == 0
        and summary.error_count == 0
    ):
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
