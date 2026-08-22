# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify all Python hook handlers can import, and that alerting can deliver.

Run at session-start (``common.sh :: run_hook_health_probe``, called from
``session-start.sh``) to provide early warning of broken deployments (missing
dependencies, wrong Python interpreter, broken module paths) and — since
OMN-15600 — of a dead alert channel.

The alert-channel half is here rather than in a separate checker on purpose:
this is the hook-health check that actually runs on a schedule, and a liveness
check nobody invokes would have caught nothing.

Why this file lives under ``src/`` (OMN-15606)
----------------------------------------------
``session-start.sh`` invokes ``$PYTHON_CMD -m
omniclaude.hooks.lib.hook_health_probe``. ``$PYTHON_CMD`` resolves to the repo
venv, in which ``omniclaude`` is the installed distribution — and the wheel
packages ``src/omniclaude`` only. The implementation previously lived at
``plugins/onex/hooks/lib/hook_health_probe.py``, which that dotted name has
never resolved to, so the invocation failed with ``No module named ...``, the
``|| true`` swallowed it, and the parse fell back to a status every consumer
read as healthy. There is now exactly ONE implementation, and it sits on the
path that runs; ``plugins/onex/hooks/lib/hook_health_probe.py`` is a thin
delegate to this module for callers that exec that path directly.

Failure semantics
-----------------
This probe never crashes session start, and it never fails open. Anything it
cannot establish is reported as a NOT-healthy status and a nonzero exit, so
that "the check did not run" is never mistaken for "the check passed".
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

#: Handler modules whose importability is checked at session start.
#:
#: Every entry MUST be importable — ``tests/unit/hooks/test_probe_channel_fails_loud.py``
#: asserts it. A phantom entry here is worse than no check: it reports a
#: permanent failure that trains the operator to ignore the warning.
#:
#: ``omniclaude.hooks.handlers.dod_completion_guard`` was such a phantom, listed
#: here since the probe was written and never importable (the DoD guard lives at
#: ``plugins/onex/hooks/lib/done_flip_guard.py``, which is not under the
#: ``omniclaude.hooks.handlers`` namespace). It went unnoticed because the
#: ``-m omniclaude.hooks.lib.hook_health_probe`` invocation never resolved, so
#: this probe had never actually run. Removed under OMN-15606; restoring
#: coverage of the currently-registered guards needs those handlers to be
#: importable first, and is tracked separately rather than faked here.
# The trailing annotation marks a Python module path, not a Kafka topic: the
# validator's heuristic (scripts/validation/validate_topic_naming.py:51) matches
# any string starting "omniclaude.". Same false positive, same annotation, as
# src/omniclaude/lib/__init__.py:30 and hook_measurement/cli.py:96.
HOOK_HANDLERS = [
    "omniclaude.hooks.handlers.context_scope_auditor",  # arch-topic-naming: ignore
]

# Kept in lockstep with omniclaude.hooks.alert_channel.EnumChannelStatus.
# Duplicated as a literal ON PURPOSE: this probe must be able to name the
# probe-error status in exactly the case where ``alert_channel`` cannot be
# imported at all, so it cannot read the value off the enum at that moment.
# tests/unit/hooks/test_probe_channel_fails_loud.py asserts the two agree.
_PROBE_ERROR_STATUS = "probe_error"

#: Statuses that mean the alert channel was checked and can deliver. Anything
#: else — dead, probe_error, or a status this probe does not recognise — is a
#: hook-health failure.
HEALTHY_CHANNEL_STATUSES = frozenset({"live", "not_configured"})


def probe() -> list[dict[str, str]]:
    """Check each hook handler module can be imported."""
    results: list[dict[str, str]] = []
    for module_path in HOOK_HANDLERS:
        try:
            importlib.import_module(module_path)
            results.append({"module": module_path, "status": "ok"})
        except Exception as e:  # noqa: BLE001 — an unimportable handler IS the finding
            results.append({"module": module_path, "status": "error", "error": str(e)})
    return results


def probe_channel() -> dict[str, Any]:
    """Classify alert-channel liveness. Never raises, never fails open.

    A probe that could not run reports ``probe_error`` — a declared, NOT-healthy
    ``EnumChannelStatus`` member — so ``main()`` exits nonzero and the shell
    consumer logs. The pre-OMN-15606 shape returned an out-of-enum ``"unknown"``
    that both consumers read as "not a failure".
    """
    try:
        from omniclaude.hooks.alert_channel import probe_channel_health

        health = probe_channel_health()
        return {
            "status": health.status.value,
            "live_channels": health.live_channels,
            "dead_channels": health.dead_channels,
            "detail": health.detail,
        }
    except Exception as e:  # noqa: BLE001 — classified as a failure, not swallowed
        return {"status": _PROBE_ERROR_STATUS, "error": str(e)}


def channel_failed(channel: dict[str, Any]) -> bool:
    """True unless the channel was affirmatively established as deliverable.

    Fail-closed on an unrecognised status: a future producer emitting a value
    this probe has never heard of is an unverified channel, not a healthy one.
    """
    return str(channel.get("status", "")) not in HEALTHY_CHANNEL_STATUSES


def main() -> int:
    """Emit the hook-health payload and return the process exit code."""
    results = probe()
    failures = [r for r in results if r["status"] == "error"]
    channel = probe_channel()
    # A dead — or unverifiable — channel is a hook-health failure: the alerts
    # this probe exists to raise would be delivered into a channel that
    # discards them, or into a channel nobody checked.
    failed_channel = channel_failed(channel)
    print(
        json.dumps(
            {
                "hook_health": results,
                "alert_channel": channel,
                "failures": len(failures) + (1 if failed_channel else 0),
            }
        )
    )
    return 1 if (failures or failed_channel) else 0


__all__ = [
    "HEALTHY_CHANNEL_STATUSES",
    "HOOK_HANDLERS",
    "channel_failed",
    "main",
    "probe",
    "probe_channel",
]


if __name__ == "__main__":
    sys.exit(main())
