#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""merge_sweep skill — dispatch through Kafka transport.

Invoked when the user runs /onex:merge_sweep. Builds a pr-lifecycle-orchestrator-start
payload and publishes it to the contract-driven Kafka topic.

Required env vars:
  KAFKA_BOOTSTRAP_SERVERS  — Kafka bootstrap address (fail-fast if unset)
  OMNI_HOME                — Path to the omni_home monorepo root (for contract resolution)
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path setup — mirror the delegate skill pattern exactly
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).parent  # merge_sweep/_lib/
_SKILL_DIR = _LIB_DIR.parent  # merge_sweep/
_PLUGIN_ROOT = _SKILL_DIR.parent.parent  # plugins/onex/
_HOOKS_LIB = _PLUGIN_ROOT / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _PLUGIN_ROOT.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

_PR_LIFECYCLE_COMMAND_NAME = "node_pr_lifecycle_orchestrator"
_CONTRACT_RELATIVE_PATH = (
    "omnimarket/src/omnimarket/nodes/node_pr_lifecycle_orchestrator/contract.yaml"
)


def _resolve_command_topic() -> str:
    """Return the subscribe topic from the node's contract.yaml.

    Locates the contract via OMNI_HOME, loads it with yaml.safe_load, and
    returns event_bus.subscribe_topics[0]. Returns an empty string on any
    failure so callers can produce a clear error rather than silently misbehaving.
    """
    omni_home = os.environ.get("OMNI_HOME", "").strip()
    if not omni_home:
        return ""
    contract_path = Path(omni_home) / _CONTRACT_RELATIVE_PATH
    if not contract_path.is_file():
        return ""
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        topics = (data or {}).get("event_bus", {}).get("subscribe_topics", [])
        return str(topics[0]) if topics else ""
    except Exception:  # noqa: BLE001
        return ""


def _resolve_correlation_id(correlation_id: str | None) -> uuid.UUID:
    raw = correlation_id or os.environ.get("ONEX_RUN_ID")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            pass
    return uuid.uuid4()


def _dispatch_via_kafka(
    payload: dict,  # type: ignore[type-arg]
    correlation_id_str: str,
    topic: str,
) -> dict:  # type: ignore[type-arg]
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap_servers:
        return {
            "success": False,
            "error": "KAFKA_BOOTSTRAP_SERVERS is not set — cannot dispatch via Kafka",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    try:
        from confluent_kafka import (
            Producer,  # type: ignore[import-untyped] # noqa: PLC0415
        )
    except ImportError:
        return {
            "success": False,
            "error": "confluent_kafka not installed — cannot dispatch via Kafka",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    envelope = {
        "event_type": "omnimarket.pr-lifecycle-orchestrator-start",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "omniclaude.merge-sweep-skill",
        "correlation_id": correlation_id_str,
        "payload": payload,
    }
    message = json.dumps(envelope).encode("utf-8")
    key = correlation_id_str.encode("utf-8")

    delivered: list[bool] = []
    errors: list[str] = []

    def _on_delivery(err: object, _msg: object) -> None:
        if err:
            errors.append(str(err))
            delivered.append(False)
        else:
            delivered.append(True)

    try:
        producer = Producer({"bootstrap.servers": bootstrap_servers})
        producer.produce(topic, value=message, key=key, on_delivery=_on_delivery)
        producer.flush(timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Kafka produce failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    if errors:
        return {
            "success": False,
            "error": f"Kafka delivery failed: {errors[0]}",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    if not delivered:
        return {
            "success": False,
            "error": "Kafka delivery timed out — no confirmation received within 10s",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    return {
        "success": True,
        "correlation_id": correlation_id_str,
        "topic": topic,
        "path": "kafka",
        "dispatch_status": "published",
    }


def dispatch_merge_sweep(
    *,
    run_id: str,
    dry_run: bool = False,
    inventory_only: bool = False,
    fix_only: bool = False,
    merge_only: bool = False,
    repos: str = "",
    max_parallel_polish: int = 20,
    enable_auto_rebase: bool = True,
    use_dag_ordering: bool = True,
    enable_trivial_comment_resolution: bool = True,
    enable_admin_merge_fallback: bool = True,
    admin_fallback_threshold_minutes: int = 15,
    verify: bool = False,
    verify_timeout_seconds: int = 30,
    correlation_id: str | None = None,
    timeout_ms: int = 300_000,
) -> dict:  # type: ignore[type-arg]
    """Dispatch node_pr_lifecycle_orchestrator via Kafka.

    Kafka is the canonical inter-service transport. The topic is resolved
    contract-first from the node's contract.yaml (event_bus.subscribe_topics[0]).
    """
    correlation_uuid = _resolve_correlation_id(correlation_id)
    correlation_id_str = str(correlation_uuid)

    command_topic = _resolve_command_topic()

    payload: dict = {  # type: ignore[type-arg]
        "correlation_id": correlation_id_str,
        "run_id": run_id,
        "dry_run": dry_run,
        "inventory_only": inventory_only,
        "fix_only": fix_only,
        "merge_only": merge_only,
        "repos": repos,
        "max_parallel_polish": max_parallel_polish,
        "enable_auto_rebase": enable_auto_rebase,
        "use_dag_ordering": use_dag_ordering,
        "enable_trivial_comment_resolution": enable_trivial_comment_resolution,
        "enable_admin_merge_fallback": enable_admin_merge_fallback,
        "admin_fallback_threshold_minutes": admin_fallback_threshold_minutes,
        "verify": verify,
        "verify_timeout_seconds": verify_timeout_seconds,
    }

    if not command_topic:
        return {
            "success": False,
            "error": (
                "Cannot resolve command topic from node contract.yaml. "
                f"Set OMNI_HOME so run.py can locate {_CONTRACT_RELATIVE_PATH}"
            ),
            "path": "kafka",
        }
    return _dispatch_via_kafka(
        payload=payload,
        correlation_id_str=correlation_id_str,
        topic=command_topic,
    )


def main() -> None:
    """CLI entry point for /onex:merge_sweep."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="merge_sweep skill — dispatch via Kafka"
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repos", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--fix-only", action="store_true")
    parser.add_argument(
        "--merge-only", "--skip-polish", action="store_true", dest="merge_only"
    )
    parser.add_argument("--max-parallel-polish", type=int, default=20)
    parser.add_argument("--enable-auto-rebase", type=_as_bool_arg, default=True)
    parser.add_argument("--use-dag-ordering", type=_as_bool_arg, default=True)
    parser.add_argument(
        "--enable-trivial-comment-resolution", type=_as_bool_arg, default=True
    )
    parser.add_argument(
        "--enable-admin-merge-fallback", type=_as_bool_arg, default=True
    )
    parser.add_argument("--admin-fallback-threshold-minutes", type=int, default=15)
    parser.add_argument("--verify", type=_as_bool_arg, default=False)
    parser.add_argument("--verify-timeout-seconds", type=int, default=30)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--timeout-ms", type=int, default=300_000)
    args = parser.parse_args()

    from datetime import UTC, datetime  # noqa: PLC0415

    run_id = (
        args.run_id or f"merge-sweep-{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%SZ')}"
    )

    result = dispatch_merge_sweep(
        run_id=run_id,
        dry_run=args.dry_run,
        inventory_only=args.inventory_only,
        fix_only=args.fix_only,
        merge_only=args.merge_only,
        repos=args.repos,
        max_parallel_polish=args.max_parallel_polish,
        enable_auto_rebase=args.enable_auto_rebase,
        use_dag_ordering=args.use_dag_ordering,
        enable_trivial_comment_resolution=args.enable_trivial_comment_resolution,
        enable_admin_merge_fallback=args.enable_admin_merge_fallback,
        admin_fallback_threshold_minutes=args.admin_fallback_threshold_minutes,
        verify=args.verify,
        verify_timeout_seconds=args.verify_timeout_seconds,
        correlation_id=args.correlation_id,
        timeout_ms=args.timeout_ms,
    )

    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(
            f"\nmerge_sweep dispatched ({result.get('path')}) - "
            f"correlation_id={result['correlation_id']}\n"
            f"command_name={_PR_LIFECYCLE_COMMAND_NAME}\n"
            f"dispatch_status={result.get('dispatch_status')}",
            file=sys.stderr,
        )
    else:
        print(f"\nmerge_sweep dispatch failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


def _as_bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


if __name__ == "__main__":
    main()
