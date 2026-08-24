#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane liveness authority [OMN-16478].

Resolves the ONE lane namespace and answers, from *positive evidence only*,
whether a lane is ALIVE, DEAD, or UNREACHABLE.

Why this exists
---------------
Friction report ``docs/tracking/2026-08-24-system-friction-report.md`` §F-10
(P0): a team lead told a worker "``supersede-binding-fix`` is dead (stale auth,
Not logged in), so no reply will come — take over OMN-16432 and land it."
``supersede-binding-fix`` was alive and mid-push. The duplicate takeover was
stopped only because the worker independently ran ``ps aux``. The same class
fired in both directions on 2026-08-17 (``occ-6118-close`` declared dead, then
corrected; ``occ-6118-close-2`` wrongly stood down for it).

Root cause: "dead" was asserted from NEGATIVE evidence — a failed
``SendMessage``, an absent ``ListAgents`` row, an ``idle`` status. None of those
distinguish *not reachable from this session* from *not running*. ``idle`` is
in fact the normal resting state of a healthy lane between turns.

The invariant this module enforces
----------------------------------
**Send failure, directory absence, and idle status are structurally incapable
of producing a DEAD verdict.** They are not inputs to :func:`probe` at all —
there is no parameter to pass them through. A DEAD verdict requires positive,
timestamped, filesystem-resident evidence that the lane stopped:

* ``ALIVE`` — a per-lane transcript whose mtime is inside the alive window, OR
  a ledger row for the lane inside it.
* ``DEAD`` — a transcript for the lane was FOUND and its mtime is older than
  the dead window, and no ledger row is newer than that window. OR: the lane's
  newest ledger row is an explicit ``TERMINAL`` row (a clean, self-declared
  completion).
* ``UNREACHABLE`` — everything else: unregistered lane, no transcript found, an
  evidence root that does not exist, an unreadable registry, or an mtime
  sitting in the band between the two thresholds. **Takeover is forbidden on
  this verdict.**

``UNREACHABLE`` is the fallback for every inconclusive path, so a gap in
evidence fails closed *against* a takeover rather than toward one. That is the
whole point: the F-10 incident is the case where evidence was missing and the
missing evidence was read as death.

Evidence sources (all local filesystem, no network, no message send)
--------------------------------------------------------------------
1. ``~/.claude/teams/<team>/config.json`` — the harness's own team registry.
   Each member carries ``name`` (the lane name, which is the address) and
   ``agentId`` (``<lane>@<team>``). This is what makes ONE namespace possible:
   a raw harness ref can be resolved back to the lane name it belongs to.
2. ``~/.claude/projects/<project>/<session>/subagents/agent-a<lane>-<hex>.jsonl``
   — the lane's own transcript. Its mtime is a per-lane heartbeat written by
   the lane's own activity, which no other lane can forge or suppress.
3. ``docs/tracking/ROLLING_WORK_LEDGER.md`` — ``CLAIM``/``TERMINAL`` rows keyed
   by lane name, the durable coordination record.

Sources 2 and 3 are independent: a lane that is mid-push (writing transcript
turns) but has not appended a ledger row in an hour is still ALIVE, which is
exactly the ``supersede-binding-fix`` shape.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------

ALIVE = "ALIVE"
DEAD = "DEAD"
UNREACHABLE = "UNREACHABLE"

#: Only this verdict permits taking over / superseding another lane's work.
TAKEOVER_PERMITTED = frozenset({DEAD})

#: A lane whose newest evidence is inside this window is ALIVE.
DEFAULT_ALIVE_WINDOW_S = 30 * 60

#: A lane may only be called DEAD once ALL evidence is older than this.
#: The gap between the two windows is deliberate and resolves to UNREACHABLE:
#: a quiet lane is not a dead lane, and the ambiguous band must not authorize
#: a takeover.
DEFAULT_DEAD_WINDOW_S = 120 * 60

#: A bare harness ref: hex-only, long enough not to collide with a real lane
#: name. Observed shapes: ``8a2709`` (teammate ref), ``aafd9716b95254b28``
#: (subagent id). Real lane names are hyphenated words (``supersede-binding-fix``,
#: ``occ-6118-close-2``) and never match this.
RAW_REF_RE = re.compile(r"^[0-9a-f]{6,}$")

#: Transcript filename shape: ``agent-a<lane-name>-<16 hex>.jsonl``. Unnamed
#: subagents use ``agent-a<17 hex>.jsonl`` and carry no lane name.
_TRANSCRIPT_RE = re.compile(r"^agent-a(?P<lane>.+)-(?P<suffix>[0-9a-f]{8,})\.jsonl$")

_LEDGER_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*\|")


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LaneRecord:
    """A lane as the harness team registry knows it."""

    name: str
    agent_id: str
    team: str


@dataclass
class Evidence:
    """Everything the probe actually observed, for the deny message."""

    registered: bool = False
    agent_id: str | None = None
    team: str | None = None
    transcript_path: str | None = None
    transcript_age_s: float | None = None
    ledger_age_s: float | None = None
    ledger_kind: str | None = None
    sources_unavailable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "registered": self.registered,
            "agent_id": self.agent_id,
            "team": self.team,
            "transcript_path": self.transcript_path,
            "transcript_age_s": (
                round(self.transcript_age_s)
                if self.transcript_age_s is not None
                else None
            ),
            "ledger_age_s": (
                round(self.ledger_age_s) if self.ledger_age_s is not None else None
            ),
            "ledger_kind": self.ledger_kind,
            "sources_unavailable": list(self.sources_unavailable),
        }


@dataclass
class Verdict:
    """The probe result. ``takeover_permitted`` is the only field a caller
    should branch on when deciding whether to supersede another lane."""

    lane: str
    state: str
    reason: str
    evidence: Evidence

    @property
    def takeover_permitted(self) -> bool:
        return self.state in TAKEOVER_PERMITTED

    def as_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "state": self.state,
            "takeover_permitted": self.takeover_permitted,
            "reason": self.reason,
            "evidence": self.evidence.as_dict(),
        }

    def human(self) -> str:
        ev = self.evidence
        bits: list[str] = []
        if ev.transcript_age_s is not None:
            bits.append(f"transcript heartbeat {_ago(ev.transcript_age_s)}")
        if ev.ledger_age_s is not None:
            kind = ev.ledger_kind or "row"
            bits.append(f"ledger {kind} {_ago(ev.ledger_age_s)}")
        if not ev.registered:
            bits.append("not in any team registry")
        if ev.sources_unavailable:
            bits.append("no evidence from: " + ", ".join(ev.sources_unavailable))
        detail = "; ".join(bits) if bits else "no evidence found"
        return f"{self.lane} is {self.state} ({detail})"


def _ago(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 90 * 60:
        return f"{int(seconds / 60)}m ago"
    return f"{seconds / 3600:.1f}h ago"


# --------------------------------------------------------------------------
# Roots
# --------------------------------------------------------------------------


def claude_home() -> Path:
    """Root of the harness state dir. ``CLAUDE_CONFIG_DIR`` wins if set."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def ledger_path() -> Path | None:
    """The rolling work ledger, resolved from ``OMNI_HOME``.

    Fail-soft (``None``) rather than raising: a missing ledger must degrade the
    verdict to UNREACHABLE, never crash the guard that calls this.
    """
    override = os.environ.get("ONEX_LEDGER_PATH")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    omni_home = os.environ.get("OMNI_HOME")
    if not omni_home:
        return None
    p = Path(omni_home) / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    return p if p.is_file() else None


# --------------------------------------------------------------------------
# Source 1 — the team registry (the ONE namespace)
# --------------------------------------------------------------------------


def load_registry(root: Path | None = None) -> dict[str, LaneRecord]:
    """Map lane name -> :class:`LaneRecord` across every team on disk.

    Newer teams win a name collision, so a lane name re-used across sessions
    resolves to its most recent incarnation.
    """
    base = (root or claude_home()) / "teams"
    if not base.is_dir():
        return {}
    records: dict[str, LaneRecord] = {}
    try:
        team_dirs = sorted(
            (d for d in base.iterdir() if d.is_dir()),
            key=lambda d: _safe_mtime(d) or 0.0,
        )
    except OSError:
        return {}
    for team_dir in team_dirs:
        config = team_dir / "config.json"
        try:
            data = json.loads(config.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for member in data.get("members", []) or []:
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            agent_id = member.get("agentId")
            if not isinstance(name, str) or not name:
                continue
            records[name] = LaneRecord(
                name=name,
                agent_id=agent_id
                if isinstance(agent_id, str)
                else f"{name}@{team_dir.name}",
                team=team_dir.name,
            )
    return records


def resolve_address(address: str, root: Path | None = None) -> tuple[str | None, str]:
    """Resolve any address form to the canonical lane name.

    Returns ``(lane_name_or_None, form)`` where ``form`` is one of
    ``lane_name`` / ``agent_id`` / ``raw_ref`` / ``unknown``.

    A raw harness ref is resolvable only when it is a prefix of a known
    ``agentId``'s session or an exact suffix match; when it cannot be resolved
    the caller still has enough to refuse it, which is the point — a raw ref is
    never a valid address regardless of whether we can map it back.
    """
    address = (address or "").strip()
    if not address:
        return None, "unknown"
    registry = load_registry(root)
    if address in registry:
        return address, "lane_name"
    if "@" in address:
        head = address.split("@", 1)[0]
        if head in registry:
            return head, "agent_id"
        return (head or None), "agent_id"
    if RAW_REF_RE.match(address):
        for name, rec in registry.items():
            if address in rec.agent_id:
                return name, "raw_ref"
        return None, "raw_ref"
    return None, "unknown"


# --------------------------------------------------------------------------
# Source 2 — per-lane transcript heartbeat
# --------------------------------------------------------------------------


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def find_transcript(lane: str, root: Path | None = None) -> tuple[Path | None, bool]:
    """Newest transcript for ``lane``.

    Returns ``(path_or_None, scanned)``. ``scanned`` is False when the projects
    root does not exist at all — the caller must treat that as "evidence source
    unavailable" (-> UNREACHABLE) and NOT as "no transcript, therefore dead".
    That distinction is the entire bug this module fixes.
    """
    projects = (root or claude_home()) / "projects"
    if not projects.is_dir():
        return None, False
    best: Path | None = None
    best_mtime = -1.0
    scanned = False
    try:
        subagent_dirs = list(projects.glob("*/*/subagents"))
    except OSError:
        return None, False
    for directory in subagent_dirs:
        if not directory.is_dir():
            continue
        scanned = True
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            match = _TRANSCRIPT_RE.match(entry.name)
            if not match or match.group("lane") != lane:
                continue
            mtime = _safe_mtime(entry)
            if mtime is not None and mtime > best_mtime:
                best, best_mtime = entry, mtime
    return best, scanned


# --------------------------------------------------------------------------
# Source 3 — ledger rows
# --------------------------------------------------------------------------


def last_ledger_row(
    lane: str, ledger: Path | None = None
) -> tuple[float | None, str | None]:
    """Age in seconds of the newest ledger row for ``lane``, and its kind.

    Rows look like::

        2026-08-24T12:22:00Z | wave2-defect-fix | OMN-16459 | CLAIM | ...

    Returns ``(None, None)`` when the ledger is unavailable or has no row for
    the lane. Callers must not read that as death.
    """
    path = ledger if ledger is not None else ledger_path()
    if path is None or not path.is_file():
        return None, None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None, None

    newest_ts: datetime | None = None
    newest_kind: str | None = None
    for line in text.splitlines():
        ts_match = _LEDGER_TS_RE.match(line)
        if not ts_match:
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) < 2 or fields[1] != lane:
            continue
        try:
            stamp = datetime.strptime(
                ts_match.group("ts"), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=UTC)
        except ValueError:
            continue
        if newest_ts is None or stamp > newest_ts:
            newest_ts = stamp
            newest_kind = fields[3] if len(fields) > 3 else None
    if newest_ts is None:
        return None, None
    age = (datetime.now(UTC) - newest_ts).total_seconds()
    return max(age, 0.0), newest_kind


# --------------------------------------------------------------------------
# The probe
# --------------------------------------------------------------------------


def probe(
    lane: str,
    *,
    root: Path | None = None,
    ledger: Path | None = None,
    alive_window_s: int = DEFAULT_ALIVE_WINDOW_S,
    dead_window_s: int = DEFAULT_DEAD_WINDOW_S,
) -> Verdict:
    """Decide ALIVE / DEAD / UNREACHABLE for ``lane``.

    Note the signature: there is deliberately **no parameter** for send
    success, ``ListAgents`` presence, or agent status. Those cannot reach this
    function, so they cannot produce a DEAD verdict — the F-10 invariant is
    enforced by the type of this call, not by a convention someone must
    remember.
    """
    evidence = Evidence()

    registry = load_registry(root)
    record = registry.get(lane)
    if record is not None:
        evidence.registered = True
        evidence.agent_id = record.agent_id
        evidence.team = record.team
    else:
        evidence.sources_unavailable.append("team registry (lane not registered)")

    transcript, scanned = find_transcript(lane, root)
    if transcript is not None:
        evidence.transcript_path = str(transcript)
        mtime = _safe_mtime(transcript)
        if mtime is not None:
            evidence.transcript_age_s = max(_now() - mtime, 0.0)
    elif not scanned:
        evidence.sources_unavailable.append(
            "transcript root (not present on this host)"
        )
    else:
        evidence.sources_unavailable.append("transcript (no file for this lane)")

    ledger_age, ledger_kind = last_ledger_row(lane, ledger)
    if ledger_age is not None:
        evidence.ledger_age_s = ledger_age
        evidence.ledger_kind = ledger_kind
    else:
        evidence.sources_unavailable.append("ledger (no row for this lane)")

    # --- ALIVE: any positive heartbeat inside the alive window wins outright.
    fresh = [
        age
        for age in (evidence.transcript_age_s, evidence.ledger_age_s)
        if age is not None and age <= alive_window_s
    ]
    if fresh:
        return Verdict(
            lane,
            ALIVE,
            f"positive heartbeat {_ago(min(fresh))}, inside the "
            f"{alive_window_s // 60}m alive window",
            evidence,
        )

    # --- DEAD path A: the lane declared its own clean completion.
    if ledger_kind == "TERMINAL" and ledger_age is not None:
        if evidence.transcript_age_s is None or evidence.transcript_age_s >= ledger_age:
            return Verdict(
                lane,
                DEAD,
                f"lane posted its own TERMINAL ledger row {_ago(ledger_age)} and has "
                "done nothing since",
                evidence,
            )

    # --- DEAD path B: the lane's own transcript stopped growing.
    #
    # Requires the transcript to have been FOUND. "No transcript" is not
    # evidence of death, it is evidence of nothing (F-10) — a found file whose
    # mtime we measured is a positive observation; a missing file is an absent
    # source. Only the transcript can condemn a lane. The ledger is a
    # corroborating source that can only ever *rescue* one: a row inside the
    # dead window means something happened, so the verdict falls back to
    # UNREACHABLE.
    if (
        evidence.transcript_age_s is not None
        and evidence.transcript_age_s > dead_window_s
    ):
        if evidence.ledger_age_s is None or evidence.ledger_age_s > dead_window_s:
            window = f"{dead_window_s // 60}m dead window"
            if evidence.ledger_age_s is None:
                corroboration = (
                    "the lane has no ledger row at all, so the transcript is its only "
                    "heartbeat"
                )
            else:
                corroboration = (
                    f"its newest ledger row is {_ago(evidence.ledger_age_s)}, also beyond "
                    "that window"
                )
            return Verdict(
                lane,
                DEAD,
                f"the lane's own transcript stopped growing {_ago(evidence.transcript_age_s)}, "
                f"beyond the {window}, and {corroboration}",
                evidence,
            )

    # --- UNREACHABLE: every other path.
    if evidence.transcript_age_s is None:
        why = (
            "no per-lane transcript was found, so there is no evidence the lane "
            "stopped — only an absence of evidence that it is running"
        )
    else:
        why = (
            f"newest heartbeat {_ago(evidence.transcript_age_s)} falls in the ambiguous "
            f"band between the {alive_window_s // 60}m alive window and the "
            f"{dead_window_s // 60}m dead window"
        )
    return Verdict(lane, UNREACHABLE, why, evidence)


def _now() -> float:
    import time

    return time.time()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

#: Exit codes chosen so a shell caller can branch without parsing JSON.
EXIT_ALIVE = 0
EXIT_UNREACHABLE = 3
EXIT_DEAD = 4

_EXIT_BY_STATE = {ALIVE: EXIT_ALIVE, UNREACHABLE: EXIT_UNREACHABLE, DEAD: EXIT_DEAD}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lane_liveness",
        description=(
            "Lane liveness authority (OMN-16478). Verdicts come from positive "
            "filesystem evidence only; a failed send or an absent ListAgents row "
            "is never an input."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="probe one lane's liveness")
    p_probe.add_argument("lane", help="lane name (the ledger/address name)")
    p_probe.add_argument(
        "--json", action="store_true", help="emit the full verdict as JSON"
    )
    p_probe.add_argument("--alive-window", type=int, default=DEFAULT_ALIVE_WINDOW_S)
    p_probe.add_argument("--dead-window", type=int, default=DEFAULT_DEAD_WINDOW_S)

    p_resolve = sub.add_parser(
        "resolve", help="resolve any address form to the lane name"
    )
    p_resolve.add_argument("address")

    args = parser.parse_args(argv)

    if args.command == "resolve":
        lane, form = resolve_address(args.address)
        print(json.dumps({"address": args.address, "lane": lane, "form": form}))
        return 0 if lane else 1

    verdict = probe(
        args.lane,
        alive_window_s=args.alive_window,
        dead_window_s=args.dead_window,
    )
    if args.json:
        print(json.dumps(verdict.as_dict(), indent=2))
    else:
        print(verdict.human())
        print(f"takeover_permitted: {str(verdict.takeover_permitted).lower()}")
    return _EXIT_BY_STATE[verdict.state]


if __name__ == "__main__":
    sys.exit(main())
