# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Dispatcher stub for the /onex:demo delegation skill.

SCAFFOLDING ONLY. The real multi-model fan-out lives in follow-up PRs
against omnibase_infra and omnimarket. See:

    docs/plans/2026-04-10-demo-skill-plan.md

This module exists so the skill surface can be locked in (args schema,
import path, test harness) while the downstream handlers and nodes are
still being built.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

PLAN_PATH = "docs/plans/2026-04-10-demo-skill-plan.md"
SCAFFOLD_MARKER = "demo-skill-scaffolding"
SUPPORTED_SUBCOMMANDS = frozenset({"delegation"})


def dispatch(  # stub-ok: scaffolding entry point, replaced in follow-up
    subcommand: str,
    *,
    count: int = 3,
    prompts: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fail-fast entry point for the /onex:demo scaffolding surface.

    Validates the subcommand and attempts to import the downstream fan-out
    handler. When the handler is missing (expected in this PR), returns a
    structured failure envelope pointing at the plan document. When the
    handler is present (follow-up PRs), raises NotImplementedError so that
    this scaffold cannot accidentally ship as the final dispatcher.
    """
    if subcommand not in SUPPORTED_SUBCOMMANDS:
        return {
            "success": False,
            "error": (
                f"Unknown subcommand '{subcommand}'. "
                f"Supported: {sorted(SUPPORTED_SUBCOMMANDS)}."
            ),
            "scaffold_marker": SCAFFOLD_MARKER,
        }

    effective_dry_run = dry_run or os.environ.get("ONEX_DEMO_DRY_RUN") == "1"

    try:
        from omnimarket.nodes.node_demo_fanout_orchestrator.handlers import (  # type: ignore[import-not-found]  # noqa: F401
            HandlerDemoFanout,
        )
    except ImportError as exc:
        return {
            "success": False,
            "error": (
                "Demo fan-out handler is not yet implemented. This skill is "
                "scaffolding only — see the plan for the full implementation "
                "timeline."
            ),
            "missing_dependency": ("omnimarket.nodes.node_demo_fanout_orchestrator"),
            "import_error": repr(exc),
            "plan_path": PLAN_PATH,
            "scaffold_marker": SCAFFOLD_MARKER,
            "requested_count": count,
            "requested_prompts": prompts or [],
            "dry_run": effective_dry_run,
        }

    # Intentional fail-fast guard for the scaffolding PR. If the downstream
    # HandlerDemoFanout import above succeeds (follow-up PRs have landed)
    # this forces the dispatcher to be rewritten rather than silently
    # running a half-built path.
    raise NotImplementedError(  # stub-ok: scaffolding fail-fast guard
        "Full /onex:demo fan-out dispatch is not implemented in the "
        f"scaffolding PR. See {PLAN_PATH}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="/onex:demo")
    parser.add_argument("subcommand", nargs="?", default="delegation")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--prompts", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])

    prompts = (
        [item.strip() for item in ns.prompts.split(",") if item.strip()]
        if ns.prompts
        else None
    )
    result = dispatch(
        ns.subcommand,
        count=ns.count,
        prompts=prompts,
        dry_run=ns.dry_run,
    )
    print(result)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
