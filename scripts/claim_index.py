#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The claim index over the ledger (OMN-18261, phase 5 item 4 of the 2026-09-12
process-friction remediation plan).

THE STORE IS THE LEDGER. Append-only, already serialised by the append tool,
already the surface every lane reads and writes, and already carrying the lane
identifier. Nothing here ever deletes or rewrites a claim.

That choice is the design's strongest argument and it is worth restating where
the code lives: OMN-17005 measured an ephemeral claim file whose expiry was a
silent unlink, so a claim released cleanly and a claim that expired under a
still-running holder were indistinguishable afterwards. An append-only store
cannot do that. The durable terminal record that ticket asks for is structural
here rather than a feature somebody had to remember to add.

THE INDEX IS A CACHE AND IS NEVER AUTHORITATIVE. A hook cannot read seven
thousand growing lines on every push, so this derives a ticket-to-holder map.
Three properties keep a cache from becoming a second, disagreeing store:

  1. Derived, never edited. Rebuilt by replaying the ledger. A disagreement is
     always resolved in the ledger's favour.
  2. Self-describing staleness. It records the line count AND a digest of the
     ledger prefix it was built from, so a reader validates before deciding.
     Line count alone would miss a rewritten row.
  3. Fail-closed with a named remedy. An index that cannot be read reads as
     ABSENT, so the caller rebuilds -- never as an empty index, which would
     report every ticket unclaimed and pass exactly the case the gate exists to
     catch.

THE STORE IS THE LEDGER AND THE ROLLS IT SPILLED INTO (OMN-18791). The ledger
is rolled daily by a post-merge hook, which MOVES rows out of the live file into
`<ledger dir>/archive/`. A resolution reading only the live file therefore lost
every claim the last roll carried away, and a lost claim reads as an UNCLAIMED
ticket -- clean, silent, and exactly the case the gate exists to catch. The
resolution now replays the live ledger plus every archive that can still hold a
live claim, bounded by the roll date so it never opens the archives it does not
need, and every holder remembers which file its row is in.

DESIGN OF RECORD: `beta/plans/2026-09-13-lane-identity-and-claim-index-design.md`
in the private planning corpus (OMN-18259), sections 4, 5 and 6.

VENDORED INTO OMNICLAUDE from the private workspace repository at commit
ed077acbc4 (OMN-19256) by OMN-19722. This copy is the one branch_claim.py,
the pre-push hook, lane_identity.py, and both branch-claim workflows run, so a
change to the resolution lands here with its tests, in one PR. It was previously
fetched unpinned from the other repository's default branch, which is how a
wording change there turned this gate red with no omniclaude change.

HONEST LIMIT. This resolves who holds a ticket according to rows lanes wrote
about themselves. It enforces attribution and blast radius, not authority: no
row proves which lane SHOULD hold a ticket. What it removes is the silent case,
two lanes on one branch and neither knowing.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import re
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

__all__ = [
    "ARCHIVE_DIR_NAME",
    "INDEX_VERSION",
    "ClaimCollision",
    "ClaimStoreIncomplete",
    "Source",
    "append_transition",
    "archive_dir_for",
    "transition_lock",
    "STALENESS_HOURS",
    "Holder",
    "build_index",
    "build_index_from_sources",
    "holder",
    "index_is_stale",
    "load_index",
    "refusal_for_claim",
    "refusal_for_push",
    "resolve_index",
    "save_index",
    "sources_are_stale",
    "ticket_from_branch",
    "window_sources",
]

INDEX_VERSION = 1

# HOW LONG A CLAIM STAYS LIVE WITHOUT ACTIVITY, and where the number comes from.
#
# The design (OMN-18259 section 6) deliberately left this unset and said it would
# be chosen from a measurement of real inter-row gaps rather than from an
# armchair. Measured on the live ledger, 2026-09-13: 6,737 gaps between
# consecutive rows written by the SAME lane on the SAME ticket, across 3,497
# distinct lane-and-ticket pairs carrying more than one row.
#
#     p50   0.35h     p75   1.34h     p90   3.55h
#     p95   7.46h     p99  36.01h     max 214.03h
#
# Twelve hours sits above p95, so a lane that is genuinely working is not
# reclaimed out from under itself, and it catches a session that died overnight
# within the next working day. It would have marked 3.47% of measured gaps
# stale, and that tail is dominated by RECURRING lanes -- the morning triage,
# worktree prune and orchestrator lanes revisiting a ticket days later. Those are
# separate visits, not one continuous piece of work, and a fresh claim is the
# correct outcome for them anyway.
#
# Changing this number means re-running that measurement, not re-arguing taste.
STALENESS_HOURS = 12

_STAMP_RE = re.compile(r"^\s*-?\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)")
_LANE_RE = re.compile(r"^\s*lane\s*=\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")
_SUBJECT_FIELD_RE = re.compile(r"^\s*tickets?\s*=", re.IGNORECASE)
_TICKET_RE = re.compile(r"\bOMN-\d+\b")
_TO_RE = re.compile(r"^\s*to\s*=\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")
_STALE_CITATION_RE = re.compile(r"^\s*stale\s*=\s*(\S+):(\d+)\s*$")
_BRANCH_TICKET_RE = re.compile(r"(?i)\bomn-(\d+)\b")

# Rows that MOVE the claim. Every other classed row by the holder is activity,
# which renews -- see the renewal note below.
_TRANSITIONS = frozenset({"CLAIM", "RELEASE", "HANDOVER", "RENEW", "RECLAIM"})


# WHERE THE ROLLED ROWS GO, and why the resolution has to follow them.
#
# The ledger ROLLS. `docs/workflows/_ledger_roll/ledger_roll.sh` drives
# `ledger_lock.py --roll-section`, which MOVES rows out of the live file into
# `<ledger dir>/archive/<stem>_<date>-split.md` once the append-only section
# crosses its caps. It happens daily, unattended, from a post-merge hook.
#
# A resolution that read only the live file therefore lost every claim the last
# roll carried away -- and a lost claim reads as an UNCLAIMED ticket, which is
# clean. The gate passed exactly the case it exists to catch, once a day, with
# nothing in any output saying so (OMN-18791).
#
# THE BOUND IS PART OF THE FIX. Reading every archive means tens of megabytes on
# every push, and a hook that costs that much gets removed rather than obeyed.
# Rolled rows are all OLDER than the roll that moved them, so an archive whose
# roll date is before the staleness cutoff cannot hold an in-window row and is
# never opened. That is a property of how the roll works, not an estimate.
ARCHIVE_DIR_NAME = "archive"

# The name the roll gives an archive: `<live ledger stem>_<YYYY-MM-DD>-split.md`
# (`ledger_lock.plan_roll`). The date is the roll's own date, which is the
# newest a row inside it can be.
_ARCHIVE_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})-split\.md$")

# The roll writes one pointer block into the live ledger naming the archive it
# just wrote. Only the MOST RECENT survives -- each roll strips the previous one
# -- so it is not the discovery mechanism. It is the fail-closed CHECK: if the
# live file says rows went somewhere inside the window and that file cannot be
# read, the store is incomplete and the resolution refuses instead of answering
# "unclaimed" for everything the roll moved.
_ROLL_POINTER_RE = re.compile(r"<!-- ledger-roll:\s*(\{.*?\})\s*-->")


class ClaimStoreIncomplete(RuntimeError):
    """A source the store itself says exists could not be read.

    Raised rather than degraded, for the reason every other fail-closed path in
    this family is: an unreadable archive yields no holders, and no holders
    reads exactly like a clean bill of health over the whole corpus. The case
    this catches in practice is a sparse checkout whose pattern misses the
    archive directory -- the continuous-integration check would otherwise pass
    every rolled claim silently.
    """


@dataclass(frozen=True)
class Source:
    """One file replayed into the index, and the name it is cited by.

    `name` is how a refusal spells the file, so it must be the portable,
    repo-relative form the caller already uses for the live ledger rather than
    an absolute path on one machine.
    """

    name: str
    text: str


def archive_dir_for(ledger: Path) -> Path:
    return ledger.parent / ARCHIVE_DIR_NAME


def _archive_name(ledger_name: str, filename: str) -> str:
    """The citable name of an archive, derived from the live ledger's own.

    Derived rather than resolved against a repository root: the caller already
    decided how this store is spelled in a citation, and the roll writes its
    archives in a fixed place relative to the ledger, so the two compose.
    """
    parent = ledger_name.rsplit("/", 1)[0] if "/" in ledger_name else ""
    prefix = f"{parent}/" if parent else ""
    return f"{prefix}{ARCHIVE_DIR_NAME}/{filename}"


def _archive_is_in_window(path: Path, cutoff: datetime) -> bool:
    """Whether `path` can hold a row at or after `cutoff`.

    The roll date in the name is preferred over the file's mtime, and the order
    is not arbitrary: `git checkout` rewrites every mtime in the tree, so an
    mtime-first bound would read every archive on a freshly cloned runner --
    the exact cost the bound exists to avoid. mtime answers only for a file the
    roll did not name in its own shape, where nothing else is available.
    """
    match = _ARCHIVE_DATE_RE.search(path.name)
    if match is not None:
        try:
            rolled_on = (
                datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC).date()
            )
        except ValueError:
            rolled_on = None
        if rolled_on is not None:
            return rolled_on >= cutoff.date()
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        # Unreadable and unnamed: include it, and let the read fail loudly
        # rather than drop a file that might carry a live claim.
        return True
    return modified >= cutoff


def _pointer_archives(text: str, cutoff: datetime) -> set[str]:
    """Archive filenames the live ledger's own roll pointer claims exist, for
    rolls that happened at or after `cutoff`."""
    named: set[str] = set()
    for match in _ROLL_POINTER_RE.finditer(text):
        try:
            marker = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        archive = marker.get("archive")
        rolled_at = marker.get("rolled_at")
        if not isinstance(archive, str) or not isinstance(rolled_at, str):
            continue
        moment = _parse_stamp(rolled_at)
        if moment is None or moment < cutoff:
            continue
        named.add(archive.rsplit("/", 1)[-1])
    return named


def window_sources(
    ledger: Path,
    ledger_name: str,
    *,
    now: datetime,
    hours: int = STALENESS_HOURS,
) -> list[Source]:
    """Every file that can carry a claim still live at `now`, oldest first.

    The live ledger is always LAST, because replay order is the claim's own
    history: a RELEASE written after a rolled CLAIM has to be applied to that
    claim, not to nothing.
    """
    cutoff = now - timedelta(hours=hours)
    live_text = ledger.read_text(encoding="utf-8")

    archive_dir = archive_dir_for(ledger)
    present: dict[str, Path] = {}
    if archive_dir.is_dir():
        for path in archive_dir.glob(f"{ledger.stem}_*.md"):
            if path.is_file():
                present[path.name] = path

    for filename in sorted(_pointer_archives(live_text, cutoff)):
        if filename not in present:
            raise ClaimStoreIncomplete(
                f"{ledger_name} records a roll into {_archive_name(ledger_name, filename)} "
                f"inside the {hours}h staleness window, and that file is not readable at "
                f"{archive_dir}. Every claim the roll moved would resolve as UNCLAIMED, "
                "which reads as a clean bill of health over exactly the rows this "
                "refuses to guess about. THE CLAIM STORE IS INCOMPLETE.\n"
                "    The usual cause is a roll whose archive was never committed "
                "alongside the pointer it wrote (OMN-18620), or a sparse checkout whose "
                f"pattern does not cover {_archive_name(ledger_name, '')}. The remedy is "
                "to make the file readable, never to widen the window or drop the check."
            )

    selected = [
        path for path in present.values() if _archive_is_in_window(path, cutoff)
    ]
    sources: list[Source] = []
    for path in sorted(selected, key=lambda item: item.name):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ClaimStoreIncomplete(
                f"{_archive_name(ledger_name, path.name)} is inside the {hours}h "
                f"staleness window and could not be read ({exc}). THE CLAIM STORE IS "
                "INCOMPLETE."
            ) from exc
        sources.append(Source(_archive_name(ledger_name, path.name), text))
    sources.append(Source(ledger_name, live_text))
    return sources


@dataclass(frozen=True)
class Holder:
    lane: str
    fence: int
    claim_line: int
    claimed_at: str
    last_activity_at: str
    state: str  # "held" | "stale"
    # WHICH FILE the claim row is in. Not decoration: once the ledger rolls,
    # `<live ledger>:<line>` names a line that holds a different row, or no row
    # at all, and a citation the reader cannot follow is worse than none.
    source: str


def _fields(line: str) -> list[str]:
    return line.split("|")


def _stamp(line: str) -> str | None:
    match = _STAMP_RE.match(line)
    return match.group(1) if match else None


def _parse_stamp(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _row_class(line: str) -> str | None:
    if _stamp(line) is None:
        return None
    fields = _fields(line)
    if len(fields) < 2:
        return None
    candidate = fields[1].strip().upper()
    return candidate if candidate.isalpha() or "-" in candidate else None


def _lane(line: str) -> str | None:
    for field in _fields(line):
        match = _LANE_RE.match(field)
        if match:
            return match.group(1)
    return None


def _subjects(line: str) -> frozenset[str]:
    """The tickets a row is ABOUT, from its declared ticket field.

    Only the declared field. Reading every identifier in the row would make a
    row that merely cites a related ticket act on it -- the over-broad shape
    that, in the ruling guard, condemned seven live rows where the defect
    accounted for two.
    """
    found: set[str] = set()
    for field in _fields(line):
        if _SUBJECT_FIELD_RE.match(field):
            found.update(_TICKET_RE.findall(field))
    return frozenset(found)


def _field_value(line: str, pattern: re.Pattern[str]) -> str | None:
    for field in _fields(line):
        match = pattern.match(field)
        if match:
            return match.group(1)
    return None


def _cites_stale(line: str) -> bool:
    return any(_STALE_CITATION_RE.match(field) for field in _fields(line))


def ticket_from_branch(branch: str) -> str | None:
    match = _BRANCH_TICKET_RE.search(branch)
    return f"OMN-{match.group(1)}" if match else None


def _is_stale(record: dict[str, Any], now: datetime) -> bool:
    last = _parse_stamp(str(record["last_activity_at"]))
    if last is None:
        return True
    return now - last > timedelta(hours=STALENESS_HOURS)


def build_index(text: str, ledger_name: str, *, now: datetime) -> dict[str, Any]:
    """Replay `text` into a ticket-to-holder map.

    One source. This is the shape for a caller that already holds the text and
    is asking about that text alone -- a test, or the append path's in-lock
    read. A caller resolving the real store wants `window_sources` +
    `build_index_from_sources`, because the store is the live ledger AND the
    rolls it has spilled into.
    """
    return build_index_from_sources([Source(ledger_name, text)], now=now)


def build_index_from_sources(
    sources: Sequence[Source], *, now: datetime
) -> dict[str, Any]:
    """Replay every source, in order, into one ticket-to-holder map.

    Order is the claim's own history: oldest file first, the live ledger last.
    Each record remembers which source its claim row came from, so a refusal
    cites the file that actually holds the row.
    """
    if not sources:
        raise ValueError("build_index_from_sources needs at least one source")
    tickets: dict[str, dict[str, Any]] = {}
    for source in sources:
        _replay(source, tickets, now)

    for record in tickets.values():
        record["state"] = "stale" if _is_stale(record, now) else "held"

    live = sources[-1]
    return {
        "version": INDEX_VERSION,
        "source_ledger": live.name,
        "source_line_count": len(live.text.splitlines()),
        "source_digest": _digest(live.text),
        "sources": [
            {
                "name": source.name,
                "line_count": len(source.text.splitlines()),
                "digest": _digest(source.text),
            }
            for source in sources
        ],
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets": tickets,
    }


def _digest(text: str) -> str:
    return hashlib.sha256("\n".join(text.splitlines()).encode("utf-8")).hexdigest()


def _replay(source: Source, tickets: dict[str, dict[str, Any]], now: datetime) -> None:
    lines = source.text.splitlines()

    for number, line in enumerate(lines, start=1):
        row_class = _row_class(line)
        if row_class is None:
            continue
        lane = _lane(line)
        if lane is None:
            continue
        subjects = _subjects(line)
        if not subjects:
            continue
        stamp = _stamp(line)
        if stamp is None:
            continue

        for ticket in subjects:
            current = tickets.get(ticket)
            live = current is not None and not _is_stale(
                current, _parse_stamp(stamp) or now
            )

            if row_class == "CLAIM":
                if live and current is not None and current["lane"] != lane:
                    continue  # the first claim holds; the second is the collision
                if live and current is not None:
                    current["last_activity_at"] = stamp
                    continue
                tickets[ticket] = {
                    "lane": lane,
                    "fence": (current["fence"] if current else 0) + 1,
                    "claim_line": number,
                    "claimed_at": stamp,
                    "last_activity_at": stamp,
                    "source": source.name,
                }
                continue

            if current is None:
                continue

            if row_class == "RELEASE":
                # Only the holder releases. Otherwise release is a way for any
                # lane to take a ticket in two rows, which is the collision this
                # exists to make visible rather than to enable.
                if current["lane"] == lane:
                    del tickets[ticket]
                continue

            if row_class == "HANDOVER":
                receiver = _field_value(line, _TO_RE)
                if current["lane"] == lane and receiver:
                    tickets[ticket] = {
                        "lane": receiver,
                        "fence": current["fence"] + 1,
                        "claim_line": number,
                        "claimed_at": stamp,
                        "last_activity_at": stamp,
                        "source": source.name,
                    }
                continue

            if row_class == "RECLAIM":
                # Only against a claim that is ACTUALLY stale, and only citing
                # the row it supersedes. A reclaim that cites nothing is just a
                # second claim, and the citation is what makes the takeover
                # resolvable by reading the file afterwards.
                if live or not _cites_stale(line):
                    if current["lane"] == lane:
                        current["last_activity_at"] = stamp
                    continue
                tickets[ticket] = {
                    "lane": lane,
                    "fence": current["fence"] + 1,
                    "claim_line": number,
                    "claimed_at": stamp,
                    "last_activity_at": stamp,
                    "source": source.name,
                }
                continue

            # RENEW and every other classed row by the holder: activity.
            #
            # Renewal is deliberately NOT a heartbeat. A lease that expires under
            # a running holder is OMN-17005's most dangerous finding, and a
            # heartbeat somebody has to remember fails the same way one step
            # later. Lanes already write progress, friction and blocked rows on
            # their tickets, so the renewal is the work they were already doing.
            if current["lane"] == lane:
                current["last_activity_at"] = stamp


def holder(index: dict[str, Any], ticket: str) -> Holder | None:
    record = index.get("tickets", {}).get(ticket)
    if record is None:
        return None
    return Holder(
        lane=str(record["lane"]),
        fence=int(record["fence"]),
        claim_line=int(record["claim_line"]),
        claimed_at=str(record["claimed_at"]),
        last_activity_at=str(record["last_activity_at"]),
        state=str(record.get("state", "held")),
        # An index written before this field existed carries no source. It
        # falls back to the live ledger, which is where every claim in such an
        # index came from -- the index was single-source by construction.
        source=str(record.get("source") or index.get("source_ledger", "<ledger>")),
    )


def index_is_stale(index: dict[str, Any], text: str) -> bool:
    """Whether `index` was built from something other than the current prefix of
    `text`. Digest as well as line count: a rewritten row leaves the count
    unchanged, and an index that missed it would answer confidently and wrongly.
    """
    lines = text.splitlines()
    count = int(index.get("source_line_count", -1))
    if count != len(lines):
        return True
    return _digest("\n".join(lines[:count])) != index.get("source_digest")


def sources_are_stale(index: dict[str, Any], sources: Sequence[Source]) -> bool:
    """Whether `index` was built from something other than exactly `sources`.

    Every source, by name, length AND digest. Validating the live ledger alone
    would serve a pre-roll answer for as long as the live file happened not to
    change -- and the moment a roll matters is the moment it just changed the
    OTHER file.

    An index carrying no `sources` key predates this and is treated as stale,
    which costs one rebuild and cannot answer wrongly.
    """
    recorded = index.get("sources")
    if not isinstance(recorded, list) or len(recorded) != len(sources):
        return True
    for entry, source in zip(recorded, sources):
        if not isinstance(entry, dict):
            return True
        lines = source.text.splitlines()
        if entry.get("name") != source.name or entry.get("line_count") != len(lines):
            return True
        if entry.get("digest") != _digest(source.text):
            return True
    return False


def save_index(index: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_index(path: Path) -> dict[str, Any] | None:
    """The stored index, or None when there is nothing trustworthy to read.

    None means ABSENT, and absent means rebuild. Returning an empty index for an
    unreadable file would report every ticket unclaimed -- a gate passing
    exactly the case it exists to catch.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
        return None
    if not isinstance(data.get("tickets"), dict):
        return None
    return data


def resolve_index(
    ledger: Path, index_path: Path, ledger_name: str, *, now: datetime
) -> dict[str, Any]:
    """The index for `ledger` AND the rolls inside the staleness window, rebuilt
    and re-saved whenever the cache is absent, unreadable, wrong-version or
    behind any of them. This is the entry point a hook calls."""
    sources = window_sources(ledger, ledger_name, now=now)
    cached = load_index(index_path)
    if cached is not None and not sources_are_stale(cached, sources):
        for record in cached.get("tickets", {}).values():
            record["state"] = "stale" if _is_stale(record, now) else "held"
        return cached
    rebuilt = build_index_from_sources(sources, now=now)
    save_index(rebuilt, index_path)
    return rebuilt


def _describe(held: Holder, ledger_name: str) -> str:
    # The HOLDER's own source, not the live ledger's name. After a roll the row
    # is in an archive, and citing the live file sends the reader to a line
    # that now holds somebody else's row (OMN-18791).
    del ledger_name
    return (
        f"{held.lane} (claim {held.source}:{held.claim_line}, taken {held.claimed_at}, "
        f"last active {held.last_activity_at}, fence {held.fence})"
    )


def _release_paths(ticket: str, held: Holder, ledger_name: str) -> str:
    # Canonical rows only (OMN-19256): the append path refuses HANDOVER and
    # RECLAIM, so the path this prints must be one ledger_lock.py admits. A
    # handover is the holder's RELEASE followed by the receiver's CLAIM, and a
    # stale takeover is a CLAIM naming the stale claim -- _replay already treats
    # both exactly as the old rows did.
    del ledger_name
    return (
        "Release path -- the holder releases, then the new lane claims:\n"
        f"    <ts> | RELEASE | lane={held.lane} | re={held.claimed_at} | ticket={ticket} | <why it is being given up>\n"
        f"    <ts> | CLAIM | lane=<your lane> | ticket={ticket} | <scope and cost sentence>\n"
        f"and if that lane is gone, wait for the claim to go stale "
        f"({STALENESS_HOURS}h with no row from it on this ticket) and then:\n"
        f"    <ts> | CLAIM | lane=<your lane> | ticket={ticket} | "
        f"supersedes-claim={held.claimed_at} | last_activity={held.last_activity_at} | <why>"
    )


def refusal_for_claim(
    index: dict[str, Any], ticket: str, lane: str, *, now: datetime
) -> str | None:
    """Why `lane` may not claim `ticket`, or None."""
    held = holder(index, ticket)
    if held is None or held.state == "stale" or held.lane == lane:
        return None
    ledger_name = str(index.get("source_ledger", "<ledger>"))
    return (
        f"{ticket} is already held by {_describe(held, ledger_name)}. "
        "Two lanes holding one ticket is what produced the 2026-09-12 cross-lane push.\n"
        + _release_paths(ticket, held, ledger_name)
    )


def refusal_for_push(
    index: dict[str, Any],
    ticket: str,
    lane: str,
    *,
    fence: int | None,
    now: datetime,
) -> str | None:
    """Why `lane` may not push to `ticket`'s branch, or None.

    Two distinct refusals, and both matter:
      * another LIVE lane holds the ticket;
      * this lane holds it but the commits carry a fence BEHIND the current one,
        which means the claim was reclaimed while the lane kept working. Without
        the fence that lane is indistinguishable from the current holder and the
        refusal has nothing to fire on (OMN-17005 AC7).

    An UNCLAIMED ticket does not block a push. That is deliberate: the refusal
    fires on a ticket held by another lane, never on the absence of a claim.
    Requiring a claim for every push turns a coordination mechanism into a tax
    on ordinary work, and a tax on ordinary work is what gets routed around.
    """
    held = holder(index, ticket)
    if held is None or held.state == "stale":
        return None
    ledger_name = str(index.get("source_ledger", "<ledger>"))
    if held.lane != lane:
        return (
            f"push to {ticket} refused: it is held by {_describe(held, ledger_name)}, "
            f"and this lane is {lane}.\n" + _release_paths(ticket, held, ledger_name)
        )
    if fence is not None and fence < held.fence:
        return (
            f"push to {ticket} refused: these commits carry fence {fence}, but the live claim "
            f"is at fence {held.fence} -- the claim was taken over while this lane kept working "
            f"({held.source}:{held.claim_line}). Re-read the ledger before continuing.\n"
            + _release_paths(ticket, held, ledger_name)
        )
    return None


# ---------------------------------------------------------------------------
# Atomic transitions
# ---------------------------------------------------------------------------


class ClaimCollision(RuntimeError):
    """A transition refused because another lane already holds the ticket."""


_LOCK_POLL_SECONDS = 0.02


@contextlib.contextmanager
def transition_lock(ledger: Path, *, timeout: float = 300.0) -> Iterator[None]:
    """One exclusive lock across the whole read-decide-append-reindex section.

    An ATOMIC DIRECTORY, because macOS has no flock(1) and this has to work with
    the standard library alone -- the same mechanism the ledger append tool
    already uses, deliberately, so the two cannot drift into two different
    notions of who holds the file.

    The critical section has to cover the DECISION as well as the write. Two
    lanes that each read the ledger, each see no holder, and then each append a
    claim produce two holders with no error anywhere -- which is the collision
    this whole phase exists to remove, reintroduced by locking only the write.
    """
    lock = ledger.with_suffix(ledger.suffix + ".claimlock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"claim lock at {lock} held for more than {timeout}s"
                ) from None
            time.sleep(_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.rmdir()


def append_transition(
    ledger: Path,
    row: str,
    *,
    ledger_name: str,
    index_path: Path | None = None,
    now: datetime | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Append one transition row under the lock, then refresh the index.

    Refuses with ClaimCollision when the row is a CLAIM on a ticket another live
    lane holds. The refusal happens INSIDE the lock, against the ledger as it is
    on disk at that instant, so a concurrent claimant cannot slip between the
    check and the write.

    Returns the refreshed index.
    """
    moment = now or datetime.now(UTC)
    with transition_lock(ledger, timeout=timeout):
        if ledger.exists():
            text = ledger.read_text(encoding="utf-8")
            # The WHOLE window, not just the live file. A collision refusal
            # that could not see a rolled claim would let a second lane claim a
            # ticket somebody is holding -- the same false negative as the push
            # refusal, on the write path (OMN-18791).
            sources = window_sources(ledger, ledger_name, now=moment)
        else:
            text = ""
            sources = [Source(ledger_name, text)]
        index = build_index_from_sources(sources, now=moment)

        if _row_class(row) == "CLAIM":
            lane = _lane(row)
            if lane is not None:
                for ticket in _subjects(row):
                    reason = refusal_for_claim(index, ticket, lane, now=moment)
                    if reason is not None:
                        raise ClaimCollision(reason)

        if text and not text.endswith("\n"):
            text += "\n"
        text += row.rstrip("\n") + "\n"
        tmp = ledger.with_suffix(ledger.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(ledger)

        refreshed = build_index_from_sources(
            [*sources[:-1], Source(ledger_name, text)], now=moment
        )
        if index_path is not None:
            save_index(refreshed, index_path)
        return refreshed


def _main(argv: list[str]) -> int:
    """Read-only reporter: `claim_index.py <ledger> [ticket]`."""
    if not argv or len(argv) > 2:
        print("usage: claim_index.py <ledger-path> [OMN-XXXX]", file=sys.stderr)
        return 2
    ledger = Path(argv[0])
    now = datetime.now(UTC)
    sources = window_sources(ledger, str(ledger), now=now)
    index = build_index_from_sources(sources, now=now)
    print(
        "claim store: "
        + ", ".join(
            f"{source.name} ({len(source.text.splitlines())} lines)"
            for source in sources
        )
    )
    if len(argv) == 2:
        held = holder(index, argv[1])
        if held is None:
            print(f"{argv[1]}: unclaimed")
            return 0
        print(f"{argv[1]}: {_describe(held, str(ledger))} state={held.state}")
        return 0
    live = {t: r for t, r in index["tickets"].items() if r["state"] == "held"}
    print(
        f"tickets with a live holder (activity within {STALENESS_HOURS}h): {len(live)}"
    )
    for ticket, record in sorted(live.items()):
        print(
            f"  {ticket:<12} lane={record['lane']} "
            f"claim={record.get('source', index['source_ledger'])}:{record['claim_line']}"
        )
    print(f"tickets with a stale claim: {len(index['tickets']) - len(live)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
