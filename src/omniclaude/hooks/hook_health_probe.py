# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Session-start hook health probe for OMN-6503.

Verifies that all registered hooks are reachable and responding.
Logs warnings for unhealthy hooks but never blocks session start.

Design principle: NEVER block. NEVER raise. Always return a result.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ModelHookHealthResult(BaseModel):
    """Result of a hook health probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_hooks: int = Field(default=0, ge=0)
    healthy_hooks: int = Field(default=0, ge=0)
    unhealthy_hooks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return len(self.unhealthy_hooks) == 0

    @property
    def degraded(self) -> bool:
        return len(self.unhealthy_hooks) > 0 and self.healthy_hooks > 0


def _find_hooks_json() -> Path | None:
    """Locate hooks.json from CLAUDE_PLUGIN_ROOT or relative path."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidate = Path(plugin_root) / "hooks" / "hooks.json"
        if candidate.exists():
            return candidate

    # Fallback: walk up from this file to find the plugin root
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "plugins" / "onex" / "hooks" / "hooks.json"
        if candidate.exists():
            return candidate
    return None


def _extract_hook_scripts(hooks_json_path: Path) -> list[str]:
    """Extract all hook script paths from hooks.json."""
    try:
        data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    scripts: list[str] = []
    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        str(hooks_json_path.parent.parent),
    )

    hooks_config = data.get("hooks", {})
    for _event_name, hook_groups in hooks_config.items():
        if not isinstance(hook_groups, list):
            continue
        for group in hook_groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    # Resolve ${CLAUDE_PLUGIN_ROOT} variable
                    resolved = cmd.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root)
                    scripts.append(resolved)
    return scripts


def _check_script_reachable(script_path: str) -> str | None:
    """Check if a hook script exists and is executable.

    Returns None if healthy, or an error message string if unhealthy.
    """
    path = Path(script_path)
    if not path.exists():
        return f"Hook script not found: {script_path}"
    if not os.access(path, os.X_OK):
        return f"Hook script not executable: {script_path}"
    return None


def probe_hook_health() -> ModelHookHealthResult:
    """Probe all registered hooks and return health status.

    This function NEVER raises. All errors are caught and converted
    to warnings in the result.
    """
    try:
        hooks_json = _find_hooks_json()
        if hooks_json is None:
            return ModelHookHealthResult(
                warnings=["[hook-health] hooks.json not found — cannot probe hooks"],
            )

        scripts = _extract_hook_scripts(hooks_json)
        if not scripts:
            return ModelHookHealthResult(
                warnings=["[hook-health] No hook scripts found in hooks.json"],
            )

        total = len(scripts)
        unhealthy: list[str] = []
        warnings: list[str] = []

        for script in scripts:
            error = _check_script_reachable(script)
            if error is not None:
                unhealthy.append(script)
                warnings.append(f"[hook-health] {error}")

        healthy = total - len(unhealthy)

        if unhealthy:
            warnings.insert(
                0,
                f"[hook-health] {len(unhealthy)}/{total} hooks unhealthy — "
                f"continuing in degraded mode",
            )

        return ModelHookHealthResult(
            total_hooks=total,
            healthy_hooks=healthy,
            unhealthy_hooks=unhealthy,
            warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001 — health probe must never crash
        return ModelHookHealthResult(
            warnings=[f"[hook-health] Probe failed: {exc}"],
        )


__all__ = [
    "ModelHookHealthResult",
    "probe_hook_health",
]
