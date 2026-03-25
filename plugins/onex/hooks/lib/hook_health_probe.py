# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify all Python hook handlers can import without error.

Run at session-start to provide early warning of broken deployments
(missing dependencies, wrong Python interpreter, broken module paths).
This is an importability check, not a substitute for execution tests.
"""

from __future__ import annotations

import importlib
import json
import sys

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


if __name__ == "__main__":
    results = probe()
    failures = [r for r in results if r["status"] == "error"]
    print(json.dumps({"hook_health": results, "failures": len(failures)}))
    sys.exit(1 if failures else 0)
