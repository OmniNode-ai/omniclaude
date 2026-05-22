# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Python handler for session cost emission (OMN-8020).

Wraps normalize_session_cost_payload() and emits the resulting
llm.cost.completed payload via emit_client_wrapper → node_emit_daemon.

The shell path (session-end.sh → omniclaude.hooks.session_cost_emitter →
emit_via_daemon) already handles emission for live hook invocations. This
module provides a testable Python-layer interface that can be called directly
from Python code, integration tests, or future Python-native hook runners.

Event routing:
  llm.cost.completed → onex.evt.omniintelligence.llm-call-completed.v1
  (registered in event_registry.py and omniclaude.yaml)
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from omniclaude.hooks.session_cost_emitter import normalize_session_cost_payload

logger = logging.getLogger(__name__)

_EVENT_TYPE = "llm.cost.completed"


def emit_session_cost(
    *,
    session_end_payload: Mapping[str, object],
    env: dict[str, str] | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    accumulator_dir: Path = Path("/tmp"),  # noqa: S108  # nosec B108
    plugin_root: str | None = None,
) -> bool:
    """Build and emit an llm.cost.completed event via node_emit_daemon.

    Args:
        session_end_payload: Raw Claude Code SessionEnd JSON object.
        env: Environment variables dict. Defaults to os.environ.
        session_id: Session identifier. Extracted from payload when absent.
        correlation_id: Optional correlation UUID for distributed tracing.
        accumulator_dir: Directory containing omniclaude-session-*.json accumulators.
        plugin_root: Path to the omniclaude plugin root for emit_client_wrapper
            resolution. Falls back to CLAUDE_PLUGIN_ROOT env var.

    Returns:
        True if the event was accepted by the daemon, False otherwise.
        Failure is soft — callers must never raise based on this return value.
    """
    resolved_env = dict(env) if env is not None else dict(os.environ)

    payload = normalize_session_cost_payload(
        session_end_payload=session_end_payload,
        env=resolved_env,
        session_id=session_id,
        correlation_id=correlation_id,
        accumulator_dir=accumulator_dir,
    )
    if payload is None:
        logger.debug("session_cost_emit_skipped_no_tokens")
        return False

    return _emit_via_daemon(payload, plugin_root=plugin_root)


def _emit_via_daemon(
    payload: dict[str, object],
    *,
    plugin_root: str | None = None,
) -> bool:
    """Emit payload via emit_client_wrapper → node_emit_daemon socket."""
    resolved_root = plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    hooks_lib = os.path.join(resolved_root, "hooks", "lib") if resolved_root else ""
    if hooks_lib and hooks_lib not in sys.path:
        sys.path.insert(0, hooks_lib)

    try:
        from emit_client_wrapper import emit_event  # noqa: PLC0415

        success = emit_event(_EVENT_TYPE, payload)
        if success:
            logger.debug(
                "session_cost_emitted",
                extra={
                    "event_type": _EVENT_TYPE,
                    "session_id": payload.get("session_id"),
                    "total_tokens": payload.get("total_tokens"),
                },
            )
        else:
            logger.warning(
                "session_cost_daemon_rejected",
                extra={"event_type": _EVENT_TYPE},
            )
        return bool(success)
    except Exception as e:  # noqa: BLE001 — boundary: emit must degrade not crash
        logger.warning(
            "session_cost_emit_failed",
            extra={"event_type": _EVENT_TYPE, "error": f"{type(e).__name__}: {e!s}"},
        )
        return False
