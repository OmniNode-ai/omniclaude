#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse ``SendMessage`` lane-liveness guard [OMN-16478].

The mechanical half of the F-10 fix (friction report
``docs/tracking/2026-08-24-system-friction-report.md`` §F-10, P0). The
:mod:`lane_liveness` module can tell the truth about a lane; this guard makes
asking it non-optional, at the one chokepoint every cross-lane instruction
passes through.

Two rules, both enforced on the outbound message:

**Rule A — one namespace.** ``to`` must be a lane name. A bare harness ref
(``8a2709``, ``aafd9716b95254b28``) is refused, with the lane name it resolves
to offered as the correction. This is the ``resume-coordinator`` failure ("a
stale raw agent ID the team lead gave me for your lane"), which cost two
self-corrections in a single pass.

**Rule B — liveness is a proof obligation.** A message that declares another
lane dead, or that authorizes taking over / superseding its work, is refused
unless :func:`lane_liveness.probe` independently returns ``DEAD``. The guard
runs the probe itself: there is no receipt to hand-carry, nothing to remember,
and no way to assert death without the assertion being checked.

``UNREACHABLE`` blocks exactly as hard as ``ALIVE`` does. That is the crux —
the incident was not someone lying, it was someone reading *"I cannot reach
it"* as *"it is not running."* A lane you cannot reach may be mid-push.

Failure posture: this guard **fails open** on any internal error, unreadable
input, or missing evidence root. It blocks on a corroborated wrong claim, never
on its own defect.

Exit codes: ``0`` allow, ``2`` block (JSON decision on stderr).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The shell wrapper runs this file with its own directory as sys.path[0], so the
# sibling module resolves by bare name. Under pytest / a direct `python3 path/to`
# invocation it does not, so make the sibling importable either way before the
# import rather than guessing which entrypoint is in play. (A static checker
# cannot follow a bare-name sibling like this; CI's mypy/pyright are scoped to
# `src/omniclaude` and never see this file, so leave the import as-is.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lane_liveness import (  # noqa: E402
    ALIVE,
    DEAD,
    RAW_REF_RE,
    UNREACHABLE,
    Verdict,
    load_registry,
    probe,
    resolve_address,
)

TOOL_NAME = "SendMessage"

#: Sentinel substituted for a lane-name occurrence before trigger matching, so
#: a lane whose own name contains a trigger word (``supersede-binding-fix``!)
#: cannot match itself.
_SENT = "\x00"

#: Everything between a trigger and its lane must stay inside one sentence —
#: ``.``/``!``/``?``/newline are excluded from every gap. Without this, "take
#: over OMN-16432 and land it. <lane> shipped" would read as a takeover of
#: <lane>.
_GAP = r"[^.!?\n]"

#: Death words, fenced so a hyphenated compound cannot supply one. Plain ``\b``
#: treats ``-`` as a boundary, so ``\bdead\b`` fires inside ``dead-letter`` and
#: "The dead-letter queue for <lane> drained" reads as a death assertion.
_DEATH_WORD = (
    r"(?<![\w-])(?:dead|gone|died|defunct|unresponsive|stalled|"
    r"not\s+responding|no\s+longer\s+running|not\s+running|not\s+alive|"
    r"never\s+coming\s+back)(?![\w-])"
)

#: Narrower set for the label form, same hyphen fence.
_DEATH_NOUN = r"(?<![\w-])(?:dead|died|defunct|gone)(?![\w-])"

#: "<lane> is dead" / "<lane> has been gone" / "<lane> appears stalled".
_DEATH_PREDICATE = re.compile(
    _SENT
    + _GAP
    + r"{0,40}?\b(?:is|was|'s|has\s+been|had\s+been|appears|appeared|seems|seemed|looks)\b"
    + _GAP
    + r"{0,25}?"
    + _DEATH_WORD,
    re.IGNORECASE,
)

#: "the dead lane <lane>" / "gone: <lane>".
_DEATH_LABEL = re.compile(
    _DEATH_NOUN + _GAP + r"{0,30}?" + _SENT,
    re.IGNORECASE,
)

#: "take over from <lane>" / "supersede <lane>" / "stand down for <lane>".
_TAKEOVER_VERB = re.compile(
    r"\b(?:take\s+over|taking\s+over|takeover|took\s+over|supersede|superseding|"
    r"supersedes|superseded|stand\s+down\s+for|standing\s+down\s+for)\b"
    + _GAP
    + r"{0,60}?"
    + _SENT,
    re.IGNORECASE,
)

#: "<lane> is superseded" / "<lane> has been superseded".
_TAKEOVER_PASSIVE = re.compile(
    _SENT
    + _GAP
    + r"{0,40}?\b(?:is|was|has\s+been|is\s+being)\b"
    + _GAP
    + r"{0,20}?\bsuperseded\b",
    re.IGNORECASE,
)

_TRIGGERS: list[tuple[str, re.Pattern[str]]] = [
    ("death assertion", _DEATH_PREDICATE),
    ("death assertion", _DEATH_LABEL),
    ("takeover authorization", _TAKEOVER_VERB),
    ("takeover authorization", _TAKEOVER_PASSIVE),
]

#: Guard against a pathological registry turning every send into an O(n·m)
#: scan. Lane names are short; this is generous.
_MAX_MESSAGE_CHARS = 200_000


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def _lane_mentions(
    message: str, lanes: list[str], recipient_lane: str | None
) -> list[str]:
    """Registered lane names that appear in ``message``, excluding the
    recipient (telling a lane about itself is not a takeover of it).

    Matched longest-first with each hit consumed, so ``occ-6118-close-2`` claims
    its own mention and a *separate* ``occ-6118-close`` mention in the same
    message is still seen. (That pair is a real incident: on 2026-08-17
    ``occ-6118-close-2`` claimed supersession of ``occ-6118-close``. Treating the
    shorter name as a mere substring of the longer one would have let exactly
    that message through.)
    """
    found: list[str] = []
    remaining = message
    for lane in sorted(set(lanes), key=len, reverse=True):
        if lane not in remaining:
            continue
        remaining = remaining.replace(lane, " ")
        if lane == recipient_lane:
            continue
        found.append(lane)
    return found


def find_triggers(message: str, lane: str) -> list[str]:
    """Trigger kinds fired for ``lane`` in ``message`` (empty = nothing to prove)."""
    masked = message.replace(lane, _SENT)
    kinds: list[str] = []
    for kind, pattern in _TRIGGERS:
        if pattern.search(masked) and kind not in kinds:
            kinds.append(kind)
    return kinds


def _rule_a(address: str) -> Decision | None:
    """Refuse a bare harness ref used as an address."""
    if not RAW_REF_RE.match(address.strip()):
        return None
    lane, _form = resolve_address(address)
    if lane:
        correction = f'It resolves to the lane name "{lane}" — address that instead.'
    else:
        correction = (
            "It does not resolve to any registered lane. Run ListAgents and use the "
            "lane name shown before the bracketed ref."
        )
    return Decision(
        False,
        f'"{address}" is a raw harness ref, not an address. Lanes have ONE namespace: '
        f"the ledger lane name. Raw refs go stale across sessions and were the source "
        f"of two mis-addressed dispatches in the 2026-08-24 friction window. {correction}",
    )


def _rule_b(
    message: str,
    recipient_lane: str | None,
    prober: Callable[[str], Verdict],
    registry_lanes: list[str],
) -> Decision | None:
    """Refuse an uncorroborated death claim or takeover authorization."""
    for lane in _lane_mentions(message, registry_lanes, recipient_lane):
        kinds = find_triggers(message, lane)
        if not kinds:
            continue
        verdict = prober(lane)
        if verdict.state == DEAD:
            continue
        return Decision(False, _deny_reason(lane, kinds, verdict))
    return None


def _deny_reason(lane: str, kinds: list[str], verdict: Verdict) -> str:
    head = " and ".join(sorted(set(kinds)))
    if verdict.state == ALIVE:
        headline = (
            f'This message carries a {head} for lane "{lane}", but {verdict.human()}.'
        )
        remedy = (
            "Do not take over its work. Message the lane directly and wait for its "
            "answer. If it is genuinely stuck, ask it to stand down and let it "
            "confirm — a lane mid-push that gets superseded loses the push."
        )
    elif verdict.state == UNREACHABLE:
        headline = (
            f'This message carries a {head} for lane "{lane}", and its liveness is '
            f"UNREACHABLE, not dead — {verdict.reason}."
        )
        remedy = (
            "UNREACHABLE is not DEAD. A send that fails, an agent missing from "
            "ListAgents, and an 'idle' status all mean 'not reachable from here'; "
            "none of them mean 'not running'. Takeover is forbidden on this verdict. "
            "Coordinate through the ledger (a CLAIM row the other lane will see) "
            "instead of reassigning its work."
        )
    else:  # pragma: no cover - DEAD never reaches here
        headline = f"unexpected verdict {verdict.state} for {lane}"
        remedy = ""
    evidence = json.dumps(verdict.evidence.as_dict(), sort_keys=True)
    return (
        f"{headline} {remedy} Evidence: {evidence}. Re-probe with: "
        f"python3 plugins/onex/hooks/lib/lane_liveness.py probe {lane} --json"
    )


def decide(
    call: dict[str, Any],
    *,
    prober: Callable[[str], Verdict] | None = None,
    registry_lanes: list[str] | None = None,
) -> Decision:
    """Allow or block one ``SendMessage`` PreToolUse call."""
    if call.get("tool_name") != TOOL_NAME:
        return Decision(True, "not_send_message")

    tool_input = call.get("tool_input")
    if not isinstance(tool_input, dict):
        return Decision(True, "unparsable_tool_input")

    address = tool_input.get("to")
    address = address if isinstance(address, str) else ""

    rule_a = _rule_a(address)
    if rule_a is not None:
        return rule_a

    message = tool_input.get("message")
    if not isinstance(message, str) or not message:
        return Decision(True, "no_message_body")
    if len(message) > _MAX_MESSAGE_CHARS:
        return Decision(True, "message_too_large_to_scan")

    lanes = (
        registry_lanes if registry_lanes is not None else list(load_registry().keys())
    )
    if not lanes:
        # No registry on this host — we cannot identify lane names in the body,
        # so there is nothing to corroborate. Fail open (never block on our own
        # missing evidence root).
        return Decision(True, "no_lane_registry")

    recipient_lane, _form = resolve_address(address)
    if recipient_lane is None and address in lanes:
        recipient_lane = address

    rule_b = _rule_b(message, recipient_lane, prober or probe, lanes)
    if rule_b is not None:
        return rule_b

    return Decision(True, "no_uncorroborated_liveness_claim")


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------


def _load_stdin_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    call = _load_stdin_call()
    try:
        decision = decide(call)
    except Exception:  # noqa: BLE001 - never block on a defect in this guard
        return 0
    if decision.allowed:
        return 0
    payload = {
        "decision": "block",
        "reason": f"[OMN-16478 lane-liveness guard] {decision.reason}",
    }
    sys.stderr.write(json.dumps(payload) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
