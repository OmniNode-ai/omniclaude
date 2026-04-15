#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""check_system_health execute — fast system snapshot [OMN-8853].

Checks Docker services and critical systemd units (system + user scopes).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Allow importing _shared helpers when run as a script.
_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, os.path.join(_SKILLS_DIR, "_shared"))

from systemd_helper import EnumSystemdUnitState, check_systemd_unit  # noqa: E402

# Critical systemd units to probe on the .201 host.
_SYSTEMD_UNITS: list[str] = [
    "deploy-agent.service",
    "omnidash.service",
]


def _check_systemd_units() -> dict[str, Any]:
    results: dict[str, str] = {}
    issues: list[str] = []

    for unit in _SYSTEMD_UNITS:
        state = check_systemd_unit(unit)
        results[unit] = str(state)
        if state == EnumSystemdUnitState.MISSING:
            issues.append(f"{unit}: MISSING from both system and user scopes")
        elif state in (
            EnumSystemdUnitState.SYSTEM_INACTIVE,
            EnumSystemdUnitState.USER_INACTIVE,
        ):
            issues.append(f"{unit}: present but inactive ({state})")

    return {"units": results, "issues": issues, "success": len(issues) == 0}


def _check_docker_services() -> dict[str, Any]:
    try:
        import subprocess

        result = subprocess.run(  # noqa: S603
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip(), "running": 0}

        lines = [line for line in result.stdout.strip().splitlines() if line]
        running = sum(1 for line in lines if "Up" in line)
        return {"success": True, "running": running, "total": len(lines)}
    except Exception as exc:
        return {"success": False, "error": str(exc), "running": 0}


def main() -> int:
    docker = _check_docker_services()
    systemd = _check_systemd_units()

    issues: list[str] = list(systemd["issues"])
    if not docker.get("success"):
        issues.append(f"Docker: {docker.get('error', 'unavailable')}")

    overall = (
        "healthy" if not issues else ("degraded" if len(issues) < 3 else "critical")
    )

    report = {
        "status": overall,
        "timestamp": datetime.now(UTC).isoformat(),
        "docker": docker,
        "systemd": systemd,
        "issues": issues,
    }

    print(json.dumps(report, indent=2))
    return 0 if overall == "healthy" else (1 if overall == "degraded" else 2)


if __name__ == "__main__":
    sys.exit(main())
