# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session phase enforcement hook for UserPromptSubmit (OMN-11233, OMN-11282).

Reads .onex_state/session/phase_state.yaml and injects enforcement
directives when the phase budget is exhausted, a halt is required,
or a budget warning threshold has been crossed.

No network calls, no env vars, no LLM — pure YAML file read + string format.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = ".onex_state"
_PHASE_STATE_REL = "session/phase_state.yaml"
_DEFAULT_STATE_PATH = ".onex_state/session/phase_state.yaml"


class EnumPhaseEvaluation(StrEnum):
    """Known last_evaluation values from the reducer's phase state."""

    NO_ACTION = "no_action"
    TRANSITION_REQUIRED = "transition_required"
    HALT_REQUIRED = "halt_required"
    BUDGET_WARNING = "budget_warning"


class ModelPhaseState(BaseModel):
    """Typed projection of .onex_state/session/phase_state.yaml.

    Only the fields the hook needs; extra fields from the reducer are ignored.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    session_id: str = ""
    current_phase: str = "unknown"
    last_evaluation: str = EnumPhaseEvaluation.NO_ACTION
    budget_elapsed_pct: int = 0
    next_phase: str | None = None
    halt_reason: str | None = None


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


def read_phase_state(state_file: Path) -> ModelPhaseState | None:
    """Read and parse the phase state YAML into a typed model.

    Returns None if the file does not exist or cannot be parsed.
    Graceful no-op: non-session contexts have no state file.
    """
    if not state_file.exists():
        return None
    try:
        with state_file.open() as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            logger.warning("phase_state.yaml is not a mapping — ignoring")
            return None
        return ModelPhaseState.model_validate(data)
    except Exception as exc:  # noqa: BLE001 — boundary: hook must degrade not crash
        logger.warning("Failed to read phase_state.yaml: %s", exc)
        return None


def build_directive(state: ModelPhaseState) -> str | None:
    """Return a directive string for the given typed phase state, or None for no-op.

    Only reads state — zero logic about WHAT constitutes a transition.
    That logic lives exclusively in the evaluator/reducer nodes.
    """
    if state.last_evaluation == EnumPhaseEvaluation.TRANSITION_REQUIRED:
        next_phase = state.next_phase or "next"
        return (
            f"[PHASE ENFORCEMENT] Phase '{state.current_phase}' budget exhausted. "
            f"Transition to '{next_phase}' required. "
            "Stop current work and dispatch next phase workers."
        )

    if state.last_evaluation == EnumPhaseEvaluation.HALT_REQUIRED:
        reason = state.halt_reason or "unspecified"
        return (
            f"[SESSION HALT] Halt condition triggered: {reason}. "
            "Stop all work immediately."
        )

    if state.last_evaluation == EnumPhaseEvaluation.BUDGET_WARNING:
        return (
            f"[PHASE WARNING] Phase '{state.current_phase}' at {state.budget_elapsed_pct}% of time budget. "
            "Plan to transition soon."
        )

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
    raw = _load_phase_state(resolved)
    if not raw:
        return ""

    evaluation: str = raw.get("last_evaluation", "")
    current_phase: str = raw.get("current_phase", "unknown")
    next_phase: str = raw.get("next_phase", "unknown")
    budget_elapsed_pct: int | float = raw.get("budget_elapsed_pct", 0)

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


def evaluate_phase_state(state_path: str = _DEFAULT_STATE_PATH) -> str | None:
    """Read state file and return enforcement directive or None."""
    state = read_phase_state(Path(state_path))
    if state is None:
        return None
    return build_directive(state)


__all__ = [
    "EnumPhaseEvaluation",
    "ModelPhaseState",
    "build_directive",
    "build_enforcement_directive",
    "evaluate_phase_state",
    "read_phase_state",
]
