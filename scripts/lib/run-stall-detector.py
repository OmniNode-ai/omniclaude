# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Thin CLI driver for HandlerPrSnapshot stall detection.

Runs HandlerPrSnapshot against the configured repos, prints a JSON array of
ModelPrStallEvent dicts to stdout, and exits 0 (fail-open — partial scan
failures are logged but do not cause a non-zero exit).

Usage (from cron-merge-sweep.sh):
    uv run python scripts/lib/run-stall-detector.py

Environment:
    ONEX_REPOS  Comma-separated list of "org/repo" strings to scan.
                Defaults to DEFAULT_REPOS from ModelPrSnapshotInput.
    OMNI_HOME   Used by the handler's _snapshot_dir() to locate state storage.

Output:
    JSON array of stall events, one per line:
    [{"pr_number": 42, "repo": "OmniNode-ai/omniclaude", ...}, ...]

    Empty array ("[]") when no stalls detected.
    Nothing is written to stdout on import error — exit 1 instead.

[OMN-9406]
"""

from __future__ import annotations

import json
import logging
import os
import sys

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)


def _resolve_repos() -> tuple[str, ...]:
    raw = os.environ.get("ONEX_REPOS", "")
    if raw.strip():
        return tuple(r.strip() for r in raw.split(",") if r.strip())
    try:
        from omnimarket.nodes.node_pr_snapshot_effect.models.model_pr_snapshot_input import (
            DEFAULT_REPOS,
        )

        return DEFAULT_REPOS
    except ImportError:
        logger.error("omnimarket not importable and ONEX_REPOS not set — cannot run")
        sys.exit(1)


def main() -> None:
    try:
        from omnimarket.nodes.node_pr_snapshot_effect import HandlerPrSnapshot
        from omnimarket.nodes.node_pr_snapshot_effect.models.model_pr_snapshot_input import (
            ModelPrSnapshotInput,
        )
    except ImportError as exc:
        logger.error("Cannot import omnimarket: %s", exc)
        logger.error(
            "Install omnimarket: uv pip install -e $OMNI_HOME/omnimarket (or ensure it is in the venv)"
        )
        sys.exit(1)

    repos = _resolve_repos()
    input_model = ModelPrSnapshotInput(repos=repos)

    try:
        handler = HandlerPrSnapshot()
        result = handler.handle(input_model)
    except Exception as exc:
        logger.error("HandlerPrSnapshot failed: %s", exc)
        # Fail-open: print empty array so callers see zero stalls rather than
        # crashing the cron tick.
        print("[]")
        return

    stall_dicts = [
        {
            "pr_number": ev.pr_number,
            "repo": ev.repo,
            "stall_count": ev.stall_count,
            "blocking_reason": ev.blocking_reason,
            "head_sha": ev.head_sha,
            "first_seen_at": ev.first_seen_at.isoformat(),
            "last_seen_at": ev.last_seen_at.isoformat(),
        }
        for ev in result.stall_events
    ]

    print(json.dumps(stall_dicts))


if __name__ == "__main__":
    main()
