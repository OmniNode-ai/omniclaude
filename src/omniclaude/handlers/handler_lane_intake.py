# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane-intake rules of the ticket-creation guard (OMN-17942, rules 11-14).

Every Linear item a lane or a node opens is written through the operator's one
existing Linear key, so its author field reads as the operator's own (scorecard
S3: 135 of 148 new items 2026-10-12..2026-10-16). The operator ruled the key
stays, so the item itself carries the fact:

* rule 11 -- a create from a lane or node context declares its lane identity;
* rule 12 -- it carries the lane-intake label (``lane_intake.label``);
* rule 13 -- its description's first line is ``<stamp_prefix> <lane>``;
* rule 14 -- no more than ``lane_intake.daily_budget`` such items are admitted
  per UTC day, counted in a per-day ledger under ``ONEX_STATE_DIR``.

The vocabulary and the budget are ``ticket_creation_policy.json``'s
``lane_intake`` object; this module spells none of them.

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the rules without growing. The guard loads this module by
path and runs it under a bare interpreter with no ``omniclaude`` package, so it
imports the standard library only. The decisions are pure functions of what they
are handed; the filesystem is touched only by :func:`begin` and :func:`record`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

#: The launcher's declarations of a lane's identity, most specific first -- the
#: ``ONEX_LANE`` operand ``hook_lane_attribution`` resolves from; the
#: remote-lane runner sets the second on hosts that do not export the first.
_LANE_ENV_KEYS = ("ONEX_LANE", "ONEX_REMOTE_LANE")
#: ``CLAUDE_CODE_ENTRYPOINT`` prefix of a headless (``claude -p``) session.
_HEADLESS_ENTRYPOINT_PREFIX = "sdk-"


class LaneIntakePolicy(NamedTuple):
    """The ``lane_intake`` object of the ticket-creation policy."""

    label: str
    stamp_prefix: str
    daily_budget: int
    state_subdir: str


class LaneAdmission(NamedTuple):
    """One create made from a lane or node context, and today's intake so far.

    ``lane`` is the declared identity, ``""`` when the context carries none.
    ``intake_count`` is ``None`` when the per-day ledger could not be read,
    which refuses: an unmeasurable budget is not a budget.
    """

    policy: LaneIntakePolicy
    lane: str
    intake_count: int | None
    ledger: Path | None
    at: str


def load_policy(policy_path: Path) -> LaneIntakePolicy:
    """Read ``lane_intake`` from the policy file, or raise ``ValueError``.

    Raised rather than defaulted: a policy that cannot be read is an unknown
    policy, and an unknown policy that admits everything is a gate reporting
    green while enforcing nothing.
    """
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))["lane_intake"]
        budget = raw["daily_budget"]
        texts = [raw[k] for k in ("label", "stamp_prefix", "state_subdir")]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{policy_path}: no usable 'lane_intake' object ({exc})")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError(f"{policy_path}: lane_intake.daily_budget must be >= 1")
    if not all(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError(f"{policy_path}: lane_intake strings must be non-blank")
    label, prefix, subdir = (t.strip() for t in texts)
    return LaneIntakePolicy(label, prefix, budget, subdir)


def ledger_path(
    environ: Mapping[str, str], policy: LaneIntakePolicy, today: str
) -> Path | None:
    """The per-UTC-day admission ledger, or ``None`` when no state dir resolves."""
    state_dir = environ.get("ONEX_STATE_DIR", "").strip()
    if not state_dir or not Path(state_dir).is_absolute():
        return None
    return Path(state_dir) / policy.state_subdir / f"{today}.jsonl"


def read_intake_count(ledger: Path | None) -> int | None:
    """Items already admitted today. A missing file is zero; unreadable is ``None``."""
    if ledger is None:
        return None
    try:
        text = ledger.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    except OSError:
        return None
    return sum(1 for line in text.splitlines() if line.strip())


def begin(
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    policy_path: Path,
    now: datetime,
    *,
    force: bool = False,
) -> LaneAdmission | None:
    """``None`` for a person's interactive session; an admission for a lane or node.

    A lane is an ``ONEX_LANE``/``ONEX_REMOTE_LANE`` declaration, a subagent call
    (``agent_id`` in the hook payload) or a headless ``sdk-*`` entrypoint -- the
    markers the lane GitHub-read guard uses. ``force`` is the node path: the
    caller IS a node, whatever its environment says.
    """
    lane = next(
        (environ[k].strip() for k in _LANE_ENV_KEYS if environ.get(k, "").strip()), ""
    )
    agent_id = payload.get("agent_id")
    in_lane = (
        force
        or bool(lane)
        or (isinstance(agent_id, str) and bool(agent_id.strip()))
        or environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith(
            _HEADLESS_ENTRYPOINT_PREFIX
        )
    )
    if not in_lane:
        return None
    policy = load_policy(policy_path)
    ledger = ledger_path(environ, policy, now.strftime("%Y-%m-%d"))
    return LaneAdmission(
        policy,
        lane,
        read_intake_count(ledger),
        ledger,
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def stamp_line(policy: LaneIntakePolicy, lane: str) -> str:
    """The exact first line a lane-opened item carries."""
    return f"{policy.stamp_prefix} {lane}"


def _label_names(tool_input: Mapping[str, object]) -> set[str]:
    """The label names a create carries, lowercased. Ids cannot be read here."""
    raw = tool_input.get("labels", tool_input.get("label"))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {x.strip().lower() for x in raw if isinstance(x, str) and x.strip()}


def findings(
    tool_input: Mapping[str, object], admission: LaneAdmission
) -> list[dict[str, str]]:
    """Rules 11-14 for one create, as ``{code, field, reason, fix}`` dicts."""
    policy, lane = admission.policy, admission.lane
    out: list[dict[str, str]] = []
    if not lane:
        out.append(
            {
                "code": "lane_identity_missing",
                "field": "lane",
                "reason": (
                    "this create comes from a lane or node context but declares "
                    "no lane identity, so the item cannot be stamped as "
                    "lane-opened and would again read as the operator's own"
                ),
                "fix": (
                    "run the lane with its identity declared (ONEX_LANE=<lane>), "
                    "or have the calling node pass its own name as the lane"
                ),
            }
        )
    if policy.label.lower() not in _label_names(tool_input):
        out.append(
            {
                "code": "lane_label_missing",
                "field": "labels",
                "reason": (
                    f"a lane- or node-created item carries the '{policy.label}' "
                    "label so the weekly intake metric can exclude it"
                ),
                "fix": f"pass labels including '{policy.label}'",
            }
        )
    description = tool_input.get("description")
    first = (
        description.split("\n", 1)[0].strip() if isinstance(description, str) else ""
    )
    if lane and first != stamp_line(policy, lane):
        out.append(
            {
                "code": "lane_stamp_missing",
                "field": "description",
                "reason": (
                    "the first line of a lane- or node-created item names the "
                    f"lane that opened it; this one opens '{first[:80]}'"
                ),
                "fix": (
                    "make the description's first line exactly "
                    f"'{stamp_line(policy, lane)}'"
                ),
            }
        )
    if admission.intake_count is None:
        out.append(
            {
                "code": "unevaluable",
                "field": "lane_intake",
                "reason": (
                    "the per-day intake ledger could not be read (ONEX_STATE_DIR "
                    "unset, relative or unreadable), so the daily budget cannot "
                    "be measured"
                ),
                "fix": "set ONEX_STATE_DIR to an absolute, readable state directory",
            }
        )
    elif admission.intake_count >= policy.daily_budget:
        out.append(
            {
                "code": "lane_intake_budget",
                "field": "lane_intake",
                "reason": (
                    f"{admission.intake_count} lane- or node-created items were "
                    f"already admitted today (UTC); the daily budget is "
                    f"{policy.daily_budget}, set in ticket_creation_policy.json"
                ),
                "fix": (
                    "do not open this item today: comment on an existing ticket, "
                    "or leave it for tomorrow's budget. Raising the budget is the "
                    "operator's edit to lane_intake.daily_budget"
                ),
            }
        )
    return out


def record(admission: LaneAdmission, title: str) -> None:
    """Append one admission to today's ledger. ``O_APPEND`` keeps lines whole.

    The check-then-append pair is not atomic across processes, so lanes
    admitted in the same instant can overshoot the budget by the number of
    racers: a bounded overshoot of a rate limit, not a bypass.
    """
    if admission.ledger is None:
        raise OSError("no intake ledger path resolves")
    admission.ledger.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"at": admission.at, "lane": admission.lane, "title": title[:200]}
    )
    fd = os.open(admission.ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


__all__ = [
    "LaneAdmission",
    "LaneIntakePolicy",
    "begin",
    "findings",
    "ledger_path",
    "load_policy",
    "read_intake_count",
    "record",
    "stamp_line",
]
