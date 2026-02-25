# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Omniclaude runtime service entrypoint.

Provides the ``start`` command for running the omniclaude runtime service,
including a ``--dry-run`` mode for validating the environment before deployment.

Usage:
    uv run python -m omniclaude.runtime start
    uv run python -m omniclaude.runtime start --dry-run

Tickets:
    OMN-2801 - Add omniclaude runtime service entrypoint
    OMN-2797 - Skill Node Runtime: Wire Effect Node Backends + Dispatcher Integration

Dry-run validation checklist:
    1. KAFKA_BOOTSTRAP_SERVERS env var is set
    2. OMNICLAUDE_CONTRACTS_ROOT env var is set
    3. All contracts are parseable (threshold: >= 80%)
    4. Both backends are available (advisory only — does not fail)
    5. Route matcher works for canonical topic

Exit codes:
    0 — all required checks pass (dry-run) or service started (live)
    1 — one or more required checks failed (dry-run)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Dry-run validation
# ---------------------------------------------------------------------------


def _check_env_vars() -> tuple[bool, str]:
    """Validate required environment variables.

    Returns:
        (ok, message) tuple.
    """
    kafka = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    contracts_root = os.environ.get("OMNICLAUDE_CONTRACTS_ROOT", "").strip()

    if not kafka:
        return False, "KAFKA_BOOTSTRAP_SERVERS is not set"
    if not contracts_root:
        return False, "OMNICLAUDE_CONTRACTS_ROOT is not set"
    return True, "OK"


def _check_contracts(contracts_root: str) -> tuple[bool, str, int, int]:
    """Parse all contract.yaml files and count successes.

    Returns:
        (ok, message, parsed_count, total_count) tuple.
        ok is True if parsed_count / total_count >= 0.80.
    """
    try:
        import yaml
    except ImportError:
        return False, "PyYAML not available", 0, 0

    root = Path(contracts_root)
    if not root.exists():
        return False, f"OMNICLAUDE_CONTRACTS_ROOT does not exist: {root}", 0, 0

    contract_files = sorted(root.glob("**/contract.yaml"))
    total = len(contract_files)
    if total == 0:
        return False, f"No contract.yaml files found in {root}", 0, 0

    parsed = 0
    for path in contract_files:
        try:
            with path.open() as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and data.get("name"):
                parsed += 1
        except Exception:
            pass  # count as failed

    threshold = 0.80
    ok = (parsed / total) >= threshold
    msg = f"{parsed}/{total} OK"
    return ok, msg, parsed, total


def _check_backends() -> tuple[str, str]:
    """Check availability of both execution backends.

    Performs an import-level check only — does not make network calls.
    Returns advisory status strings; failures do not fail the dry-run.

    Returns:
        (claude_code_status, vllm_status) tuple.
    """
    # Check claude_code backend
    claude_code_status = "OK"
    try:
        from omniclaude.nodes.node_claude_code_session_effect import (  # noqa: F401
            node as _cc_node,
        )
    except Exception as exc:
        claude_code_status = f"WARN ({exc})"

    # Check vllm backend (local LLM inference effect)
    vllm_status = "OK"
    try:
        from omniclaude.nodes.node_local_llm_inference_effect import (  # noqa: F401
            node as _vllm_node,
        )
    except Exception as exc:
        vllm_status = f"WARN ({exc})"

    return claude_code_status, vllm_status


def _check_route_matcher() -> tuple[bool, str]:
    """Validate that the route matcher handles canonical omniclaude topics.

    Returns:
        (ok, message) tuple.
    """
    try:
        from omnibase_core.enums import EnumMessageCategory
        from omnibase_core.models.dispatch.model_dispatch_route import (
            ModelDispatchRoute,
        )

        route = ModelDispatchRoute(
            route_id="dry-run-check",
            topic_pattern="onex.cmd.omniclaude.*.v1",
            handler_id="dry-run-handler",
            message_category=EnumMessageCategory.COMMAND,
            message_type="dry-run",
        )
        if route.matches_topic("onex.cmd.omniclaude.onex-status.v1"):
            return True, "OK (pattern matches onex.cmd.omniclaude.onex-status.v1)"
        return (
            False,
            "Route matcher returned False for onex.cmd.omniclaude.onex-status.v1",
        )
    except Exception as exc:
        return False, f"Route matcher error: {exc}"


def _run_dry_run() -> int:
    """Execute the full dry-run validation checklist.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    failures: list[str] = []

    # 1. Environment variables
    env_ok, env_msg = _check_env_vars()
    if not env_ok:
        print(f"ERROR: {env_msg}", file=sys.stderr)
        failures.append(env_msg)

    # 2. Route matcher (can check without env vars)
    route_ok, route_msg = _check_route_matcher()
    if route_ok:
        print(f"Route matcher: {route_msg}")
    else:
        print(f"ERROR: Route matcher: {route_msg}", file=sys.stderr)
        failures.append(f"Route matcher: {route_msg}")

    # 3. Contracts (requires OMNICLAUDE_CONTRACTS_ROOT)
    if env_ok or os.environ.get("OMNICLAUDE_CONTRACTS_ROOT"):
        contracts_root = os.environ.get("OMNICLAUDE_CONTRACTS_ROOT", "")
        contract_ok, contract_msg, _parsed, _total = _check_contracts(contracts_root)
        if contract_ok:
            # 4. Backends (advisory only — check alongside contracts)
            claude_code_status, vllm_status = _check_backends()
            print(
                f"Contracts: {contract_msg} | Backends: claude_code={claude_code_status} vllm={vllm_status}"
            )
            print("Note: contract cache is static; restart required for changes")
        else:
            print(f"ERROR: Contracts: {contract_msg}", file=sys.stderr)
            failures.append(f"Contracts: {contract_msg}")
    elif not env_ok:
        # Already reported env failure above; skip contracts check
        pass

    if failures:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Live start (placeholder)
# ---------------------------------------------------------------------------


def _run_live() -> int:
    """Start the omniclaude runtime service (live mode).

    Validates environment first, then starts the plugin lifecycle.
    """
    # Validate required env vars before attempting to start
    env_ok, env_msg = _check_env_vars()
    if not env_ok:
        print(f"ERROR: {env_msg}", file=sys.stderr)
        return 1

    print("Starting omniclaude runtime service...")
    print("Use SIGTERM to shut down gracefully.")
    # NOTE: Full service start (PluginClaude.initialize + start_consumers)
    # is wired in the kernel bootstrap layer. This entrypoint is the
    # Docker CMD target (python -m omniclaude.runtime start) and
    # delegates lifecycle to the kernel plugin loader.
    # Placeholder: in production this would invoke the kernel bootstrap.
    try:
        import asyncio

        from omniclaude.runtime.plugin import PluginClaude

        plugin = PluginClaude()
        print(f"Plugin status: {plugin.get_status_line()}")
        print(
            "Runtime service ready. (Live mode requires kernel bootstrap for full startup.)"
        )
        asyncio.run(_keepalive())
        return 0
    except KeyboardInterrupt:
        print("\nShutdown requested.")
        return 0
    except Exception as exc:
        print(f"ERROR: Failed to start runtime: {exc}", file=sys.stderr)
        return 1


async def _keepalive() -> None:
    """Run until interrupted."""
    import asyncio

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OmniClaude Runtime Service",
        prog="python -m omniclaude.runtime",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start", help="Start the omniclaude runtime service")
    start_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate environment and exit (exits 0 on success, 1 on failure)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entrypoint for python -m omniclaude.runtime."""
    args = _parse_args(argv)

    if args.command == "start":
        if args.dry_run:
            return _run_dry_run()
        return _run_live()

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
