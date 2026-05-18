# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session phase enforcement hook for UserPromptSubmit (OMN-11233).

Reads .onex_state/session/phase_state.yaml and injects enforcement
directives when the phase budget is exhausted, a halt is required,
or a budget warning threshold has been crossed.

No network calls, no env vars, no LLM — pure YAML file read + string format.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = ".onex_state"
_PHASE_STATE_REL = "session/phase_state.yaml"


def _load_phase_state(state_dir: Path) -> dict | None:
    path = state_dir / _PHASE_STATE_REL
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Failed to read phase_state.yaml: %s", exc)
        return None


def build_enforcement_directive(state_dir: Path | None = None) -> str:
    """Return an enforcement directive string for the current phase state.

    Returns an empty string when no action is needed (in-budget, no state file,
    or unrecognised evaluation value). Returns a non-empty directive string for
    ``transition_required``, ``halt_required``, and ``budget_warning``.

    Args:
        state_dir: Override state directory. Defaults to ``.onex_state`` in cwd.
    """
    resolved = state_dir if state_dir is not None else Path(_DEFAULT_STATE_DIR)
    state = _load_phase_state(resolved)
    if not state:
        return ""

    evaluation: str = state.get("last_evaluation", "")
    current_phase: str = state.get("current_phase", "unknown")
    next_phase: str = state.get("next_phase", "unknown")
    budget_elapsed_pct: int | float = state.get("budget_elapsed_pct", 0)

    if evaluation == "transition_required":
        return (
            f"[PHASE ENFORCEMENT] Phase '{current_phase}' budget exhausted. "
            f"Transition to '{next_phase}' required. "
            "Stop current work and dispatch next phase workers."
        )
    if evaluation == "halt_required":
        return "[SESSION HALT] Halt condition triggered. Stop all work immediately."
    if evaluation == "budget_warning":
        return (
            f"[PHASE WARNING] Phase '{current_phase}' at {budget_elapsed_pct}% "
            "of time budget. Plan to transition soon."
        )
    return ""


__all__ = ["build_enforcement_directive"]
