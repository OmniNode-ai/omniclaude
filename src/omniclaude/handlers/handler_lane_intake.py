# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane-intake rules of the ticket-creation guard (OMN-17942, rules 11-14).

Every Linear item a lane or a node opens is written through the operator's one
existing Linear key, so its author field reads as the operator's own (scorecard
S3: 135 of 148 new items 2026-10-12..2026-10-16). The operator ruled the key
stays, so the item itself carries the fact:

* rule 11 -- a create from a lane or node context declares its lane identity:
  the launcher's ``ONEX_LANE``/``ONEX_REMOTE_LANE``, or, for a workflow
  subagent that cannot set its harness environment, the lane the harness's
  ``agent-<agent id>.meta.json`` sidecar names, accepted only while that lane
  holds an open CLAIM on the rolling work ledger; an in-session helper may
  instead use its parent session's registered lane and open CLAIM;
* rule 12 -- it carries the lane-intake label (``lane_intake.label``);
* rule 13 -- its description's first line is ``<stamp_prefix> <lane>``;
* rule 14 -- no more than ``lane_intake.daily_budget`` such items are admitted
  per UTC day, counted in a per-day ledger under ``ONEX_STATE_DIR``;
* rule 14a -- a create that cites a task of an approved plan is not lane-invented
  intake and does not spend that budget (RULING 2026-10-29T10:59:39Z). The
  citation is verified against the plan file at the plan repository's
  ``origin/main`` by ``handler_plan_task_citation``; one that cannot be
  confirmed is refused, naming what is missing, and a create that cites no
  plan spends the budget as before.

The vocabulary and the budget are ``ticket_creation_policy.json``'s
``lane_intake`` object (the plan exemption is its ``plan_task_exemption``
member); this module spells none of them.

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the rules without growing. The guard loads this module by
path and runs it under a bare interpreter with no ``omniclaude`` package, so it
imports the standard library only. The decisions are pure functions of what they
are handed; the filesystem is touched only by :func:`begin` and :func:`record`.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:  # the module is loaded by path at runtime, see _plan_module
    from omniclaude.handlers.handler_plan_task_citation import (
        PlanCitation,
        PlanTaskExemption,
    )

#: The launcher's declarations of a lane's identity, most specific first -- the
#: ``ONEX_LANE`` operand ``hook_lane_attribution`` resolves from; the
#: remote-lane runner sets the second on hosts that do not export the first.
_LANE_ENV_KEYS = ("ONEX_LANE", "ONEX_REMOTE_LANE")
#: ``CLAUDE_CODE_ENTRYPOINT`` prefix of a headless (``claude -p``) session.
_HEADLESS_ENTRYPOINT_PREFIX = "sdk-"
#: Where a lane's identity came from: the launcher's environment, or a
#: workflow subagent's harness sidecar confirmed by its open ledger CLAIM.
LANE_SOURCE_ENV = "env"
LANE_SOURCE_SIDECAR_CLAIM = "sidecar+claim"
LANE_SOURCE_PARENT_SESSION_CLAIM = "parent-session+claim"
#: The repository root, from ``src/omniclaude/handlers/<this file>``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
#: The stdlib-only readers this module reuses rather than re-implements: the
#: refusal recorder's sidecar and open-CLAIM reading (OMN-19381), which sits on
#: the hook library's ``hook_lane_attribution`` sidecar locator (OMN-18609).
_HOOKS_LIB = _REPO_ROOT / "plugins/onex/hooks/lib"
_PLAN_CITATION_PY = Path(__file__).with_name("handler_plan_task_citation.py")
_REFUSAL_LANE_PY = (
    _REPO_ROOT
    / "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers"
    / "handler_hook_refusal_lane.py"
)


class LaneIntakePolicy(NamedTuple):
    """The ``lane_intake`` object of the ticket-creation policy."""

    label: str
    stamp_prefix: str
    daily_budget: int
    state_subdir: str
    #: ``lane_intake.plan_task_exemption``, read by ``handler_plan_task_citation``.
    plan_task: PlanTaskExemption


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
    #: Environment, sidecar+claim, parent-session+claim, or unresolved (empty).
    lane_source: str = ""
    #: The lane a subagent's sidecar named, kept when no open CLAIM confirmed
    #: it, so the refusal can say which CLAIM is missing.
    unclaimed_sidecar_lane: str = ""
    helper: str = ""
    parent_session_id: str = ""
    #: The plan task this create cites, once confirmed at the plan's ref. A
    #: plan-backed create spends no budget and is recorded apart from the count.
    plan: PlanCitation | None = None
    #: What was missing when the create cites a plan task that is not confirmed.
    plan_error: str = ""


def _plan_module() -> ModuleType:
    """The plan-citation reader, loaded by path for the reason the guard loads this module so."""
    spec = importlib.util.spec_from_file_location(
        "handler_plan_task_citation", _PLAN_CITATION_PY
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"plan-citation handler not loadable: {_PLAN_CITATION_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        plan_task = _plan_module().load(raw["plan_task_exemption"], str(policy_path))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{policy_path}: no usable 'lane_intake' object ({exc})")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError(f"{policy_path}: lane_intake.daily_budget must be >= 1")
    if not all(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError(f"{policy_path}: lane_intake strings must be non-blank")
    label, prefix, subdir = (t.strip() for t in texts)
    return LaneIntakePolicy(label, prefix, budget, subdir, plan_task)


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


def _refusal_lane_module() -> ModuleType | None:
    """The refusal recorder's lane reader, loaded by path, or ``None``.

    Loaded by path for the reason the guard loads this module by path: the
    hook's bare interpreter has no ``omniclaude`` package. ``None`` when it
    cannot be loaded, which resolves no lane and so refuses.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "handler_hook_refusal_lane", _REFUSAL_LANE_PY
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.use_hooks_lib(str(_HOOKS_LIB))
    except (OSError, ImportError, SyntaxError, AttributeError):
        return None
    return module


def _parent_session_lane(session_id: str, environ: Mapping[str, str]) -> str:
    """Read the exact session binding written by session-start's registry.

    No newest-session or stamp fallback: neither proves who owns this helper.
    The two overrides and default match ``loops_check.liveness_state_dir``.
    """
    directory = (
        environ.get("OMNI_LANE_LIVENESS_STATE_DIR", "").strip()
        or environ.get("OMNI_SESSION_START_STATE_DIR", "").strip()
    )
    root = (
        Path(directory)
        if directory
        else Path.home() / ".local/state/omni/session-start"
    )
    try:
        registry = json.loads((root / "lane-liveness-sessions.json").read_text("utf-8"))
        entry = registry.get(session_id) if isinstance(registry, dict) else None
        lane = entry.get("lane") if isinstance(entry, dict) else None
    except (OSError, ValueError):
        return ""
    return lane.strip() if isinstance(lane, str) else ""


def subagent_lane(
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    *,
    allow_parent: bool = True,
) -> tuple[str, str, str, str]:
    """``(lane, sidecar_lane, source, parent_session_id)`` for a helper.

    A workflow subagent cannot set ``ONEX_LANE`` in the Claude Code process
    environment the hook reads, so its identity comes from two facts it did
    not assert in the call itself: the harness's ``agent-<agent id>.meta.json``
    sidecar, found from the payload's ``agent_id`` and transcript path, names
    the lane it was dispatched as; and the rolling work ledger holds an open
    CLAIM for exactly that lane. Otherwise an interactive session's helper
    may use the lane registered to its parent session, with that lane's open
    CLAIM. The hook's ``session_id`` names that parent harness session; the
    helper has its own ``agent_id``. The stamp never participates in identity
    resolution. Never raises.
    """
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return "", "", "", ""
    reader = _refusal_lane_module()
    if reader is None:
        return "", "", "", ""
    try:
        attribution = importlib.import_module("hook_lane_attribution")
    except ImportError:
        return "", "", "", ""
    session = payload.get("session_id")
    session_id = session.strip() if isinstance(session, str) else ""
    named = ""
    for key in ("transcript_path", "agent_transcript_path"):
        transcript = payload.get(key)
        if not isinstance(transcript, str) or not transcript.strip():
            continue
        # Both readers never raise: an unreadable sidecar names no lane.
        meta = attribution.read_sidecar(
            transcript, session_id or None, agent_id.strip()
        )
        named = reader.lane_cell(reader.sidecar_lane(meta))
        if named:
            break
    if not named:
        return "", "", "", ""
    # An unreadable ledger reads as no open CLAIM, which confirms nothing.
    claims = reader.open_claims(environ)
    if any(claim.get("lane") == named for claim in claims):
        return named, named, LANE_SOURCE_SIDECAR_CLAIM, ""
    if allow_parent and session_id:
        parent_lane = _parent_session_lane(session_id, environ)
        if parent_lane and any(claim.get("lane") == parent_lane for claim in claims):
            return parent_lane, named, LANE_SOURCE_PARENT_SESSION_CLAIM, session_id
    return "", named, "", ""


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

    The declared environment names the lane first, unchanged for the
    remote-lane runner. A subagent with no declaration is named by
    :func:`subagent_lane` (sidecar or registered parent plus open CLAIM).
    Headless and node contexts cannot borrow a parent session's authority.
    """
    lane = next(
        (environ[k].strip() for k in _LANE_ENV_KEYS if environ.get(k, "").strip()), ""
    )
    source = LANE_SOURCE_ENV if lane else ""
    agent_id = payload.get("agent_id")
    is_subagent = isinstance(agent_id, str) and bool(agent_id.strip())
    in_lane = (
        force
        or bool(lane)
        or is_subagent
        or environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith(
            _HEADLESS_ENTRYPOINT_PREFIX
        )
    )
    if not in_lane:
        return None
    unclaimed = ""
    helper = parent_session_id = ""
    if not lane and is_subagent:
        lane, named, source, parent_session_id = subagent_lane(
            payload,
            environ,
            allow_parent=not force
            and not environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith(
                _HEADLESS_ENTRYPOINT_PREFIX
            ),
        )
        helper = named
        unclaimed = "" if lane else named
    policy = load_policy(policy_path)
    tool_input = payload.get("tool_input")
    plan, plan_error = _plan_module().evaluate(
        tool_input.get("description") if isinstance(tool_input, dict) else None,
        policy.plan_task,
        environ,
    )
    ledger = ledger_path(environ, policy, now.strftime("%Y-%m-%d"))
    return LaneAdmission(
        policy,
        lane,
        read_intake_count(ledger),
        ledger,
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source,
        unclaimed,
        helper,
        parent_session_id,
        plan if not plan_error else None,
        plan_error,
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
        unclaimed = admission.unclaimed_sidecar_lane
        out.append(
            {
                "code": "lane_identity_missing",
                "field": "lane",
                "reason": (
                    "this create comes from a lane or node context but declares "
                    "no lane identity, so the item cannot be stamped as "
                    "lane-opened and would again read as the operator's own"
                    + (
                        f"; the harness names this subagent '{unclaimed}', but "
                        f"the rolling work ledger holds no open CLAIM for lane "
                        f"'{unclaimed}'"
                        if unclaimed
                        else ""
                    )
                ),
                "fix": (
                    f"append this lane's CLAIM (lane={unclaimed}) through "
                    "/omni:ledger-write before minting"
                    if unclaimed
                    else "run the lane with its identity declared "
                    "(ONEX_LANE=<lane>); a workflow subagent is named by its "
                    "harness sidecar while its own or its registered parent "
                    "session's CLAIM is open on the rolling work ledger; "
                    "a calling node passes its own name as the lane"
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
    if admission.plan_error:
        out.append(
            {
                "code": "plan_citation_unverified",
                "field": "description",
                "reason": (
                    "this create cites a plan task to be exempt from the daily "
                    f"budget, but {admission.plan_error}"
                ),
                "fix": (
                    "cite a task that is in a plan already at "
                    f"the plan repository {policy.plan_task.ref}, or drop "
                    "the citation line so the create spends the daily budget; "
                    "when the reason names the "
                    f"'{policy.plan_task.plan_repo_key}' key of the "
                    f"'{policy.plan_task.overlay}' overlay, supply that key in "
                    "the overlay rather than setting an environment variable"
                ),
            }
        )
    elif admission.plan is not None:
        # RULING 2026-10-29T10:59:39Z: a confirmed plan task spends no budget.
        pass
    elif admission.intake_count is None:
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
    target = admission.ledger
    if admission.plan is not None:
        # Audit only, and best effort: the day's count reads ``<day>.jsonl`` and
        # never this file, so a plan-backed create leaves the count unchanged.
        if target is None:
            return
        target = target.with_name(f"{target.stem}.plan{target.suffix}")
    if target is None:
        raise OSError("no intake ledger path resolves")
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": admission.at,
        "lane": admission.lane,
        "lane_source": admission.lane_source,
        "helper": admission.helper,
        "parent_session_id": admission.parent_session_id,
        "title": title[:200],
    }
    if admission.plan is not None:
        entry["plan_path"] = admission.plan.path
        entry["plan_task"] = admission.plan.task
    line = json.dumps(entry)
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


__all__ = [
    "LANE_SOURCE_ENV",
    "LANE_SOURCE_PARENT_SESSION_CLAIM",
    "LANE_SOURCE_SIDECAR_CLAIM",
    "LaneAdmission",
    "LaneIntakePolicy",
    "begin",
    "findings",
    "ledger_path",
    "load_policy",
    "read_intake_count",
    "record",
    "stamp_line",
    "subagent_lane",
]
