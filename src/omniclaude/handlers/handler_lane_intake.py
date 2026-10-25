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
  holds an open CLAIM on the rolling work ledger;
* rule 12 -- it carries the lane-intake label (``lane_intake.label``);
* rule 13 -- its description's first line is ``<stamp_prefix> <lane>``;
* rule 14 -- trailing admissions cannot exceed measured governed closures plus
  the declared delta. Per-day journal files retain the trailing window.

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

import fcntl
import importlib
import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

if TYPE_CHECKING:
    from omniclaude.models.model_ticket_inflow_budget import ModelTicketInflowBudget

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
#: The repository root, from ``src/omniclaude/handlers/<this file>``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
#: The stdlib-only readers this module reuses rather than re-implements: the
#: refusal recorder's sidecar and open-CLAIM reading (OMN-19381), which sits on
#: the hook library's ``hook_lane_attribution`` sidecar locator (OMN-18609).
_HOOKS_LIB = _REPO_ROOT / "plugins/onex/hooks/lib"
_REFUSAL_LANE_PY = (
    _REPO_ROOT
    / "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers"
    / "handler_hook_refusal_lane.py"
)


class LaneIntakePolicy(NamedTuple):
    """The ``lane_intake`` object of the ticket-creation policy."""

    label: str
    stamp_prefix: str
    state_subdir: str
    budget_path: str
    window_days: int
    max_age_seconds: int
    delta: int
    ratio_threshold: float


class LaneAdmission(NamedTuple):
    """One create made from a lane or node context, and the trailing intake so far.

    ``lane`` is the declared identity, ``""`` when the context carries none.
    ``intake_count`` is ``None`` when the trailing journal could not be read,
    which refuses: an unmeasurable budget is not a budget.
    """

    policy: LaneIntakePolicy
    lane: str
    intake_count: int | None
    ledger: Path | None
    at: str
    #: :data:`LANE_SOURCE_ENV`, :data:`LANE_SOURCE_SIDECAR_CLAIM` or ``""``.
    lane_source: str = ""
    #: The lane a subagent's sidecar named, kept when no open CLAIM confirmed
    #: it, so the refusal can say which CLAIM is missing.
    unclaimed_sidecar_lane: str = ""
    budget: ModelTicketInflowBudget | None = None
    budget_reason: str = ""
    bound: bool = False


def load_policy(policy_path: Path) -> LaneIntakePolicy:
    """Read ``lane_intake`` from the policy file, or raise ``ValueError``.

    Raised rather than defaulted: a policy that cannot be read is an unknown
    policy, and an unknown policy that admits everything is a gate reporting
    green while enforcing nothing.
    """
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))["lane_intake"]
        texts = [
            raw[k] for k in ("label", "stamp_prefix", "state_subdir", "budget_path")
        ]
        numbers = [raw[k] for k in ("window_days", "max_age_seconds", "delta")]
        threshold = raw["ratio_threshold"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"{policy_path}: no usable 'lane_intake' object ({exc})"
        ) from exc
    if not all(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError(f"{policy_path}: lane_intake strings must be non-blank")
    if any(type(n) is not int or n < 0 for n in numbers) or 0 in numbers[:2]:
        raise ValueError(
            f"{policy_path}: window/age must be positive integers; delta >= 0"
        )
    if type(threshold) not in (int, float) or not 0 < threshold < float("inf"):
        raise ValueError(f"{policy_path}: ratio_threshold must be finite and positive")
    label, prefix, subdir, budget_path = (t.strip() for t in texts)
    for name in (subdir, budget_path):
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError(
                f"{policy_path}: intake paths must stay within ONEX_STATE_DIR"
            )
    return LaneIntakePolicy(
        label,
        prefix,
        subdir,
        budget_path,
        numbers[0],
        numbers[1],
        numbers[2],
        float(threshold),
    )


class ProtocolTicketInflowAdmission(Protocol):
    """The stdlib-only admission reader loaded by the bare hook interpreter."""

    def read_budget(
        self, policy: LaneIntakePolicy, state: Path | None, now: datetime
    ) -> tuple[ModelTicketInflowBudget | None, str]: ...

    def window_count(
        self, ledger: Path | None, budget: ModelTicketInflowBudget | None, at: str
    ) -> int | None: ...

    def capacity_finding(
        self, admission: LaneAdmission, count: int | None
    ) -> dict[str, str] | None: ...


def _inflow() -> ProtocolTicketInflowAdmission:
    path = Path(__file__).with_name("handler_ticket_inflow_admission.py")
    spec = importlib.util.spec_from_file_location(
        "handler_ticket_inflow_admission", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"inflow handler not loadable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("ProtocolTicketInflowAdmission", module)


def ledger_path(
    environ: Mapping[str, str], policy: LaneIntakePolicy, today: str
) -> Path | None:
    """The per-UTC-day admission ledger, or ``None`` when no state dir resolves."""
    state_dir = environ.get("ONEX_STATE_DIR", "").strip()
    if not state_dir or not Path(state_dir).is_absolute():
        return None
    return Path(state_dir) / policy.state_subdir / f"{today}.jsonl"


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


def subagent_lane(
    payload: Mapping[str, object], environ: Mapping[str, str]
) -> tuple[str, str]:
    """``(lane, sidecar_lane)`` for a workflow subagent's create.

    A workflow subagent cannot set ``ONEX_LANE`` in the Claude Code process
    environment the hook reads, so its identity comes from two facts it did
    not assert in the call itself: the harness's ``agent-<agent id>.meta.json``
    sidecar, found from the payload's ``agent_id`` and transcript path, names
    the lane it was dispatched as; and the rolling work ledger holds an open
    CLAIM for exactly that lane. ``lane`` is that name when both agree and
    ``""`` otherwise; ``sidecar_lane`` is the sidecar's name whatever the
    ledger says, so a refusal can name the CLAIM that is missing. Never raises.
    """
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return "", ""
    reader = _refusal_lane_module()
    if reader is None:
        return "", ""
    try:
        attribution = importlib.import_module("hook_lane_attribution")
    except ImportError:
        return "", ""
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
        return "", ""
    # An unreadable ledger reads as no open CLAIM, which confirms nothing.
    claims = reader.open_claims(environ)
    if any(claim.get("lane") == named for claim in claims):
        return named, named
    return "", named


def begin(
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    policy_path: Path,
    now: datetime,
    *,
    force: bool = False,
    binding: Callable[[str], object] | None = None,
) -> LaneAdmission | None:
    """``None`` for a person's interactive session; an admission for a lane or node.

    A lane is an ``ONEX_LANE``/``ONEX_REMOTE_LANE`` declaration, a subagent call
    (``agent_id`` in the hook payload) or a headless ``sdk-*`` entrypoint -- the
    markers the lane GitHub-read guard uses. ``force`` is the node path: the
    caller IS a node, whatever its environment says.

    The declared environment names the lane first, unchanged for the
    remote-lane runner. A subagent with no declaration is named by
    :func:`subagent_lane` (sidecar plus open CLAIM) or by nothing.
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
    if not lane and is_subagent:
        lane, named = subagent_lane(payload, environ)
        source = LANE_SOURCE_SIDECAR_CLAIM if lane else ""
        unclaimed = "" if lane else named
    policy = load_policy(policy_path)
    ledger = ledger_path(environ, policy, now.strftime("%Y-%m-%d"))
    inflow = _inflow()
    budget, reason = inflow.read_budget(
        policy, Path(environ["ONEX_STATE_DIR"].strip()) if ledger else None, now
    )
    at = now.isoformat()
    tool_input = payload.get("tool_input")
    body = (
        str(tool_input.get("description", "")) if isinstance(tool_input, dict) else ""
    )
    return LaneAdmission(
        policy,
        lane,
        inflow.window_count(ledger, budget, at),
        ledger,
        at,
        source,
        unclaimed,
        budget,
        reason,
        bool(binding(body)) if binding else False,
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
    tool_input: Mapping[str, object], admission: LaneAdmission, *, bound: bool = False
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
                    "harness sidecar while its own CLAIM is open on the rolling "
                    "work ledger; a calling node passes its own name as the lane"
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
    capacity = _inflow().capacity_finding(admission, admission.intake_count)
    if capacity:
        out.append(capacity)
    budget = admission.budget
    if (
        budget is not None
        and budget.created_count > budget.closed_count * policy.ratio_threshold
        and not admission.bound
    ):
        out.append(
            {
                "code": "inflow_ratio",
                "field": "description",
                "reason": f"trailing created={budget.created_count}, closed={budget.closed_count} exceeds ratio threshold {policy.ratio_threshold}",
                "fix": "bind this create to a declared Gate, or wait for measured closure to restore the ratio",
            }
        )
    return out


def record(admission: LaneAdmission, title: str) -> None:
    """Serialize the final capacity check and append under a window-wide lock.

    Rechecking under the lock prevents concurrent hook processes from spending
    the same last admission. All UTC days share the same lock.
    """
    if admission.ledger is None:
        raise OSError("no intake ledger path resolves")
    admission.ledger.parent.mkdir(parents=True, exist_ok=True)
    with (admission.ledger.parent / ".admission.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        inflow = _inflow()
        count = inflow.window_count(admission.ledger, admission.budget, admission.at)
        failure = inflow.capacity_finding(admission, count)
        if failure:
            raise OSError(failure["reason"])
        line = json.dumps(
            {
                "at": admission.at,
                "lane": admission.lane,
                "lane_source": admission.lane_source,
                "title": title[:200],
                "budget_reason": admission.budget_reason,
            }
        )
        fd = os.open(admission.ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)


def complete(
    admission: LaneAdmission, tool_input: Mapping[str, object], no_record: bool
) -> int:
    """Record a successful admission and render its measurement exception, if any."""
    try:
        if not no_record:
            record(admission, str(tool_input.get("title", "")))
    except OSError as exc:
        sys.stderr.write(f"could not record the intake admission: {exc}\n")
        return 1
    if admission.budget_reason:
        sys.stdout.write(
            json.dumps({"decision": "allow", "reason": admission.budget_reason}) + "\n"
        )
    return 0


__all__ = [
    "LANE_SOURCE_ENV",
    "LANE_SOURCE_SIDECAR_CLAIM",
    "LaneAdmission",
    "LaneIntakePolicy",
    "begin",
    "complete",
    "findings",
    "ledger_path",
    "load_policy",
    "record",
    "stamp_line",
    "subagent_lane",
]
