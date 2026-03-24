# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Thin wrapper for env var health check, called from session-start.sh.

Outputs JSON to stdout for session-start.sh to capture.
Outputs warnings to stderr for hooks.log.
Never blocks SessionStart -- all errors are caught.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        from omniclaude.hooks.env_health_check import check_critical_env_vars

        result = check_critical_env_vars()
        # Print warnings to stderr for hooks.log
        for w in result.warnings:
            print(w, file=sys.stderr)
        # Print JSON to stdout for session-start.sh to capture
        if not result.healthy:
            warning_text = "\n".join(
                [
                    "--- Env Var Health Check ---",
                    *result.warnings,
                    "Set missing vars in ~/.omnibase/.env and restart.",
                    "---",
                ]
            )
            json.dump({"warning": warning_text}, sys.stdout)
        else:
            json.dump({"warning": ""}, sys.stdout)
    except Exception:
        json.dump({"warning": ""}, sys.stdout)


if __name__ == "__main__":
    main()
