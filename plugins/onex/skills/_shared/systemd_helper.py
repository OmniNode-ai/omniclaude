# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dual-scope systemd unit probe [OMN-8853].

Probes BOTH system and user systemd scopes before reporting a unit missing.
Prior agents produced false negatives on deploy-agent.service by only checking
the system scope.
"""

from __future__ import annotations

import subprocess
from enum import StrEnum, auto
from typing import NamedTuple


class EnumSystemdUnitState(StrEnum):
    SYSTEM_ACTIVE = auto()
    USER_ACTIVE = auto()
    BOTH_ACTIVE = auto()
    SYSTEM_INACTIVE = auto()
    USER_INACTIVE = auto()
    MISSING = auto()


class _ScopeResult(NamedTuple):
    active: bool
    found: bool


def _probe_scope(unit_name: str, *, user: bool) -> _ScopeResult:
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd += ["show", unit_name, "--property=ActiveState"]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603

    # Exit code 4 means unit not found; exit code 1 can also mean not found.
    # We treat any non-zero exit OR output containing "not found"/"no unit" as absent.
    not_found_signals = ("could not find unit", "no unit", "not found")
    output_lower = (proc.stdout + proc.stderr).lower()

    if proc.returncode == 4 or any(s in output_lower for s in not_found_signals):
        return _ScopeResult(active=False, found=False)

    active = "ActiveState=active" in proc.stdout
    return _ScopeResult(active=active, found=True)


def check_systemd_unit(unit_name: str) -> EnumSystemdUnitState:
    """Probe both system and user scopes; return the combined state.

    Always probes both scopes — never short-circuits on the first hit.
    """
    system = _probe_scope(unit_name, user=False)
    user = _probe_scope(unit_name, user=True)

    if system.active and user.active:
        return EnumSystemdUnitState.BOTH_ACTIVE
    if system.active:
        return EnumSystemdUnitState.SYSTEM_ACTIVE
    if user.active:
        return EnumSystemdUnitState.USER_ACTIVE
    if system.found:
        return EnumSystemdUnitState.SYSTEM_INACTIVE
    if user.found:
        return EnumSystemdUnitState.USER_INACTIVE
    return EnumSystemdUnitState.MISSING
