# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify all Python hook handlers can import, and that alerting can deliver.

Run at session-start (``session-start.sh``) to provide early warning of broken
deployments (missing dependencies, wrong Python interpreter, broken module
paths) and — since OMN-15600 — of a dead alert channel.

The alert-channel half is here rather than in a separate checker on purpose:
this is the hook-health check that actually runs on a schedule, and a liveness
check nobody invokes would have caught nothing. A configured-but-dead channel
counts as a failure, so the existing session-start WARNING fires.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

HOOK_HANDLERS = [
    "omniclaude.hooks.handlers.context_scope_auditor",
    "omniclaude.hooks.handlers.dod_completion_guard",
]


def probe() -> list[dict[str, str]]:
    """Check each hook handler module can be imported."""
    results: list[dict[str, str]] = []
    for module_path in HOOK_HANDLERS:
        try:
            importlib.import_module(module_path)
            results.append({"module": module_path, "status": "ok"})
        except Exception as e:
            results.append({"module": module_path, "status": "error", "error": str(e)})
    return results


def probe_channel() -> dict[str, Any]:
    """Probe alert-channel liveness (cached ~1h). Never raises."""
    try:
        from omniclaude.hooks.alert_channel import probe_alert_channel

        health = probe_alert_channel()
        return {
            "status": health.status,
            "live_channels": health.live_channels,
            "dead_channels": health.dead_channels,
            "detail": health.detail,
        }
    except Exception as e:  # noqa: BLE001 — probe must never break session start
        return {"status": "unknown", "error": str(e)}


if __name__ == "__main__":
    results = probe()
    failures = [r for r in results if r["status"] == "error"]
    channel = probe_channel()
    # A dead channel is a hook-health failure: the alerts this probe exists to
    # raise would be delivered into a channel that discards them.
    channel_failed = channel.get("status") == "dead"
    print(
        json.dumps(
            {
                "hook_health": results,
                "alert_channel": channel,
                "failures": len(failures) + (1 if channel_failed else 0),
            }
        )
    )
    sys.exit(1 if (failures or channel_failed) else 0)
