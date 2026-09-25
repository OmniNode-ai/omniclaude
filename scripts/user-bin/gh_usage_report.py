#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Attribute this host's GitHub calls to lanes, from the gh shim's usage log (OMN-19585).

The shim (``scripts/user-bin/gh``) appends one JSON line per invocation to
``${XDG_CACHE_HOME:-$HOME/.cache}/omni/gh-usage/<UTC date>.jsonl``. This report
reads a window of that log and prints, per lane, the call count, an estimate of
the core REST requests those calls spent and the hourly rate, and it names the
share it cannot attribute.

Request counts are ESTIMATES: calls are weighted by the per-command cost table
of the 2026-09-25 measurement report (knowledge-base-internal
``beta/tracking/2026-09-25-gh-quota-measurement.md``, section (a)). Only
``gh api`` = 1 was validated live there. ``gh api graphql`` calls spend
GraphQL points, a separate bucket, and are counted in their own column.
Cache hits and local subcommands (``auth``, ``config``) cost nothing.

Attribution:
  * ``lane_source=env``: ``ONEX_LANE`` was set; the lane is named.
  * ``lane_source=session``: a Claude Code session id; attributed to the
    session. With ``--transcripts <project dir>`` the report narrows each such
    call to the one sub-agent whose Bash tool call was running when the call
    was made, and names it by its dispatch label. A call that no running tool
    call, or more than one, could have made stays on the session.
  * ``lane_source=parent``: neither was set (a launchd job, a Codex lane, a
    terminal). This is the unattributed share.

Usage:
  gh_usage_report.py [--since 1h|30m|2026-09-25T14:00:00Z] [--until ...]
                     [--log-dir DIR] [--transcripts DIR] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

# measurement report section (a): assumed REST requests per command class
COST_TABLE: dict[str, int] = {
    "api": 1,
    "pr checks": 4,
    "pr view": 2,
    "pr list": 1,
    "pr merge": 2,
}
RUN_COST = 2
DEFAULT_COST = 1
FREE_METHODS = frozenset({"LOCAL"})

_DURATION = re.compile(r"^(\d+)([smhd])$")


def parse_when(text: str, now: datetime) -> datetime:
    m = _DURATION.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * n
        return now - timedelta(seconds=seconds)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def core_cost(rec: dict[str, object]) -> int:
    """Estimated core REST requests one logged call spent."""
    if rec.get("cache") == "hit" or rec.get("method") in FREE_METHODS:
        return 0
    cls = str(rec.get("cls", ""))
    if cls == "api graphql":
        return 0
    if cls in COST_TABLE:
        return COST_TABLE[cls]
    if cls.startswith("run "):
        return RUN_COST
    return DEFAULT_COST


def is_graphql(rec: dict[str, object]) -> bool:
    return rec.get("cls") == "api graphql" and rec.get("cache") != "hit"


def default_log_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "omni" / "gh-usage"


def load_records(
    log_dir: Path, since: datetime, until: datetime
) -> list[dict[str, object]]:
    if not log_dir.is_dir():
        raise SystemExit(
            f"gh_usage_report: no usage log directory at {log_dir}; is the gh shim installed?"
        )
    out: list[dict[str, object]] = []
    day = since.date()
    while day <= until.date():
        path = log_dir / f"{day.isoformat()}.jsonl"
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    rec = json.loads(line)
                    ts = datetime.fromisoformat(str(rec["ts"]).replace("Z", "+00:00"))
                except (ValueError, KeyError, TypeError):
                    continue
                if since <= ts <= until:
                    rec["_ts"] = ts
                    out.append(rec)
        day += timedelta(days=1)
    return out


# --- sub-agent resolution from Claude Code transcripts ----------------------


class Interval(NamedTuple):
    start: datetime
    end: datetime
    agent: str
    command: str


# A Bash command that can reach gh: gh itself, or a skill script that shells out to it.
GH_CALLER = re.compile(
    r"\bgh\b|pr_snapshot|ci_state|drain_map|pause_check|runtime_class|plugin_bump_check|base_compare"
)


class SessionIndex:
    def __init__(self) -> None:
        self.intervals: list[Interval] = []
        self.labels: dict[str, str] = {}


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def index_session(session_dir: Path, since: datetime) -> SessionIndex:
    """Bash tool-call intervals per sub-agent, and each agent's dispatch label."""
    idx = SessionIndex()
    sub = session_dir / "subagents"
    if not sub.is_dir():
        return idx
    horizon = since.timestamp() - 3600
    for meta in sub.rglob("agent-*.meta.json"):
        agent = meta.name[len("agent-") : -len(".meta.json")]
        try:
            data = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        label = data.get("name") or data.get("description") or data.get("agentType")
        if isinstance(label, str) and label:
            idx.labels[agent] = label
    for transcript in sub.rglob("agent-*.jsonl"):
        try:
            if transcript.stat().st_mtime < horizon:
                continue
        except OSError:
            continue
        agent = transcript.stem[len("agent-") :]
        starts: dict[str, tuple[datetime, str]] = {}
        with transcript.open(errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = _parse_ts(rec.get("timestamp"))
                content = (rec.get("message") or {}).get("content")
                if ts is None or not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "tool_use" and part.get("name") == "Bash":
                        command = str((part.get("input") or {}).get("command", ""))
                        starts[str(part.get("id"))] = (ts, command)
                    elif part.get("type") == "tool_result":
                        begun = starts.pop(str(part.get("tool_use_id")), None)
                        if begun is not None:
                            idx.intervals.append(
                                Interval(begun[0], ts, agent, begun[1])
                            )
        # A tool call still running when the transcript was read.
        for begun_at, command in starts.values():
            idx.intervals.append(Interval(begun_at, datetime.now(UTC), agent, command))
    return idx


def resolve_agent(idx: SessionIndex, ts: datetime) -> str | None:
    slack = timedelta(seconds=2)
    running = [iv for iv in idx.intervals if iv.start - slack <= ts <= iv.end + slack]
    agents = {iv.agent for iv in running}
    if len(agents) > 1:
        # Several sub-agents had a Bash call running: keep those whose command can reach gh.
        agents = {iv.agent for iv in running if GH_CALLER.search(iv.command)}
    if len(agents) == 1:
        agent = agents.pop()
        return idx.labels.get(agent, f"agent:{agent}")
    return None


def find_session_dir(transcripts: Path, session: str) -> Path | None:
    direct = transcripts / session
    if direct.is_dir():
        return direct
    for child in transcripts.glob(f"*/{session}"):
        if child.is_dir():
            return child
    return None


# --- report ------------------------------------------------------------------


def build_report(
    records: list[dict[str, object]],
    since: datetime,
    until: datetime,
    transcripts: Path | None,
) -> dict[str, object]:
    hours = max((until - since).total_seconds() / 3600, 1 / 60)
    indexes: dict[str, SessionIndex] = {}
    lanes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    unattributed_calls = 0
    unattributed_cost = 0
    total_cost = 0
    for rec in records:
        lane = str(rec.get("lane") or "parent:unknown")
        source = rec.get("lane_source")
        if source == "session" and transcripts is not None:
            session = str(rec.get("session", ""))
            if session not in indexes:
                sdir = find_session_dir(transcripts, session)
                indexes[session] = (
                    index_session(sdir, since) if sdir else SessionIndex()
                )
            ts = rec["_ts"]
            assert isinstance(ts, datetime)
            named = resolve_agent(indexes[session], ts)
            if named:
                lane = named
        cost = core_cost(rec)
        total_cost += cost
        row = lanes[lane]
        row["calls"] += 1
        row["core_requests_est"] += cost
        row["graphql_calls"] += 1 if is_graphql(rec) else 0
        row["cache_hits"] += 1 if rec.get("cache") == "hit" else 0
        if source not in ("env", "session"):
            unattributed_calls += 1
            unattributed_cost += cost
    total_calls = len(records)
    rows: list[dict[str, str | int | float]] = []
    for lane, row in lanes.items():
        rows.append(
            {
                "lane": lane,
                "calls": int(row["calls"]),
                "core_requests_est": int(row["core_requests_est"]),
                "core_requests_per_hour_est": round(
                    row["core_requests_est"] / hours, 1
                ),
                "graphql_calls": int(row["graphql_calls"]),
                "cache_hits": int(row["cache_hits"]),
            }
        )
    rows.sort(
        key=lambda r: (
            -float(r["core_requests_est"]),
            -float(r["calls"]),
            str(r["lane"]),
        )
    )
    return {
        "since": since.isoformat().replace("+00:00", "Z"),
        "until": until.isoformat().replace("+00:00", "Z"),
        "hours": round(hours, 3),
        "total_calls": total_calls,
        "total_core_requests_est": total_cost,
        "unattributed_calls": unattributed_calls,
        "unattributed_core_requests_est": unattributed_cost,
        "unattributed_share_of_calls": round(unattributed_calls / total_calls, 4)
        if total_calls
        else 0.0,
        "attributed_share_of_calls": round(1 - unattributed_calls / total_calls, 4)
        if total_calls
        else 0.0,
        "estimate_basis": "measurement report 2026-09-25 section (a) cost table; only gh api = 1 validated live",
        "lanes": rows,
    }


def render_text(rep: dict[str, object]) -> str:
    share = rep["unattributed_share_of_calls"]
    assert isinstance(share, float | int)
    lines = [
        f"gh usage {rep['since']} .. {rep['until']} ({rep['hours']} h)",
        f"calls {rep['total_calls']}, core requests (estimate) {rep['total_core_requests_est']}",
        f"UNATTRIBUTED: {rep['unattributed_calls']} calls "
        f"({float(share) * 100:.1f}%), "
        f"{rep['unattributed_core_requests_est']} core requests (estimate)",
        "",
        f"{'lane':<48} {'calls':>6} {'core_est':>9} {'core/h':>8} {'gql':>5} {'hits':>5}",
    ]
    lanes = rep["lanes"]
    assert isinstance(lanes, list)
    for r in lanes:
        lines.append(
            f"{str(r['lane'])[:48]:<48} {r['calls']:>6} {r['core_requests_est']:>9} "
            f"{r['core_requests_per_hour_est']:>8} {r['graphql_calls']:>5} {r['cache_hits']:>5}"
        )
    lines.append("")
    lines.append(f"basis: {rep['estimate_basis']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--since", default="1h")
    ap.add_argument("--until", default=None)
    ap.add_argument("--log-dir", type=Path, default=None)
    ap.add_argument("--transcripts", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.now(UTC)
    since = parse_when(args.since, now)
    until = parse_when(args.until, now) if args.until else now
    records = load_records(args.log_dir or default_log_dir(), since, until)
    rep = build_report(records, since, until, args.transcripts)
    print(json.dumps(rep, indent=2) if args.json else render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
