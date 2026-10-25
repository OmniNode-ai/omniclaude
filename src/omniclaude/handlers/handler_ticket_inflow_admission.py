# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Offline budget reading and trailing journal counting for lane admission."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from omniclaude.handlers.handler_lane_intake import LaneAdmission, LaneIntakePolicy
    from omniclaude.models.model_ticket_inflow_budget import ModelTicketInflowBudget


def budget_model() -> type[ModelTicketInflowBudget]:
    """Load the stdlib-only model under the hook's bare system interpreter."""
    path = Path(__file__).resolve().parents[1] / "models/model_ticket_inflow_budget.py"
    spec = importlib.util.spec_from_file_location("model_ticket_inflow_budget", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"budget model not loadable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("type[ModelTicketInflowBudget]", module.ModelTicketInflowBudget)


def read_budget(
    policy: LaneIntakePolicy, state: Path | None, now: datetime
) -> tuple[ModelTicketInflowBudget | None, str]:
    """AC4 admits on missing, unreadable or stale measurements, with a reason."""
    if state is None:
        return None, "budget unavailable: ONEX_STATE_DIR is unresolved"
    path = state / policy.budget_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        budget = budget_model().from_dict(raw)
        budget.validate_window(now, policy.window_days, policy.max_age_seconds)
    except FileNotFoundError:
        return None, f"budget missing: {path}; closure limit not evaluated"
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        return (
            None,
            f"budget unreadable or stale: {path}: {exc}; closure limit not evaluated",
        )
    return budget, ""


def window_count(
    ledger: Path | None, budget: ModelTicketInflowBudget | None, at: str
) -> int | None:
    """Conservatively join global measured admissions and the local journal.

    Snapshot-covered journal rows are not added twice. New local admissions are
    added even if the tracker later refused the write. A legacy untimed row is
    charged for its UTC day. Any unreadable journal refuses, as before.
    """
    if ledger is None:
        return None
    if budget is None:
        return 0
    start, end = (
        datetime.fromisoformat(budget.window[key].replace("Z", "+00:00")).astimezone(
            UTC
        )
        for key in ("start", "end")
    )
    covered = pending = 0
    try:
        paths = list(ledger.parent.iterdir())
    except FileNotFoundError:
        paths = []
    except OSError:
        return None
    try:
        for path in paths:
            if path.suffix != ".jsonl":
                continue
            if not start.strftime("%Y-%m-%d") <= path.stem <= at[:10]:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                value = row.get("at")
                if value is None:
                    # Unknown time on the snapshot day is charged as pending.
                    if path.stem >= end.strftime("%Y-%m-%d"):
                        pending += 1
                    else:
                        covered += 1
                    continue
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if instant >= end:
                    pending += 1
                elif instant >= start:
                    covered += 1
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return None
    return max(int(budget.lane_created_count), covered) + pending


def capacity_finding(
    admission: LaneAdmission, count: int | None
) -> dict[str, str] | None:
    """A bound plan child still spends one closure-funded admission."""
    if count is None:
        return {
            "code": "unevaluable",
            "field": "lane_intake",
            "reason": "the trailing intake journal could not be read (ONEX_STATE_DIR unset, relative or unreadable)",
            "fix": "set ONEX_STATE_DIR to an absolute, readable state directory and repair unreadable journals",
        }
    budget = admission.budget
    if budget is not None and count >= budget.closed_count + admission.policy.delta:
        return {
            "code": "lane_intake_budget",
            "field": "lane_intake",
            "reason": f"{count} lane admissions in window starting {budget.window['start']}; allowance is {budget.closed_count} governed closures + declared delta {admission.policy.delta}",
            "fix": "wait for measured closures to fund admission, or comment on an existing ticket; the allowance moves with closure, never a hand-raised daily budget",
        }
    return None
