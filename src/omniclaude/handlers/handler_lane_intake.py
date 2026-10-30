# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane-intake rules of the ticket-creation guard (OMN-17942, rules 11-13).

Every Linear item a lane or a node opens is written through the operator's one
existing Linear key, so its author field reads as the operator's own (scorecard
S3: 135 of 148 new items 2026-10-12..2026-10-16). The operator ruled the key
stays, so the item itself carries the fact:

* rule 11 -- a create from a lane or node context declares its lane identity:
  the launcher's ``ONEX_LANE``/``ONEX_REMOTE_LANE``, or, for a workflow
  subagent that cannot set its harness environment, the lane the harness's
  sidecar or the dispatch prompt in the agent's own transcript names, accepted
  only while that lane holds an open CLAIM on the rolling work ledger; an
  in-session helper may instead use its parent session's registered lane and
  open CLAIM (``handler_subagent_lane_resolve``);
* rule 12 -- it carries the lane-intake label (``lane_intake.label``);
* rule 13 -- its description's first line is ``<stamp_prefix> <lane>``.

No rule counts items: creating a ticket is never refused or deferred by how many were
created (RULING 2026-10-30T00:03:58Z, which replaced the 30-a-day budget of the former
rule 14 and its plan-task exemption with a work-in-progress limit on starting work).

The vocabulary is ``ticket_creation_policy.json``'s ``lane_intake`` object; this
module spells none of it.

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the rules without growing. The guard loads this module by
path and runs it under a bare interpreter with no ``omniclaude`` package, so it
imports the standard library only. The decisions are pure functions of what they
are handed; the filesystem is touched only by :func:`begin`.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

#: The launcher's declarations of a lane's identity, most specific first -- the
#: ``ONEX_LANE`` operand ``hook_lane_attribution`` resolves from; the
#: remote-lane runner sets the second on hosts that do not export the first.
_LANE_ENV_KEYS = ("ONEX_LANE", "ONEX_REMOTE_LANE")
#: ``CLAUDE_CODE_ENTRYPOINT`` prefix of a headless (``claude -p``) session.
_HEADLESS_ENTRYPOINT_PREFIX = "sdk-"
#: Where a lane's identity came from: the launcher's environment, or a
#: subagent's sidecar, dispatch prompt or parent session confirmed by an open
#: ledger CLAIM (``node_hook_refusal_record_effect``).
LANE_SOURCE_ENV = "env"
_SUBAGENT_LANE_PY = (
    Path(__file__).resolve().parents[1]
    / "nodes/node_hook_refusal_record_effect/handlers"
    / "handler_subagent_lane_resolve.py"
)


class LaneIntakePolicy(NamedTuple):
    """The ``lane_intake`` object of the ticket-creation policy."""

    label: str
    stamp_prefix: str


class LaneAdmission(NamedTuple):
    """One create made from a lane or node context.

    ``lane`` is the declared identity, ``""`` when the context carries none.
    """

    policy: LaneIntakePolicy
    lane: str
    #: The lane a subagent's sidecar named, kept when no open CLAIM confirmed
    #: it, so the refusal can say which CLAIM is missing.
    unclaimed_sidecar_lane: str = ""


def _load(name: str, path: Path) -> ModuleType:
    """A sibling handler, loaded by path for the reason the guard loads this module so."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{name} not loadable: {path}")
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
        texts = [raw[k] for k in ("label", "stamp_prefix")]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{policy_path}: no usable 'lane_intake' object ({exc})")
    if not all(isinstance(t, str) and t.strip() for t in texts):
        raise ValueError(f"{policy_path}: lane_intake strings must be non-blank")
    label, prefix = (t.strip() for t in texts)
    return LaneIntakePolicy(label, prefix)


def begin(
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    policy_path: Path,
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
    ``node_hook_refusal_record_effect`` (sidecar, dispatch prompt or registered parent
    plus open CLAIM).
    Headless and node contexts cannot borrow a parent session's authority.
    """
    lane = next(
        (environ[k].strip() for k in _LANE_ENV_KEYS if environ.get(k, "").strip()), ""
    )
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
        lane, named, _source, _parent = _load(
            "handler_subagent_lane_resolve", _SUBAGENT_LANE_PY
        ).subagent_lane(
            payload,
            environ,
            allow_parent=not force
            and not environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith(
                _HEADLESS_ENTRYPOINT_PREFIX
            ),
        )
        unclaimed = "" if lane else named
    return LaneAdmission(load_policy(policy_path), lane, unclaimed)


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
    """Rules 11-13 for one create, as ``{code, field, reason, fix}`` dicts."""
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
                        f"; this subagent is named '{unclaimed}' by its harness "
                        f"sidecar or dispatch prompt, but "
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
                    "harness sidecar or its dispatch prompt ('You are lane "
                    "<lane>') while its own or its registered parent "
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
    return out


__all__ = [
    "LANE_SOURCE_ENV",
    "LaneAdmission",
    "LaneIntakePolicy",
    "begin",
    "findings",
    "load_policy",
    "stamp_line",
]
